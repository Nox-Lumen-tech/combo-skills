# 增量更新与 Copy-on-Write 快照机制

## 概述

编辑完成后，ES chunks 的更新分两种场景：

| 场景 | 操作 | 说明 |
|------|------|------|
| 原地编辑（文件名不变） | `workspace_ops(action="trigger_chunk_update")` | 在现有 ws_doc_id 上增量更新 |
| 另存为新文件（文件名变了） | `workspace_ops(action="snapshot_and_index")` | **Copy-on-Write**：创建新 ws_doc_id + full_reparse |

**核心原则**：每个产出文件独立拥有一份 ES chunks，不覆盖父版本。

## Copy-on-Write 快照（snapshot_and_index）

### 为什么需要

当 Agent 编辑文档并保存为新文件名（如 `合同.docx` → `合同_numbered.docx`）时：
- 原 ws_doc_id 的 chunks 仍指向原文件（版本、名称、内容都是旧的）
- 按新文件名搜索 ES → 0 结果
- 原地覆盖 ES 会导致版本不对应

### 快照流程

```
write_file_bytes 保存新文件（outputs/合同_numbered.docx）
  ↓
Agent 调用 workspace_ops(action="snapshot_and_index")
  参数: parent_ws_doc_id, output_path, source_type, old_range(可选)
  ↓
系统内部：
  Step 1: Fork 父 chunks → new_ws_doc_id
          复制所有 chunks，更新 doc_id / workspace_path / docnm_kwd
          → 新 ws_doc_id 拥有完整基线（和父文件内容一致）
  Step 2: trigger_chunk_update(new_ws_doc_id, output_path, old_range)
          在基线上做增量更新（复用现有机制）
          ├─ 有 old_range → incremental_update_chunks()（快）
          └─ 没 old_range → _full_reparse_fallback()（慢但正确）
  ↓
返回 new_ws_doc_id（后续检索用这个 ID）
  ↓
下轮 unified_search(doc_ids="new_ws_doc_id") 立即可搜
```

**为什么必须先 Fork？**

Fork 是增量更新的前提。增量更新需要：
1. 已有 chunks 作为基线（知道哪些旧 chunks 要删）
2. 段落偏移信息（后续 chunks 的 para_start_int 要加 delta）
3. 非修改范围的 chunks 保持不变

没有基线 → 增量更新无法工作 → 只能 full reparse。有了基线 → 大部分 chunks 直接复用 → 只重解析被改的范围。

### 实现要点

```python
def _snapshot_and_index(self, params: dict) -> dict:
    parent_ws_doc_id = params["parent_ws_doc_id"]
    output_path = params["output_path"]
    source_type = params.get("source_type", "docx")
    old_range = params.get("old_range")           # 可选
    new_para_count = params.get("new_para_count")  # 可选

    # 1. 生成新 ws_doc_id（基于 output_path 的 hash，保证幂等）
    new_ws_doc_id = f"ws_{sid}_{xxhash.xxh64(output_path.encode()).hexdigest()[:16]}"

    # 2. 幂等：如果 new_ws_doc_id 已存在，先清理
    es.delete_by_query(index=index_name, body={"query": {"term": {"doc_id": new_ws_doc_id}}})

    # 3. Fork 父 chunks → 新 ws_doc_id（建立基线）
    parent_chunks = es.search(
        index=index_name,
        body={"query": {"term": {"doc_id": parent_ws_doc_id}}, "size": 10000},
    )
    new_docnm = output_path.rsplit("/", 1)[-1]
    batch = []
    for hit in parent_chunks["hits"]["hits"]:
        ck = hit["_source"].copy()
        ck["doc_id"] = new_ws_doc_id
        ck["workspace_path"] = output_path          # 不加 bucket 前缀，与 minio.get("workspace", key) 一致
        ck["docnm_kwd"] = new_docnm
        ck["parent_ws_doc_id"] = parent_ws_doc_id
        ck["is_workspace_version"] = True
        ck["id"] = xxhash.xxh64(
            (ck.get("content_with_weight", "") + new_ws_doc_id).encode()
        ).hexdigest()
        batch.append(ck)
    es.bulk_index(index_name, batch, refresh=True)

    # 4. 在基线上增量更新（复用现有 trigger_chunk_update 机制）
    if old_range:
        incremental_update_chunks(
            tenant_id, new_ws_doc_id, output_path,   # 不加 "workspace/" 前缀
            source_type, old_range, new_para_count,
        )
    else:
        _full_reparse_fallback(
            tenant_id, new_ws_doc_id, output_path, source_type,  # 同上
        )

    return {
        "status": "snapshot_created",
        "new_ws_doc_id": new_ws_doc_id,
        "chunks_forked": len(batch),
        "update_mode": "incremental" if old_range else "full_reparse",
    }
```

### 版本链示例

```
KB: 合同.docx (doc_id=abc, 296 chunks)
  │
  ├─ copy_kb_document
  │    └─ _fork_chunks_to_workspace(abc → ws_{sid}_abc)
  │
  ws_{sid}_abc (296 chunks, docnm=合同.docx)         ← 基线快照
  │
  ├─ 编号 + snapshot_and_index
  │    ├─ fork(ws_{sid}_abc → ws_{sid}_{hash1})       ← 复制基线
  │    └─ trigger_chunk_update(ws_{sid}_{hash1})      ← 增量更新编号部分
  │
  ws_{sid}_{hash1} (298 chunks, docnm=合同_numbered.docx) ← 编号后版本
  │
  ├─ 加链接 + snapshot_and_index
  │    ├─ fork(ws_{sid}_{hash1} → ws_{sid}_{hash2})   ← 复制编号后基线
  │    └─ trigger_chunk_update(ws_{sid}_{hash2})      ← 增量更新链接部分
  │
  ws_{sid}_{hash2} (300 chunks, docnm=合同_linked.docx)   ← 最终版本
```

每个版本独立可搜，搜任何一个版本都能找到对应内容。
增量更新只处理被改的范围，未修改的 chunks 从 fork 直接继承。

## 原地增量更新（trigger_chunk_update）

适用于文件名不变、只修改局部内容的场景。

### 触发时机
- docx skill / pptx skill / execute_code 编辑完成后
- 文件写回同一路径（文件名不变）
- Agent 调用 `workspace_ops(action="trigger_chunk_update")` 触发 ES 异步更新

### 更新流程
```
编辑完成
  ↓
MinIO 同步写入（立即可下载，同一路径）
  ↓
Agent 调用 workspace_ops(action="trigger_chunk_update")
  ↓
异步：incremental_update_chunks()
  ↓
ES chunks 增量更新（refresh=true）
  ↓
下轮搜索立即可见新内容
```

## 增量更新算法

### DOCX / XLSX（带范围字段）

#### Step 0: 自动扩展边界 + 提取旧图片描述
```python
# 问题：Agent 编辑了 para [15, 20]，但 chunk_X 的 para_range=[15, 30]
# 解决：自动扩展到 [15, 30]，防止未编辑部分数据丢失

# 查询受影响 chunks 的实际边界
affected = es.search(
    index="ragflow_{tenant_id}",
    body={"query": overlap_query, "size": 10000}
)

actual_start = min(c["para_start_int"] for c in affected)
actual_end = max(c["para_end_int"] for c in affected)

# 提取旧 image chunk 的描述（避免重跑 VLM）
old_image_descs = {}
for c in affected:
    if c["chunk_type"] == "image" and c.get("content_with_weight"):
        old_image_descs[c["para_start_int"]] = c["content_with_weight"]
```

#### Step 1: 删除范围内的所有 chunks
```python
# 删除文本 + 图片 + 表格 chunks（不区分类型）
es.delete_by_query(
    index="ragflow_{tenant_id}",
    body={"query": overlap_query},
    refresh=True
)
```

#### Step 2: 重新解析受影响范围
```python
# 复用现有 chunk() 函数，新增参数
new_chunks = chunk(
    filename=workspace_path,
    binary=doc_bytes,
    from_para=actual_start,           # 新增：起始段落
    to_para=actual_end + delta,       # 新增：结束段落
    enable_vlm=False,                 # 新增：跳过 VLM
    image_descriptions=merged_descs,  # 新增：复用旧描述
    callback=lambda *a, **kw: None,
    tenant_id=tenant_id,
)
```

#### Step 3: 偏移后续 chunks 的位置字段
```python
# delta = new_para_count - (old_end - old_start + 1)
if delta != 0:
    es.update_by_query(
        index="ragflow_{tenant_id}",
        body={
            "query": {
                "bool": {
                    "must": [
                        {"term": {"doc_id": ws_doc_id}},
                        {"range": {"para_start_int": {"gt": actual_end}}}
                    ]
                }
            },
            "script": {
                "source": """
                    ctx._source.para_start_int += params.delta;
                    ctx._source.para_end_int += params.delta;
                """,
                "params": {"delta": delta}
            }
        }
    )
```

#### Step 4: 最终 refresh
```python
es.indices.refresh(index="ragflow_{tenant_id}")
```

### PPTX（单一 slide_num）

PPTX 是最简单的，因为 1 slide = 1 chunk：

#### 修改内容（不增删 slide）
```python
# 最简单：只更新对应 slide 的 chunk 内容
es.delete_by_query(
    index="ragflow_{tenant_id}",
    body={"query": {
        "bool": {"must": [
            {"term": {"doc_id": ws_doc_id}},
            {"term": {"slide_num": slide_num}}
        ]}
    }},
    refresh=True
)
# 重新解析该 slide（或直接用新内容替换）
# 写入新 chunk
# **不需要偏移任何东西**
```

#### 插入 slide
```python
# 新增 slide 的 chunk
# 偏移后续 chunks：所有 slide_num > 插入位置的 chunks，slide_num += 1
es.update_by_query(
    body={
        "script": {
            "source": "ctx._source.slide_num += 1;",
            "params": {"delta": 1}
        }
    }
)
```

#### 删除 slide
```python
# 删除 slide 的 chunk
# 偏移后续 chunks：所有 slide_num > 删除位置的 chunks，slide_num -= 1
es.update_by_query(
    body={
        "script": {
            "source": "ctx._source.slide_num -= 1;",
            "params": {"delta": -1}
        }
    }
)
```

## XLSX 的按 Sheet 隔离

XLSX 需要**按 sheet 隔离**，每个 sheet 的 chunks 独立处理和偏移：

```python
# 重叠查询限定在同一 sheet 内
overlap_query = {
    "bool": {
        "must": [
            {"term": {"doc_id": ws_doc_id}},
            {"term": {"sheet_name": sheet_name}}  # 限定 sheet
        ],
        # ... 行范围重叠条件
    }
}

# 只偏移同一 sheet 内后续 chunks
es.update_by_query(
    body={
        "query": {
            "bool": {
                "must": [
                    {"term": {"doc_id": ws_doc_id}},
                    {"term": {"sheet_name": sheet_name}},  # 限定 sheet
                    {"range": {"row_start_int": {"gt": actual_end}}}
                ]
            }
        },
        "script": {
            "source": """
                ctx._source.row_start_int += params.delta;
                ctx._source.row_end_int += params.delta;
            """,
            "params": {"delta": delta}
        }
    }
)
```

**关键差异**：修改 Sheet1 的行不会影响 Sheet2 的行号。

## 图片描述复用机制

### 为什么要复用
- VLM（Vision Language Model）调用成本高
- 编辑只改了文本，图片没动 → 旧描述（VLM 生成的）直接复用
- Agent 修改了图片 → 调用方通过 `image_descriptions` 参数覆盖

### 描述来源优先级
```python
# 合并图片描述：调用方提供的覆盖旧的（Agent 明确修改的图片优先）
merged_image_descs = {**old_image_descs, **(image_descriptions or {})}
```

| 场景 | 描述来源 | 需要 VLM？ |
|------|---------|-----------|
| 初始解析（上传时） | VLM 模型生成 | 是（默认 True） |
| 增量更新 — 图片未修改 | 从旧 chunk 的 `content_with_weight` 提取复用 | 否 |
| 增量更新 — Agent 修改/新增图片 | Agent 通过 `image_descriptions` 传入 | 否 |
| 增量更新 — 无描述 fallback | `"[图片]"` 占位符 | 否 |

## 降级策略

### 失败自动 fallback
```python
for attempt in range(max_retries + 1):
    try:
        _do_incremental_update(...)
        return  # 成功则直接返回
    except Exception as e:
        logging.error(f"Attempt {attempt + 1} failed: {e}")
        if attempt < max_retries:
            time.sleep(1 * (attempt + 1))  # 简单退避
        else:
            # 所有重试失败，fallback 到全量重解析
            _full_reparse_fallback(tenant_id, ws_doc_id, workspace_path)
```

### 全量重解析
```python
def _full_reparse_fallback(tenant_id, ws_doc_id, workspace_path):
    # 1. 删除该 ws_doc_id 的所有现有 chunks
    es.delete_by_query(
        index=f"ragflow_{tenant_id}",
        body={"query": {"term": {"doc_id": ws_doc_id}}},
        refresh=True
    )

    # 2. 全量解析文档（复用现有 chunk()，VLM 关闭）
    all_chunks = chunk(
        filename=workspace_path,
        binary=doc_bytes,
        from_para=0,
        to_para=None,  # 全文
        enable_vlm=False,
        callback=lambda *a, **kw: None,
        tenant_id=tenant_id,
    )

    # 3. 写入新 chunks
    batch = [...]
    es.bulk_index(f"ragflow_{tenant_id}", batch, refresh=True)
```

## 一致性保障

### refresh=true
- ES 写入后立即可搜
- 下轮 `unified_search` 能立即看到新内容

### 文档级锁
```python
# 防止并发 subagent 编辑同一文档
doc_lock = get_doc_lock(ws_doc_id)
with doc_lock:
    # 执行增量更新...
```

### Agent 兜底
- 当前 turn 内可用返回的 `modified_range` 兜底
- 不依赖 ES 立即一致

## 性能说明

- 所有查询都通过 `doc_id=ws_doc_id` 过滤，只影响 ONE document 的 chunks
- 一个几千页文档约 1000-2000 chunks，update_by_query 在此规模下毫秒级完成
- 最坏情况（在文档开头编辑导致所有后续 chunks 偏移）也只是更新 2000 条记录

## 错误处理

- 增量更新内置重试机制（默认 2 次重试，退避间隔递增）
- 重试全部失败后自动 fallback 到全量重解析
- 全量重解析也失败时记录 CRITICAL 日志（ES chunks 可能不一致，但 MinIO 文件是正确的）
- 所有失败都有完整日志（含 stack trace），方便排查

## Agent 调用方式

编辑完成后，Agent 调用 `workspace_ops` 触发增量更新：

```python
workspace_ops(
    action="trigger_chunk_update",
    params='{"ws_doc_id": "ws_xxx_abc", "workspace_path": "sessions/{sid}/downloads/doc.docx", "source_type": "docx", "old_range": {"para_start_int": 120, "para_end_int": 150}, "new_para_count": 25}'
)
```

- 调用立即返回 `{"status": "update_triggered"}`，ES 更新在后台异步进行
- MinIO 文件立即可下载（编辑时已同步写入）
- 不传 `old_range` 时自动 fallback 到全量重解析（慢但始终正确）
- 下轮搜索自动看到新内容（`refresh=true`）
