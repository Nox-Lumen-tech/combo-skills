# 高亮步骤 API 参考

> Agent 执行差异高亮任务前 `read_file` 此文档。

## docx_utils — 精准高亮

```python
from ragbase_skills.docx import docx_utils
```

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `highlight_text_in_paragraph` | `(para, keyword, color="FF0000", mode="highlight", max_count=0)` | `int` | 在段落中高亮 keyword，自动处理 run splitting（跨 run 也能正确拆分）。返回命中次数 |
| `highlight_keywords_in_range` | `(doc, keywords, para_start, para_end, color="FF0000", mode="highlight")` | `dict` | 批量高亮：遍历 body 段落 **和** 表格内段落。返回 `{"total": int, "details": {kw: count}}` |
| `highlight_keywords_in_tables` | `(doc, keywords, color="FF0000", mode="highlight", table_indices=None)` | `dict` | 表格内高亮。`table_indices` 可指定表格。返回格式同上 |

### 三种 mode

| mode | 效果 | 适用场景 |
|------|------|----------|
| `"highlight"` | Word 内置荧光笔 | **默认推荐**，表格内有底色也清晰可见 |
| `"shading"` | 背景色填充 | 普通段落中最醒目，但表格内可能被单元格底色覆盖 |
| `"font_color"` | 改文字颜色 | 需要保留背景、只改文字颜色时 |

### 示例

```python
from docx import Document
from ragbase_skills.docx import docx_utils

doc = Document(local_path)

# 在指定段落范围内批量高亮（para_start/para_end 从 ES 获得）
result = docx_utils.highlight_keywords_in_range(
    doc,
    keywords=["前雾灯", "BCM_FrontFogLampSt", "150ms"],
    para_start=350, para_end=370,
    color="FF0000", mode="highlight",
)
print(f"命中 {result['total']} 处: {result['details']}")

# 单段精确高亮（关键词可能跨 run）
para = doc.paragraphs[355]
n = docx_utils.highlight_text_in_paragraph(
    para, "指示灯OFF", color="FF0000", mode="shading"
)

doc.save(output_path)
```
