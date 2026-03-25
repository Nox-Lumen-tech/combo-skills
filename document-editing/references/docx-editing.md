# DOCX 编辑详细流程

## Step 1: 复制文档到 workspace

1. 调用 `copy_kb_document(doc_id)`
2. 返回 `ws_doc_id` 和 `workspace_path`
3. 已在 workspace → 跳过

## Step 2: 检索定位

`unified_search` 返回的 `structured_info` 包含：
- `source_type`: "docx"
- `para_start_int` / `para_end_int`: 段落范围
- `workspace_path`: workspace 中的文件路径

## Step 4: 编辑

### 使用 docx skill 编辑

**定位**：根据 `para_start_int` 和 `para_end_int` 定位段落范围。

**能力**：
- 文本段落编辑（替换/插入/删除）
- 保留原有样式、编号、交叉引用
- 支持表格、图片、公式等复杂元素

**Skill 失败回退**：使用 execute_code + python-docx 脚本

```python
from ragbase_tools import init_context, read_file_bytes, write_file_bytes
from docx import Document
from io import BytesIO

def main(**args):
    init_context(session_id=args["session_id"], user_id=args["user_id"])
    
    # 读取 workspace 中的文档（二进制）
    doc_bytes = read_file_bytes(workspace_path)
    doc = Document(BytesIO(doc_bytes))
    
    # 根据 para_range 定位段落
    for i in range(para_start_int, para_end_int + 1):
        p = doc.paragraphs[i]
        # 执行修改...
    
    # 保存（二进制写入 MinIO）
    buf = BytesIO()
    doc.save(buf)
    write_file_bytes(output_path, buf.getvalue())
    print(f"已保存: {output_path}")
```

**重要**：二进制文件必须用 `write_file_bytes()`，不要用 `write_file()`（仅支持文本）。

### Step 4.5: 触发 ES 增量更新

编辑完成后，**Agent 必须调用 `workspace_ops`** 触发 ES 更新：

```python
workspace_ops(
    action="trigger_chunk_update",
    params='{"ws_doc_id": "<ws_doc_id>", "workspace_path": "<workspace_path>", "source_type": "docx", "old_range": {"para_start_int": <start>, "para_end_int": <end>}, "new_para_count": <count>}'
)
```

**参数说明**：
- `old_range`: 编辑前的段落范围（来自 Step 2 搜索结果的 `para_start_int` / `para_end_int`）
- `new_para_count`: 编辑后该范围变成了多少段（增/删段落时需要）
- `image_descriptions`: 如果编辑中插入/修改了图片，提供 `{para_idx: "描述"}` 避免 VLM 调用

**降级模式**：不传 `old_range` → 全量重解析（慢但始终正确）

**异步执行**：调用立即返回 `{"status": "update_triggered"}`，后台异步更新 ES。

**关键设计**：
- `para_idx` 基于 `doc.paragraphs` 的索引，不包含表格内部段落
- 表格需通过搜索附近文本定位 → execute_code 操作 `doc.tables`
- 图片/公式通过所在段落的 `para_idx` 定位

## 示例

### 示例 1：修改合同条款

用户："帮我修改合同第三章的违约责任条款"

```python
# Step 1: 复制文档到 workspace
result = unified_search(action="copy_kb_document", doc_ids="abc123")
workspace_path = result["storage_ref"]["path"]
ws_doc_id = result["storage_ref"]["ws_doc_id"]

# Step 2: 检索定位
search_result = unified_search(
    action="search", 
    query="违约责任",
    doc_ids=ws_doc_id
)
para_range = [
    search_result["results"][0]["structured_info"]["para_start_int"],
    search_result["results"][0]["structured_info"]["para_end_int"]
]

# Step 3: 向用户确认
print(f"将修改段落 {para_range[0]}-{para_range[1]}，内容如下：")
print(search_result["results"][0]["content"])

# Step 4: 使用 docx skill 编辑
# Agent 调用 docx skill / execute_code ...

# Step 4.5: 触发 ES 增量更新
workspace_ops(
    action="trigger_chunk_update",
    params=json.dumps({
        "ws_doc_id": ws_doc_id,
        "workspace_path": workspace_path,
        "source_type": "docx",
        "old_range": {"para_start_int": para_range[0], "para_end_int": para_range[1]},
        "new_para_count": 30  # 编辑后的段落数
    })
)

# Step 5: 文件已自动注册为产出物（无需手动调用 register_artifact）
```

### 示例 2：二次编辑

用户："再把第五章也改一下"

```python
# 已在 workspace，跳过 copy

# Step 2: 检索定位（搜索 workspace 版本）
search_result = unified_search(
    action="search", 
    query="保密条款",
    doc_ids=ws_doc_id  # 使用 workspace doc_id
)
# 此时搜索到的是已更新的 workspace chunks

# Step 3-5: 同上
```

### 示例 3：表格编辑

用户："修改第三章的定价表"

```python
# Step 1-2: 同上，搜索定位到表格附近文本

# Step 4: 使用 execute_code 编辑表格
execute_code(f"""
from ragbase_tools import init_context, read_file_bytes, write_file_bytes
from docx import Document
from io import BytesIO

def main(**args):
    init_context(session_id=args["session_id"], user_id=args["user_id"])
    doc_bytes = read_file_bytes("{workspace_path}")
    doc = Document(BytesIO(doc_bytes))
    
    table = doc.tables[2]
    table.cell(1, 1).text = "新价格"
    
    buf = BytesIO()
    doc.save(buf)
    write_file_bytes("{workspace_path}", buf.getvalue())
    print("表格修改完成")
""")

# Step 4.5: 触发 ES 增量更新
workspace_ops(
    action="trigger_chunk_update",
    params=json.dumps({
        "ws_doc_id": ws_doc_id,
        "workspace_path": workspace_path,
        "source_type": "docx",
    })
)

# Step 5: 文件已自动注册为产出物（无需手动调用 register_artifact）
```

## 注意事项

1. **原始 KB 不变**：编辑只影响 workspace chunks，原始 KB chunks 永不修改
2. **样式保留**：docx skill 在 XML 层操作，天然保留样式
3. **定位精度**：`para_range` 只覆盖 `doc.paragraphs`，表格需额外定位
4. **立即可搜**：编辑后 ES `refresh=true`，下轮搜索立即可见新内容
