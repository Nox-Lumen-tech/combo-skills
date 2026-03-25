# 表格/图片/公式定位说明

## 各格式位置字段总结

| 格式 | 位置字段 | 定位单位 | 是否需要范围 |
|------|---------|----------|------------|
| **DOCX** | `para_start_int` / `para_end_int` | 段落（`doc.paragraphs` 的索引） | 是 |
| **XLSX** | `sheet_name` + `row_start_int` / `row_end_int` | 行 + 工作表 | 是 |
| **PPTX** | `slide_num` | Slide（幻灯片） | **否**（单一整数） |
| **PDF** | `page_num_int` | Page（页） | **否**（单一整数） |

## DOCX：段落索引

### para_idx 的定义
`para_idx` = `enumerate(doc.paragraphs)` 的索引值。

在 python-docx 中，`doc.paragraphs` 只返回 `<w:body>` 下的 `<w:p>` 元素，**不包含表格内部的段落**。

```
文档 XML 结构：
  <w:body>
    <w:p/>          ← doc.paragraphs[0], para_idx=0
    <w:p/>          ← doc.paragraphs[1], para_idx=1
    <w:tbl/>        ← doc.tables[0]，不在 doc.paragraphs 中
    <w:p/>          ← doc.paragraphs[2], para_idx=2
    <w:p/>          ← doc.paragraphs[3], para_idx=3
  </w:body>
```

### 各元素类型的计数规则

| 元素类型 | 是否在 `doc.paragraphs` 中 | para_idx | 编辑方式 |
| -------- | ----------------------- | ------- | -------- |
| 普通文本段落 | ✅ 是 | 按 `enumerate(doc.paragraphs)` 顺序 | para_range + docx skill |
| 标题段落 | ✅ 是（style 为 Heading） | 同上 | para_range + docx skill |
| 表格 | ❌ 否（在 `doc.tables` 中） | 无 para_idx | execute_code (python-docx) |
| 图片（内联） | ✅ 所在段落有 para_idx | 所在段落的 para_idx | execute_code |
| 公式 | ✅ 所在段落有 para_idx | 所在段落的 para_idx | execute_code |
| 文本框/浮动元素 | ❌ 不在 `doc.paragraphs` 中 | 无 | execute_code |

### 编辑能力边界

| 编辑类型 | 支持方式 | 适用范围 |
| -------- | -------- | -------- |
| 文本段落编辑（替换/插入/删除） | para_range 定位 + docx skill | ✅ 核心场景 |
| 表格编辑 | execute_code + python-docx | 通过表格前后的段落文本搜索定位 |
| 图片替换 | execute_code + python-docx | 通过图片所在段落的 para_idx 定位 |
| 公式编辑 | execute_code + python-docx | 通过 FormulaPosition 定位 |
| 复杂格式（文本框/浮动元素） | execute_code | 需要自定义 XML 操作 |

## XLSX：工作表 + 行号

### 二级定位结构
XLSX 需要**工作表名 + 行号**二级定位：

```python
# XLSX chunk 的位置信息
{
    "source_type": "xlsx",
    "sheet_name": "Sheet1",        # 第一级：工作表名
    "row_start_int": 10,           # 第二级：起始行号
    "row_end_int": 50              # 第二级：结束行号
}
```

### 行号基准
- **1-based**：Excel 原生行号，openpyxl 也是 1-based
- **表头行包含**：`row_start_int` = 表头行（第 1 行），便于增量更新时重建完整表格结构

### 按 Sheet 隔离
- 每个 sheet 的 chunks 独立管理
- 修改 Sheet1 的行不会影响 Sheet2 的行号
- 增量更新时只偏移同一 sheet 内的后续 chunks

### 固定分块
XLSX 按 `chunk_rows=256` 固定切分：
- Chunk 1: rows 1-256
- Chunk 2: rows 257-512
- Chunk 3: rows 513-768
- ...

## PPTX：幻灯片编号

### slide_num 的定义
`slide_num` = 幻灯片在演示文稿中的顺序（从 1 开始）。

### 天然 1:1 映射
PPTX 是三种二进制格式中最简单的：
- **1 slide = 1 chunk**（天然映射）
- 一个 slide 的内容变化不会改变 chunk 边界
- 无需处理"跨 chunk 编辑"问题

### 无需范围字段
PPTX 只需要单一 `slide_num`：
```python
{"source_type": "pptx", "slide_num": 5}
```

对比其他格式：
```python
# DOCX（需要范围）
{"source_type": "docx", "para_start_int": 120, "para_end_int": 150}

# XLSX（二级定位 + 范围）
{"source_type": "xlsx", "sheet_name": "Sheet1", "row_start_int": 10, "row_end_int": 50}

# PPTX（单一整数）
{"source_type": "pptx", "slide_num": 5}
```

### 增删幻灯片
- **修改内容**：只更新该 slide 的 chunk 内容，不偏移
- **插入 slide**：新增 chunk + 偏移后续 chunks 的 slide_num
- **删除 slide**：删除 chunk + 偏移后续 chunks 的 slide_num

## PDF：页码（有限编辑）

### page_num_int
PDF 已有丰富的位置信息：
- `page_num_int`：页码列表
- `position_int`：坐标信息（x0, x1, top, bottom）

### 编辑能力有限
PDF 主要是标注/注释，不是本方案重点：
- 只需将 `page_num_int` 暴露到 `SearchItem`
- PDF 定位已有基础

## 定位策略总结

| 场景 | 定位方式 | 说明 |
|------|---------|------|
| 修改段落文本（DOCX） | `para_range` 直接定位 | 核心场景 |
| 修改表格内容（DOCX） | 搜索附近段落文本定位 → execute_code + `doc.tables` | 表格无 `para_idx` |
| 修改图片（DOCX） | 通过图片所在段落的 `para_idx` | 内联图片段落有 `para_idx` |
| 修改公式（DOCX） | 通过公式所在段落的 `para_idx` | 同上 |
| 修改文本框/浮动元素（DOCX） | execute_code 操作 XML | 不在 `doc.paragraphs` 中 |
| 修改单元格（XLSX） | `sheet_name` + `row_range` 定位 | 二级定位 |
| 修改幻灯片（PPTX） | `slide_num` 直接定位 | 最简单，1:1 映射 |
| 修改 PDF 内容 | `page_num_int` 定位 | 有限编辑 |

## 当用户要求修改非段落元素时

1. `unified_search` 搜索附近文本获取大致位置
2. `execute_code` + 对应库（python-docx / openpyxl / python-pptx）精确操作
3. 系统自动更新 ES chunks

**示例**（修改 DOCX 表格）：
```python
# 用户："修改表格中的产品价格"
# Step 1: 搜索表格附近文本
search_result = unified_search(
    action="search",
    query="产品名称",
    doc_ids=ws_doc_id
)
para_range = [
    search_result["results"][0]["structured_info"]["para_start_int"],
    search_result["results"][0]["structured_info"]["para_end_int"]
]

# Step 2: 通过 execute_code 操作表格
execute_code(f"""
from docx import Document

doc = Document("{workspace_path}")

# 表格不在 doc.paragraphs 中，通过位置估算
# 假设表格在 para {para_range[0]} 附近
table_idx = {para_range[0]}  # 根据实际情况调整

if table_idx < len(doc.tables):
    table = doc.tables[table_idx]
    # 修改表格内容
    for row in table.rows:
        for cell in row.cells:
            if "旧价格" in cell.text:
                # 修改逻辑...
                pass

doc.save("{workspace_path}")
""")
```
