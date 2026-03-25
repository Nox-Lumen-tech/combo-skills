# 编号步骤 API 参考

> Agent 执行编号任务前 `read_file` 此文档。

## docx_utils — 段落遍历与安全文本修改

```python
from ragbase_skills.docx import docx_utils
```

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `get_body_paragraphs` | `(doc, skip_styles=None)` | `List[Tuple[int, Paragraph]]` | 返回正文段落（**自动跳过 TOC / header / footer**），`int` 是段落索引（与 ES `para_start_int` 对齐） |
| `get_toc_paragraphs` | `(doc)` | `List[Tuple[int, Paragraph]]` | 返回目录段落（仅 TOC 样式） |
| `safe_append_text` | `(para, text, copy_format=True)` | `None` | 在段落末尾追加文本，**保留原有格式** |
| `safe_replace_text` | `(para, old, new)` | `bool` | 在段落的某个 run 中替换文本（保留格式），若跨 run 返回 `False` |
| `find_heading_paragraphs` | `(doc, level=None, skip_toc=True)` | `List[Tuple[int, Paragraph]]` | 查找指定级别的标题段落 |
| `insert_paragraphs_after` | `(doc, after_idx, texts)` | `dict` | 在 after_idx 段落之后插入新段落，自动继承锚点样式。返回 `{"inserted": N, "first_idx": N, "last_idx": N, "style": "...", "is_toc": bool}` |

## Word 自动编号（`<w:numPr>`）陷阱

很多文档的章节编号（如 "3.1."）**不是段落文本的一部分**，而是 Word 自动编号系统渲染的：

| 位置 | `para.text` | `re.match(r'^\d+\.\d+', text)` |
|------|-------------|-------------------------------|
| TOC (para 33) | `3.1.\t前雾灯指示灯\t28` | **匹配** ✅ — 编号是字面文本 |
| Body (para 351) | `前雾灯指示灯` | **不匹配** ❌ — 编号由 `<w:numPr>` 渲染 |

**因此**：用 `^\d+\.\d+` 正则遍历 `doc.paragraphs` 会**只命中 TOC、完全跳过正文**。

### 正确做法：用 numPr 的 ilvl 判断层级

```python
from docx import Document
from ragbase_skills.docx import docx_utils

doc = Document("input.docx")
ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

# ilvl=0 → X 级（一级标题）
# ilvl=1 → X.X 级（二级标题）
# ilvl=2 → X.X.X 级（三级标题）
current_chapter = ""
seq = 0
for idx, para in docx_utils.get_body_paragraphs(doc):
    numPr = para._element.find(f'.//{ns}numPr')
    if numPr is None:
        continue
    ilvl_el = numPr.find(f'{ns}ilvl')
    ilvl = int(ilvl_el.get(f'{ns}val')) if ilvl_el is not None else -1
    if ilvl == 0:
        current_chapter = para.text.strip()
        seq = 0
    elif ilvl == 1:
        seq += 1
        docx_utils.safe_append_text(para, f" (GAC_{current_chapter}_{seq:02d})")

doc.save("output.docx")
```

### 用 keyword_locator 逐个定位

先从 TOC 或 unified_search 获取标题列表，再用上下文消歧定位正文。

```python
from ragbase_skills.docx import keyword_locator as kl, docx_utils

titles = ["前雾灯指示灯", "后雾灯指示灯", "位置灯指示灯"]
for title in titles:
    result = kl.locate_keyword(docx_path, title, nearby="功能定义")
    if result["found"]:
        if result.get("in_table"):
            table = doc.tables[result["table_idx"]]
            cell = table.rows[result["row_idx"]].cells[result["cell_idx"]]
            para = cell.paragraphs[result["cell_para_idx"]]
        else:
            para = doc.paragraphs[result["paragraph_idx"]]
        docx_utils.safe_append_text(para, " (编号)")
```

### 有 para_range 时直接用索引过滤

```python
for idx, para in enumerate(doc.paragraphs):
    if para_start <= idx <= para_end:
        if "前雾灯指示灯" in para.text:
            docx_utils.safe_append_text(para, " (编号)")
```

### TOC 和正文插入

新章节需要在 TOC 和正文两处都插入：

```python
# TOC 区域
toc_paras = docx_utils.get_toc_paragraphs(doc)
result = docx_utils.insert_paragraphs_after(doc, after_idx=192, texts=[
    "7.5\t智能钥匙与车辆灯光交互状态提示\t60",
])

# 正文区域
result = docx_utils.insert_paragraphs_after(doc, after_idx=590, texts=[
    "7.5 智能钥匙与车辆灯光交互状态提示",
    "功能描述：...",
])
```

## keyword_locator — 关键词定位

```python
from ragbase_skills.docx import keyword_locator as kl
```

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `locate_keyword` | `(docx_path, keyword, nearby="", match_mode="run", para_range=None, context="")` | `dict` | 定位关键词。`context` 为同段落上下文验证串，用于消歧 |
| `batch_locate` | `(docx_path, specs)` | `List[dict]` | 批量定位。`specs` = `[{"keyword": "...", "context": "...", "nearby": "...", "para_range": [120,150]}, ...]` |

**返回 dict 字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `found` | `bool` | 是否找到 |
| `in_table` | `bool` | 是否在表格中（决定取段落方式） |
| `paragraph_idx` | `int` | body 段落索引（`in_table=False` 时有效） |
| `table_idx` / `row_idx` / `cell_idx` / `cell_para_idx` | `int` | 表格坐标（`in_table=True` 时有效） |
| `run_idx` | `int` | run 索引（-1 = 段落级匹配） |
| `context` | `str` | 段落文本前200字符 |
