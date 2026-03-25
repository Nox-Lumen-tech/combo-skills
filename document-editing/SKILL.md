---
name: document-editing
description: 二进制文档（DOCX/XLSX/PPTX）部分编辑：检索定位 → skill 编辑 → ES Copy-on-Write 快照
metadata:
  tags: ["document", "editing", "docx", "xlsx", "pptx"]
  emoji: "📝"
---

# Document Editing — 二进制文档部分编辑

## ⚠️ 与 docx/xlsx/pptx skill 的关系

| Skill | 职责 | 何时使用 |
|-------|------|---------|
| **document-editing** (本 skill) | 工作流编排：ES 检索 → 定位 → 调用技术 skill → ES 快照更新 | 编辑**知识库中**的文档 |
| **docx/xlsx/pptx skill** | 技术实现：XML 操作 / 格式处理 / 创建新文档 | 编辑**本地**文件 或 被 document-editing 调用 |

**关键流程**：本 skill 负责「找到位置」，技术 skill 负责「修改内容」。

## 适用场景
用户需要修改、分析、对比知识库中的 DOCX / XLSX / PPTX 等二进制文档。

## 前置条件
- 文档已在知识库中（已被 DeepDoc 解析，ES 中有 chunks）
- chunks 包含位置信息（`para_range` / `row_range` / `slide_num`）

---

## ⚡ ES-first 原则 — 二进制文档有 ES 时优先用 ES

**核心规则：二进制文档（docx/xlsx/pptx）经过 `copy_kb_document` 或 `snapshot_and_index` 后就拥有 ES chunks。读取这些文档的内容时，必须优先走 ES search，不要用 `read_file`。**

`read_file` 读二进制文档 = 把整个文档转成纯文本塞进 context，丢失结构信息、浪费 token、还需要写代码二次解析。ES search 直接返回精确 chunk + 段落位置。

### 工具选择决策表

| 我要做什么 | 用什么 | 为什么 |
|-----------|--------|--------|
| 查某个需求/条款的内容 | `unified_search(query="关键词", doc_ids="ws_doc_id")` | 返回精确 chunk + 段落位置，token 友好 |
| 对比两份文档的差异 | 对每个对比项分别搜两个文档的 `ws_doc_id` | 逐条精确对比，不需要读整个文档 |
| 列出文档全部内容 | `unified_search(action="list_chunks", doc_ids="ws_doc_id")` | 结构化分片，带位置信息 |
| 提取文档中的特定模式（如所有编号） | `unified_search(query="编号模式关键词", doc_ids="ws_doc_id")` | 比正则扫描全文更快 |
| 修改文档二进制结构（XML/格式/超链接/高亮） | `execute_code`（下载 docx → 操作 → upload） | 需要操作二进制格式 |
| 在文档中插入新段落/章节 | `execute_code` + `docx_utils.insert_paragraphs_after()` | 禁止用 `doc.add_paragraph()`，会在末尾产生重复 |
| 读取纯文本文件（.md / .py / .json） | `read_file` | 纯文本文件没有 ES 索引 |

### 反面案例

```
❌ 错误：用 read_file 读整个 docx 来提取需求列表
   → 消耗大量 tokens，丢失结构信息，还需要写代码解析

✅ 正确：unified_search(query="FUNC_0007", doc_ids="ws_...")
   → 直接返回该需求的 chunk（含段落范围、上下文）
```

```
❌ 错误：read_file 读两个完整 docx → execute_code 逐行对比
   → 两份文档全文进 context，token 爆炸

✅ 正确：对每个需求项分别搜 EEA 和 GAC 的 ws_doc_id
   → 每次只对比两个精确 chunk，在 reasoning 中直接分析差异
```

### 什么时候用 read_file？

- 纯文本文件（`.md` / `.py` / `.json` 等），没有 ES 索引
- 需要查看二进制文件的原始格式/编码（极少见）

**判断标准很简单：二进制文档有 ES chunks → 用 ES；纯文本文件没有 ES → 用 read_file。**

---

## 工作流概览

| Step | 动作 | 说明 |
|------|------|------|
| 1 | `copy_kb_document(doc_id)` | 拷贝到 workspace/downloads + fork ES chunks → `ws_{sid}_{doc_id}` |
| 2 | `unified_search(query="...", doc_ids="ws_doc_id")` | 检索定位，返回位置信息 + `workspace_path` |
| 3 | 向用户确认修改范围 | 展示搜索结果中的文本内容 |
| 4 | skill / execute_code 编辑 | `write_file_bytes` 写入修改后的文档（可以是新文件名） |
| 5 | **`workspace_ops(action="snapshot_and_index")`** | **必须**：fork 父 ES → 新 ws_doc_id → full_reparse 新文件。不做这步 = 后续搜不到 |
| 6 | 验证 + 自动注册 | 用新 `ws_doc_id` 抽样搜索确认内容正确，展示文件卡片 |

### ⚠️ 规则：execute_code 产出新文件后必须 snapshot_and_index

**每次 `execute_code` 产出新的二进制文档（docx/xlsx/pptx）后，必须立即调用 `snapshot_and_index`，不可跳过。**

```
execute_code → write_file_bytes → snapshot_and_index → 拿到新 ws_doc_id
                                        ↑ 不做这步 = ES 里没有新文件的 chunks
                                                    = 后续 unified_search 搜不到
                                                    = 后续任务无法用 ES 对比/检索
```

**为什么**：`write_file_bytes` 只把文件存到 MinIO，不会更新 ES。没有 `snapshot_and_index`，新文件在 ES 中不存在，后续轮次的 `unified_search` 无法检索到它的内容。这会导致：
- 第二个任务想检索第一个任务的产出 → 搜不到
- 对比两份文档的差异 → 只能 `read_file` 而不是 ES 精确搜索
- ws_doc_id 不进 Digest → 后续轮次完全不知道有这个文档

**多步任务中每步都要做**：如果任务分为"编号 → 超链接 → 对比高亮"三步，每步产出新文件后都要 `snapshot_and_index`，不能只在最后一步做。

二次编辑：在已有产出上继续编辑时，使用该产出文件的 `ws_doc_id` 检索，编辑后再次 `snapshot_and_index`。

---

## ES Copy-on-Write 快照机制

### 核心原则

**每个产出文件独立拥有一份 ES chunks，不覆盖父版本。**

```
KB 原始文档 (doc_id=abc)
│  ES: ragflow_{tenant}/abc           ← 知识库 chunks（只读，不动）
│
├─ copy_kb_document
│
downloads/合同.docx (ws_doc_id=ws_{sid}_abc)
│  ES: ragflow_{tenant}/ws_{sid}_abc  ← fork from KB（只读快照）
│
├─ 编辑 + write_file_bytes (新文件名)
│
outputs/合同_numbered.docx (ws_doc_id=ws_{sid}_{hash1})
│  ES: ragflow_{tenant}/ws_{sid}_{hash1} ← fork from parent + full_reparse
│
├─ 继续编辑 + write_file_bytes (又一个新文件名)
│
outputs/合同_linked.docx (ws_doc_id=ws_{sid}_{hash2})
   ES: ragflow_{tenant}/ws_{sid}_{hash2} ← fork from parent + full_reparse
```

### 为什么不原地覆盖 ES？

| 方案 | 问题 |
|------|------|
| 覆盖原 ws_doc_id 的 chunks | 文件名变了但 `docnm_kwd` 没变 → 按新名称搜不到；旧版本也丢了 |
| 只更新 `docnm_kwd` / `workspace_path` | 版本不对应：ES 内容是旧的，文件是新的 |
| **Copy-on-Write（本方案）** | 每个文件独立 ES，版本永远对应，搜索不会混乱 |

### 存储开销

一个 1000 页 DOCX ≈ 500-2000 个 ES chunks ≈ 2-10 MB 文本。session 内通常 2-5 个版本，总增量 < 50 MB，完全可接受。

### snapshot_and_index 内部流程

```
Step 1: Fork 父 chunks → 新 ws_doc_id
        复制所有 chunks，更新 doc_id / workspace_path / docnm_kwd
        → 新 ws_doc_id 拥有完整基线（和父文件内容一致）

Step 2: trigger_chunk_update(new_ws_doc_id, output_path, old_range)
        在基线上做增量更新，只重解析被改的范围
        ├─ Agent 提供 old_range → 增量更新（快）
        └─ 不提供 old_range → full_reparse fallback（慢但正确）
        → 新 ws_doc_id 的 chunks 和新文件内容一致
```

Fork 是增量更新的**前提**：没有基线，增量更新不知道哪些旧 chunks 要删、哪些要保留、后续偏移多少。

### 调用方式

```python
workspace_ops(
    action="snapshot_and_index",
    params='{
        "parent_ws_doc_id": "ws_{sid}_abc",
        "output_path": "sessions/{sid}/outputs/合同_numbered.docx",
        "source_type": "docx",
        "old_range": {"para_start_int": 0, "para_end_int": 50}
    }'
)
```

**参数说明**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `parent_ws_doc_id` | ✅ | 父文档的 ws_doc_id（从 copy_kb_document 返回值或上次 snapshot 返回值获取） |
| `output_path` | ✅ | 新文件在 workspace 中的路径 |
| `source_type` | ✅ | `"docx"` / `"xlsx"` / `"pptx"` |
| `old_range` | 推荐 | 被修改的段落/行范围。有 → 增量更新；没有 → full_reparse fallback |
| `new_para_count` | 可选 | 修改后该范围变成了多少段落/行 |

**返回**：
```json
{
    "status": "snapshot_created",
    "new_ws_doc_id": "ws_{sid}_{hash}",
    "parent_ws_doc_id": "ws_{sid}_abc",
    "output_path": "sessions/{sid}/outputs/合同_numbered.docx",
    "chunks_forked": 296,
    "update_mode": "incremental",
    "search_cmd": "unified_search(query='关键词', doc_ids='ws_{sid}_{hash}')"
}
```

### 后续检索该产出

拿到 `new_ws_doc_id` 后，后续所有检索都用它：

```python
unified_search(action="search", query="违约责任", doc_ids="ws_{sid}_{hash}")
```

### 在产出物上二次编辑

如果需要在已有产出上继续编辑（如在 `_numbered.docx` 基础上加超链接）：

```python
# 1. 用该产出的 ws_doc_id 检索定位
unified_search(action="search", query="前雾灯", doc_ids="ws_{sid}_{hash1}")

# 2. 编辑 + 另存为新文件
# execute_code → write_file_bytes → outputs/合同_linked.docx

# 3. 以上一个产出为 parent 再次 snapshot
workspace_ops(
    action="snapshot_and_index",
    params='{"parent_ws_doc_id": "ws_{sid}_{hash1}", "output_path": "..._linked.docx", ...}'
)
# → 返回 ws_{sid}_{hash2}，版本链继续延伸
```

---

## ✅ 产出验证 — execute_code 之后必须用 ES 抽样检查

代码执行（如批量添加编号、创建超链接、修改格式）容易出现 off-by-one、匹配遗漏、映射错位等 bug。**每次 execute_code 产出文档后，必须用 ES 搜索抽样验证结果正确性。**

### 验证流程

```
execute_code 产出新文档
    ↓
snapshot_and_index → 新 ws_doc_id（ES chunks 已更新）
    ↓
unified_search(query="第一个期望内容", doc_ids="new_ws_doc_id")
    → 检查返回的 chunk 是否包含预期修改
    ↓
unified_search(query="最后一个期望内容", doc_ids="new_ws_doc_id")
    → 检查边界条目是否正确
    ↓
确认无误 → 输出给用户
```

### 典型验证场景

**批量编号**：搜索第一个和最后一个编号，确认序号连续、没有偏移
```python
unified_search(query="GAC_外灯系统_01", doc_ids="ws_{sid}_{hash}")
# 期望返回 "前雾灯指示灯" 相关 chunk — 如果返回的是 "后雾灯指示灯"，说明编号偏移了
```

**超链接映射**：搜索映射的两端，确认对应关系
```python
unified_search(query="FUNC_0007", doc_ids="ws_{sid}_{hash_gac}")
# 期望出现在 "前雾灯指示灯" chunk — 如果不是，说明映射错位
```

**内容修改**：搜索被修改的关键词，确认新旧值
```python
unified_search(query="60天", doc_ids="ws_{sid}_{hash}")
# 期望在 "违约责任" chunk 中找到 — 如果还是 "30天"，说明修改未生效
```

### 为什么不能只靠代码内部验证？

代码可以 `assert` 检查行数/计数，但无法验证 **语义正确性**（编号对应到正确的需求项、超链接指向正确的位置）。ES 搜索是唯一能从「用户视角」验证内容的方式。

---

## 按格式选择工具

根据 `source_type` 字段选择编辑工具：

| source_type | 编辑工具 | 位置字段 |
|-------------|---------|----------|
| docx | docx skill | `para_start_int` / `para_end_int` + **关键词定位** |
| xlsx | **xlsx skill** (execute_code + openpyxl) | `sheet_name` + `row_start_int` / `row_end_int` |
| pptx | pptx skill / execute_code | `slide_num` |
| pdf | 有限编辑 | `page_num_int` |

---

## 🔑 关键词定位协议（与 docx skill 协作）

### 为什么需要关键词定位？

ES 返回的 `para_start_int/para_end_int` 是基于段落索引的定位，但：
- 跨文档编辑时，段落索引可能不稳定
- docx skill 在 XML 层操作，需要更精确的定位
- 简单关键词可能重复（如 "REQ_001" 可能出现多次）

**解决方案**：Agent 提供丰富的上下文关键词，docx skill 在 XML 层精确匹配。

### LocatorSpec 格式

调用 docx skill 时，除 ES 位置信息外，**必须**提供 `LocatorSpec`：

```json
{
  "primary": "REQ_001",
  "context_before": ["第3.2条", "违约责任"],
  "context_after": ["赔偿金额"],
  "match_mode": "run",
  "occurrence": 0
}
```

**字段说明**：

| 字段 | 必须 | 说明 |
|------|------|------|
| `primary` | ✅ | 主关键词（要定位/修改的文本） |
| `context_before` | 推荐 | 前置上下文词（提升唯一性） |
| `context_after` | 推荐 | 后置上下文词（提升唯一性） |
| `match_mode` | 可选 | `"run"`（默认，精确到 run）/ `"paragraph"`（段落级）/ `"fuzzy"`（模糊） |
| `occurrence` | 可选 | 仍有多个匹配时，选择第几个（0-based） |

### 消歧逻辑

docx skill 的 `keyword_locator.py` 会：
1. 找到所有包含 `primary` 的候选位置
2. 检查 `context_before` 是否在前面 10 段内出现
3. 检查 `context_after` 是否在后面 10 段内出现
4. 按上下文匹配得分排序，返回最佳匹配

**如果仍无法消歧**：返回候选列表，Agent 需提供更多上下文。

### 两种定位方式配合

```
document-editing                    docx skill
       │                                │
       ├── unified_search() ────────────┤ 获取 ES 位置信息
       │   (para_start_int, para_end)   │
       │                                │
       ├── 分析上下文 ──────────────────┤ 确定 LocatorSpec
       │   → LocatorSpec                │
       │                                │
       └── 调用 docx skill ─────────────┤
           + workspace_path             │
           + LocatorSpec                │
           + 修改内容                    │
                                        │
                            ┌───────────┴───────────┐
                            │ keyword_locator.py    │
                            │ 精确定位 XML 位置      │
                            │ 执行修改              │
                            └───────────────────────┘
```

### 示例

**用户**："把合同第 3.2 条的违约责任里的赔偿金额从 30 天改成 60 天"

**Agent 分析**：
- ES 检索：找到"第3.2条 违约责任"在 para 45-52
- 要修改：`30` → `60`
- LocatorSpec：
  ```json
  {
    "primary": "30",
    "context_before": ["第3.2条", "违约责任", "赔偿"],
    "context_after": ["天"],
    "match_mode": "run"
  }
  ```

这样即使文档中有多处 "30"，也能精确定位到正确位置。

## 详细参考
- DOCX 编辑流程 + 示例：`references/docx-editing.md`
- XLSX 编辑流程 + 示例：`references/xlsx-editing.md`
- PPTX 编辑流程 + 示例：`references/pptx-editing.md`
- 表格/图片/公式定位：`references/element-positioning.md`
- 增量更新机制：`references/incremental-update.md`
