---
name: docx
description: "Use this skill whenever the user wants to create, read, edit, or manipulate Word documents (.docx files). Triggers include: any mention of \"Word doc\", \"word document\", \".docx\", or requests to produce professional documents with formatting like tables of contents, headings, page numbers, or letterheads. Also use when extracting or reorganizing content from .docx files, inserting or replacing images in documents, performing find-and-replace in Word files, working with tracked changes or comments, or converting content into a polished Word document. If the user asks for a \"report\", \"memo\", \"letter\", \"template\", or similar deliverable as a Word or .docx file, use this skill. Do NOT use for PDFs, spreadsheets, Google Docs, or general coding tasks unrelated to document generation."
license: Proprietary. LICENSE.txt has complete terms
---

# DOCX creation, editing, and analysis

## ⚠️ 场景选择

| 场景 | 使用的 Skill |
|------|-------------|
| **编辑知识库中的文档**（已在 ES 中有 chunks） | `document-editing` → 先 ES 检索定位 → 再用本 skill |
| **本地/新 DOCX 文件操作** | 直接使用本 skill |

**知识库文档编辑流程**（必须先完成这些步骤）：
1. `copy_kb_document(doc_id)` → 复制到 workspace
2. `unified_search(query)` → ES 检索定位，获取 `para_range` 和 `workspace_path`
3. 使用本 skill 编辑 `workspace_path` 中的文件
4. `workspace_ops(action="trigger_chunk_update")` → 触发 ES 增量更新

详见 `document-editing` skill 的 `references/docx-editing.md`。

---

## 工具选择：python-docx 优先，必要时再用 XML

**原则**：能用 python-docx 完成的先用 python-docx，代码简单、易维护；只有 python-docx 做不到的才用 XML。

| 能力 | python-docx | XML (unpack/edit/pack) |
|------|-------------|------------------------|
| 段落增删改 | ✅ 简单 | ✅ 支持 |
| 表格增删改 | ✅ 简单 | ✅ 支持 |
| 插入图片 | ✅ 支持 | ✅ 支持 |
| 样式/格式 | ⚠️ 部分支持 | ✅ 完全支持 |
| 书签 / 超链接 | ❌ 不支持 | ✅ 用 docx_link_engine |
| 修订 / 批注 | ❌ 不支持 | ✅ 需 XML |
| 复杂编号、交叉引用 | ⚠️ 易出问题 | ✅ 更可控 |

**决策流程**：
1. 段落、表格、简单格式、插入图片 → **优先 python-docx**
2. 书签、超链接 → **用 docx_link_engine.py**（封装好的 XML 工具）
3. 修订、批注、复杂结构 → **unpack → edit XML → pack**

---

<!-- COMPACTION_CONSTRAINTS_START -->
1. `from ragbase_skills.docx import keyword_locator, docx_link_engine as dle, docx_validator, docx_utils, comment`，禁止手写 XML
2. 定位必须用 `para_range`（ES）+ `keyword`，禁止全文 `content.find()`
3. `<w:hyperlink>` 只能包裹 `<w:r>`，不能包含 `<w:pPr>`
4. 临时目录用 `tempfile.mkdtemp()`
5. 输出前必须 `docx_validator.validate_docx(path)` 验证
6. **严禁循环中交替 `doc.save()` 和 `dle.insert_*()`** — 两阶段模式
7. `keyword_locator.locate_keyword()` 返回 `in_table` 字段，表格用 `doc.tables[t].rows[r].cells[c].paragraphs[p]`
8. 批量超链接用 `dle.batch_insert_cross_document_hyperlinks_on_run(docx, specs, out)`
9. 跨文档超链接 4 步：①②双方建 bookmark → ③④双方建 hyperlink
10. bookmark 必须打在内容段落（不是 TOC），`bookmark_name` 对应内容（如 `bm_FUNC_0007`）
11. 一对多用 `dle.split_run_with_cross_document_hyperlinks(docx, text, targets, out)`
12. 注释文本用 `comment.build_mapping_comment(match_type, gac_id_list, diff_detail, conclusion)`
13. 严禁手写超链接/书签 XML（`OxmlElement`/`etree.Element`/`SubElement`），必须用 `dle.*` API
14. 推荐管线：`keyword_locator.batch_locate(docx, specs)` → `dle.batch_operations(docx, operations, out)`
15. **关键函数签名**：
    - `docx_utils.safe_append_text(para, text, copy_format=True)` → None
    - `docx_utils.get_body_paragraphs(doc, skip_styles=None)` → List[Tuple[int, Paragraph]]
    - `docx_utils.highlight_keywords_in_range(doc, keywords, para_start, para_end, color, mode)` → dict
    - `keyword_locator.locate_keyword(docx_path, keyword, nearby="", match_mode="run", para_range=None, context="")` → dict{found, in_table, paragraph_idx, table_idx, ...}
    - `keyword_locator.batch_locate(docx_path, specs)` → List[dict]，specs=[{"keyword","context","nearby","para_range"}]
    - `dle.batch_operations(docx, operations, out)` → dict{bookmarks, hyperlinks, splits, failed, failed_details}
    - `dle.insert_cross_document_hyperlink(docx, text, target_doc, bookmark_name, out, occurrence, nearby, para_range)` → Tuple[bool, str]
    - `dle.split_run_with_cross_document_hyperlinks(docx, text, targets, out, nearby, para_range)` → Tuple[int, List[str]]
16. **详细 API 文档在 reference 文件中**：编号→`references/numbering-api.md`，链接→`references/linking-api.md`，高亮→`references/highlighting-api.md`，组合层→`references/pipeline-api.md`。执行代码前先 `read_file` 对应 reference。
17. **组合层**：`from ragbase_skills.docx import docx_pipeline as pipeline`。跨文档/批量链接优先用 `pipeline.locate_and_apply(doc, specs, out)` 或 `pipeline.bidirectional_link(pairs, output_dir)`，省去手动组装。底层原语不受影响。
<!-- COMPACTION_CONSTRAINTS_END -->

<!-- AGENT_CONTEXT_START -->
## ⛔ MANDATORY RULES（必须遵守，违反将导致文档损坏）

### Rule 1: 沙箱中使用内置 Skill 脚本

`execute_code` 中操作 DOCX 时，**必须使用预装的 `ragbase_skills` 包**：

```python
from ragbase_skills.docx import keyword_locator, docx_link_engine as dle, docx_validator, docx_utils, comment
from ragbase_skills.docx import docx_pipeline as pipeline  # 组合层（可选）
```

| 模块 | 用途 | 详细 API → reference 文件 |
|------|------|--------------------------|
| `docx_utils` | 段落遍历（跳过TOC）、安全文本修改、精准高亮、段落插入 | `references/numbering-api.md` |
| `keyword_locator` | 关键词定位（支持 para_range + 表格 fallback） | `references/numbering-api.md` |
| `docx_link_engine` | 书签 / 超链接 / batch_operations | `references/linking-api.md` |
| `comment` | 添加批注（`build_mapping_comment`） | `references/linking-api.md` |
| `docx_validator` | DOCX 后置验证 | （见下方） |
| `docx_pipeline` | **组合层**：跨文档定位、定位+操作、双向链接 | `references/pipeline-api.md` |

**执行代码前**，先 `read_file` 对应的 reference 文件获取完整函数签名、参数和示例。

### Rule 2: 定位必须用 para_range + keyword（禁止全文 find）

ES `unified_search` 返回的 `para_start_int` / `para_end_int` 与 XML `<w:body>/<w:p>` 索引一致。**必须传递 para_range**，不传会命中 TOC。

```python
result = kl.locate_keyword("input.docx", "前雾灯指示灯", nearby="外灯系统", para_range=(120, 150))
```

批量编辑用 `docx_utils.get_body_paragraphs(doc)` 自动跳过 TOC。

### Rule 3: 禁止手写 XML 字符串操作

| ❌ 严禁 | ✅ 正确做法 |
|---------|------------|
| `content.find('<w:p')` + 字符串切片 | `lxml.etree` 解析 |
| `'<w:hyperlink>' + ...` 拼接 | `dle.create_external_hyperlink()` |
| `<w:hyperlink>` 包裹 `<w:pPr>` | `<w:hyperlink>` 只能包裹 `<w:r>` |

### Rule 4: 插入段落用 `docx_utils.insert_paragraphs_after()`（禁止 `doc.add_paragraph()`）

`doc.add_paragraph()` 只能追加到末尾。用 `insert_paragraphs_after(doc, after_idx, texts)` 原地插入并继承锚点样式。

### Rule 5: 临时目录用 `tempfile.mkdtemp(prefix="docx_")`

### Rule 6: 输出前用 `docx_validator.validate_docx(path)` 验证

返回 `{"valid": bool, "errors": [...], "warnings": [...]}`。检查 ZIP 完整性、Content_Types、书签配对、r:id 与 rels 一致性。

### Rule 7: TOC 与正文区分 + 自动编号陷阱

TOC 段落复制正文标题文本。`para.text` 中看到的 `3.1.` 前缀在正文中**不存在**（由 `<w:numPr>` 渲染）。用 `^\d+\.\d+` 正则只命中 TOC，完全跳过正文。**正确做法**：用 numPr 的 `ilvl` 属性判断层级。详见 `references/numbering-api.md`。

### Rule 8: 跨文档超链接 4 步缺一不可

1. docA 建 bookmark（`para_range` 定位到内容段落，不是 TOC）
2. docB 建 bookmark
3. docA 建 hyperlink → `docB#bookmark_B`
4. docB 建 hyperlink → `docA#bookmark_A`

`target_doc` 必须用**最终输出文件名**（不是临时路径）。详见 `references/linking-api.md`。

### Rule 9: 修改文本保留格式

```python
# ❌ para.text = para.text + " (GAC_01)"  → 清除所有格式
# ✅ docx_utils.safe_append_text(para, " (GAC_01)")  → 保留格式
```

---

## 📖 API 概览

> 下方仅列出函数名和一行说明。**完整签名、参数、示例在 reference 文件中**。

### docx_utils（`references/numbering-api.md`）

| 函数 | 说明 |
|------|------|
| `get_body_paragraphs(doc)` | 正文段落（跳过 TOC），索引对齐 ES |
| `get_toc_paragraphs(doc)` | 目录段落 |
| `safe_append_text(para, text)` | 追加文本，保留格式 |
| `safe_replace_text(para, old, new)` | run 内替换，保留格式 |
| `find_heading_paragraphs(doc, level)` | 按级别查找标题 |
| `insert_paragraphs_after(doc, after_idx, texts)` | 原地插入段落 |
| `highlight_text_in_paragraph(para, keyword)` | 精准高亮（跨 run 自动拆分） |
| `highlight_keywords_in_range(doc, keywords, start, end)` | 批量高亮 |

### keyword_locator（`references/numbering-api.md`）

| 函数 | 说明 |
|------|------|
| `locate_keyword(docx, keyword, nearby, para_range, context)` | 单个定位（body + 表格 fallback） |
| `batch_locate(docx, specs)` | 批量定位（单次解压） |

### docx_link_engine（`references/linking-api.md`）

| 函数 | 说明 |
|------|------|
| `insert_bookmark(docx, text, name, out)` | 段落级书签 |
| `insert_bookmark_on_run(docx, text, name, out)` | run 级书签 |
| `batch_insert_bookmarks_on_run(docx, specs, out)` | 批量 run 书签 |
| `insert_cross_document_hyperlink(docx, text, target, bm, out)` | 跨文档超链接 |
| `batch_insert_cross_document_hyperlinks_on_run(docx, specs, out)` | 批量跨文档超链接 |
| `split_run_with_cross_document_hyperlinks(docx, text, targets, out)` | 一对多分段链接 |
| `batch_operations(docx, operations, out)` | **坐标驱动批量操作（推荐）** |
| `comment.build_mapping_comment(match_type, gac_id_list, diff_detail, conclusion)` | 注释文本标准化 |

### highlighting（`references/highlighting-api.md`）

| 函数 | 说明 |
|------|------|
| `highlight_text_in_paragraph(para, keyword, color, mode)` | 三种 mode: highlight/shading/font_color |
| `highlight_keywords_in_range(doc, keywords, start, end)` | 段落 + 表格批量高亮 |
| `highlight_keywords_in_tables(doc, keywords, table_indices)` | 仅表格高亮 |

### docx_pipeline — 组合层（`references/pipeline-api.md`）

> **跨文档 / 批量链接任务优先用 pipeline**，省去手动组装 locator→operation 的胶水代码。底层原语仍可直接调用。

| 函数 | 说明 | 内部调用 |
|------|------|---------|
| `multi_doc_locate(docs_specs)` | 跨 N 文档批量定位 | `batch_locate` × N |
| `locate_and_apply(doc, specs, out)` | 定位+操作一步完成 | `batch_locate` → `batch_operations` |
| `bidirectional_link(pairs, output_dir)` | N 对文档双向链接（4 步自动） | `locate_and_apply` × 2N |
<!-- AGENT_CONTEXT_END -->

---

## Overview

A .docx file is a ZIP archive containing XML files.

## Quick Reference

| Task | Approach |
|------|----------|
| Read/analyze content | `pandoc` or unpack for raw XML |
| Create new document | Use `docx-js` - see Creating New Documents below |
| Edit existing document | **优先** python-docx（段落/表格）；复杂需求用 unpack → edit XML → repack |
| Cross-document hyperlinks | `docx_link_engine.py` 或 unpack → add bookmark + hyperlink XML |

### Converting .doc to .docx

Legacy `.doc` files must be converted before editing:

```bash
python scripts/office/soffice.py --headless --convert-to docx document.doc
```

### Reading Content

```bash
# Text extraction with tracked changes
pandoc --track-changes=all document.docx -o output.md

# Raw XML access
python scripts/office/unpack.py document.docx unpacked/
```

### Converting to Images

```bash
python scripts/office/soffice.py --headless --convert-to pdf document.docx
pdftoppm -jpeg -r 150 document.pdf page
```

### Accepting Tracked Changes

To produce a clean document with all tracked changes accepted (requires LibreOffice):

```bash
python scripts/accept_changes.py input.docx output.docx
```

---

## Creating New Documents

Generate .docx files with JavaScript, then validate. Install: `npm install -g docx`

### Setup
```javascript
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun,
        Header, Footer, AlignmentType, PageOrientation, LevelFormat, ExternalHyperlink,
        TableOfContents, HeadingLevel, BorderStyle, WidthType, ShadingType,
        VerticalAlign, PageNumber, PageBreak } = require('docx');

const doc = new Document({ sections: [{ children: [/* content */] }] });
Packer.toBuffer(doc).then(buffer => fs.writeFileSync("doc.docx", buffer));
```

### Validation
After creating the file, validate it. If validation fails, unpack, fix the XML, and repack.
```bash
python scripts/office/validate.py doc.docx
```

### Page Size

```javascript
// CRITICAL: docx-js defaults to A4, not US Letter
// Always set page size explicitly for consistent results
sections: [{
  properties: {
    page: {
      size: {
        width: 12240,   // 8.5 inches in DXA
        height: 15840   // 11 inches in DXA
      },
      margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } // 1 inch margins
    }
  },
  children: [/* content */]
}]
```

**Common page sizes (DXA units, 1440 DXA = 1 inch):**

| Paper | Width | Height | Content Width (1" margins) |
|-------|-------|--------|---------------------------|
| US Letter | 12,240 | 15,840 | 9,360 |
| A4 (default) | 11,906 | 16,838 | 9,026 |

**Landscape orientation:** docx-js swaps width/height internally, so pass portrait dimensions and let it handle the swap:
```javascript
size: {
  width: 12240,   // Pass SHORT edge as width
  height: 15840,  // Pass LONG edge as height
  orientation: PageOrientation.LANDSCAPE  // docx-js swaps them in the XML
},
// Content width = 15840 - left margin - right margin (uses the long edge)
```

### Styles (Override Built-in Headings)

Use Arial as the default font (universally supported). Keep titles black for readability.

```javascript
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 24 } } }, // 12pt default
    paragraphStyles: [
      // IMPORTANT: Use exact IDs to override built-in styles
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 } }, // outlineLevel required for TOC
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 180, after: 180 }, outlineLevel: 1 } },
    ]
  },
  sections: [{
    children: [
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Title")] }),
    ]
  }]
});
```

### Lists (NEVER use unicode bullets)

```javascript
// ❌ WRONG: new Paragraph({ children: [new TextRun("• Item")] })  // BAD
// ✅ CORRECT: Use LevelFormat.BULLET with numbering config
const doc = new Document({
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
  ]},
  sections: [{ children: [
    new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Bullet item")] }),
    new Paragraph({ numbering: { reference: "numbers", level: 0 }, children: [new TextRun("Numbered item")] }),
  ]}]
});
// Same reference = continues (1,2,3 then 4,5,6); Different reference = restarts (1,2,3 then 1,2,3)
```

### Tables

**CRITICAL: Tables need dual widths** - set both `columnWidths` on the table AND `width` on each cell.

```javascript
const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };

new Table({
  width: { size: 9360, type: WidthType.DXA }, // Always DXA (PERCENTAGE breaks in Google Docs)
  columnWidths: [4680, 4680], // Must sum to table width (1440 DXA = 1 inch)
  rows: [
    new TableRow({
      children: [
        new TableCell({
          borders,
          width: { size: 4680, type: WidthType.DXA },
          shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, // CLEAR not SOLID
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun("Cell")] })]
        })
      ]
    })
  ]
});
// Table width = sum of columnWidths. US Letter 1" margins: 12240 - 2880 = 9360 DXA
```

### Images

```javascript
// CRITICAL: type parameter is REQUIRED
new Paragraph({
  children: [new ImageRun({
    type: "png", // Required: png, jpg, jpeg, gif, bmp, svg
    data: fs.readFileSync("image.png"),
    transformation: { width: 200, height: 150 },
    altText: { title: "Title", description: "Desc", name: "Name" } // All three required
  })]
})
```

### Page Breaks

```javascript
// CRITICAL: PageBreak must be inside a Paragraph
new Paragraph({ children: [new PageBreak()] })

// Or use pageBreakBefore
new Paragraph({ pageBreakBefore: true, children: [new TextRun("New page")] })
```

### Table of Contents

```javascript
// CRITICAL: Headings must use HeadingLevel ONLY - no custom styles
new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-3" })
```

### Headers/Footers

```javascript
sections: [{
  properties: {
    page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } // 1440 = 1 inch
  },
  headers: {
    default: new Header({ children: [new Paragraph({ children: [new TextRun("Header")] })] })
  },
  footers: {
    default: new Footer({ children: [new Paragraph({
      children: [new TextRun("Page "), new TextRun({ children: [PageNumber.CURRENT] })]
    })] })
  },
  children: [/* content */]
}]
```


## Editing Existing Documents

**优先用 python-docx**（段落/表格/图片等），只有需要书签、超链接、修订、批注时再用下面的 XML 流程。

### 优先：python-docx 编辑

```python
from docx import Document
from ragbase_skills.docx import docx_utils

doc = Document("input.docx")

# ✅ 正确：用 get_body_paragraphs 遍历（自动跳过 TOC）
body_paras = docx_utils.get_body_paragraphs(doc)
for idx, para in body_paras:
    if "旧文本" in para.text:
        docx_utils.safe_replace_text(para, "旧文本", "新文本")

# ❌ 严禁：直接遍历 doc.paragraphs（会命中 TOC 段落）
# for para in doc.paragraphs:
#     para.text = para.text.replace("旧文本", "新文本")

# 表格
table = doc.tables[0]
table.cell(0, 0).text = "新内容"

doc.save("output.docx")
```

在 Agent 的 execute_code 中，用 `read_file_bytes` / `write_file_bytes` 读写 MinIO 上的文件。

### XML 流程（书签/超链接/修订/批注时使用）

**Follow all 3 steps in order.**

### Step 1: Unpack
```bash
python scripts/office/unpack.py document.docx unpacked/
```
Extracts XML, pretty-prints, merges adjacent runs, and converts smart quotes to XML entities (`&#x201C;` etc.) so they survive editing. Use `--merge-runs false` to skip run merging.

### Step 2: Edit XML

Edit files in `unpacked/word/`. See XML Reference below for patterns.

**Use "Claude" as the author** for tracked changes and comments, unless the user explicitly requests use of a different name.

**Use the Edit tool directly for string replacement. Do not write Python scripts.** Scripts introduce unnecessary complexity. The Edit tool shows exactly what is being replaced.

**CRITICAL: Use smart quotes for new content.** When adding text with apostrophes or quotes, use XML entities to produce smart quotes:
```xml
<!-- Use these entities for professional typography -->
<w:t>Here&#x2019;s a quote: &#x201C;Hello&#x201D;</w:t>
```
| Entity | Character |
|--------|-----------|
| `&#x2018;` | ‘ (left single) |
| `&#x2019;` | ’ (right single / apostrophe) |
| `&#x201C;` | “ (left double) |
| `&#x201D;` | ” (right double) |

**Adding comments:** Use `comment.py` to handle boilerplate across multiple XML files (text must be pre-escaped XML):
```bash
python scripts/comment.py unpacked/ 0 "Comment text with &amp; and &#x2019;"
python scripts/comment.py unpacked/ 1 "Reply text" --parent 0  # reply to comment 0
python scripts/comment.py unpacked/ 0 "Text" --author "Custom Author"  # custom author name
```
Then add markers to document.xml (see Comments in XML Reference).

### Step 3: Pack
```bash
python scripts/office/pack.py unpacked/ output.docx --original document.docx
```
Validates with auto-repair, condenses XML, and creates DOCX. Use `--validate false` to skip.

**Auto-repair will fix:**
- `durableId` >= 0x7FFFFFFF (regenerates valid ID)
- Missing `xml:space="preserve"` on `<w:t>` with whitespace

**Auto-repair won't fix:**
- Malformed XML, invalid element nesting, missing relationships, schema violations

### Common Pitfalls

- **Replace entire `<w:r>` elements**: When adding tracked changes, replace the whole `<w:r>...</w:r>` block with `<w:del>...<w:ins>...` as siblings. Don't inject tracked change tags inside a run.
- **Preserve `<w:rPr>` formatting**: Copy the original run's `<w:rPr>` block into your tracked change runs to maintain bold, font size, etc.

### XML 常见错误（文档损坏、Word 打不开）

| 现象 | 原因 | 解决 |
|------|------|------|
| Word 报错、文档打不开 | 命名空间错误或缺失 | 使用完整 `w:` 前缀，如 `<w:t>` 而非 `<t>` |
| 文档损坏 | 标签未闭合 | 确保每个开始标签有对应结束标签 |
| 空格/换行丢失 | `<w:t>` 含首尾空格未声明 | 加 `xml:space="preserve"` |
| 样式错乱 | `<w:pPr>` 内元素顺序错误 | 按序：`pStyle` → `numPr` → `spacing` → `ind` → `jc` → `rPr` 最后 |

**CRITICAL**：新增或修改的 `<w:t>` 若含首尾空格，必须加 `xml:space="preserve"`：
```xml
<!-- 错误：空格可能被 Word 吞掉 -->
<w:t> 有空格 </w:t>

<!-- 正确 -->
<w:t xml:space="preserve"> 有空格 </w:t>
```

---

## XML Reference

### Schema Compliance

- **Element order in `<w:pPr>`**: `<w:pStyle>`, `<w:numPr>`, `<w:spacing>`, `<w:ind>`, `<w:jc>`, `<w:rPr>` last
- **Whitespace**: Add `xml:space="preserve"` to `<w:t>` with leading/trailing spaces
- **RSIDs**: Must be 8-digit hex (e.g., `00AB1234`)

### Tracked Changes

**Insertion:**
```xml
<w:ins w:id="1" w:author="Claude" w:date="2025-01-01T00:00:00Z">
  <w:r><w:t>inserted text</w:t></w:r>
</w:ins>
```

**Deletion:**
```xml
<w:del w:id="2" w:author="Claude" w:date="2025-01-01T00:00:00Z">
  <w:r><w:delText>deleted text</w:delText></w:r>
</w:del>
```

**Inside `<w:del>`**: Use `<w:delText>` instead of `<w:t>`, and `<w:delInstrText>` instead of `<w:instrText>`.

**Minimal edits** - only mark what changes:
```xml
<!-- Change "30 days" to "60 days" -->
<w:r><w:t>The term is </w:t></w:r>
<w:del w:id="1" w:author="Claude" w:date="...">
  <w:r><w:delText>30</w:delText></w:r>
</w:del>
<w:ins w:id="2" w:author="Claude" w:date="...">
  <w:r><w:t>60</w:t></w:r>
</w:ins>
<w:r><w:t> days.</w:t></w:r>
```

**Deleting entire paragraphs/list items** - when removing ALL content from a paragraph, also mark the paragraph mark as deleted so it merges with the next paragraph. Add `<w:del/>` inside `<w:pPr><w:rPr>`:
```xml
<w:p>
  <w:pPr>
    <w:numPr>...</w:numPr>  <!-- list numbering if present -->
    <w:rPr>
      <w:del w:id="1" w:author="Claude" w:date="2025-01-01T00:00:00Z"/>
    </w:rPr>
  </w:pPr>
  <w:del w:id="2" w:author="Claude" w:date="2025-01-01T00:00:00Z">
    <w:r><w:delText>Entire paragraph content being deleted...</w:delText></w:r>
  </w:del>
</w:p>
```
Without the `<w:del/>` in `<w:pPr><w:rPr>`, accepting changes leaves an empty paragraph/list item.

**Rejecting another author's insertion** - nest deletion inside their insertion:
```xml
<w:ins w:author="Jane" w:id="5">
  <w:del w:author="Claude" w:id="10">
    <w:r><w:delText>their inserted text</w:delText></w:r>
  </w:del>
</w:ins>
```

**Restoring another author's deletion** - add insertion after (don't modify their deletion):
```xml
<w:del w:author="Jane" w:id="5">
  <w:r><w:delText>deleted text</w:delText></w:r>
</w:del>
<w:ins w:author="Claude" w:id="10">
  <w:r><w:t>deleted text</w:t></w:r>
</w:ins>
```

### Comments

After running `comment.py` (see Step 2), add markers to document.xml. For replies, use `--parent` flag and nest markers inside the parent's.

**CRITICAL: `<w:commentRangeStart>` and `<w:commentRangeEnd>` are siblings of `<w:r>`, never inside `<w:r>`.**

```xml
<!-- Comment markers are direct children of w:p, never inside w:r -->
<w:commentRangeStart w:id="0"/>
<w:del w:id="1" w:author="Claude" w:date="2025-01-01T00:00:00Z">
  <w:r><w:delText>deleted</w:delText></w:r>
</w:del>
<w:r><w:t> more text</w:t></w:r>
<w:commentRangeEnd w:id="0"/>
<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="0"/></w:r>

<!-- Comment 0 with reply 1 nested inside -->
<w:commentRangeStart w:id="0"/>
  <w:commentRangeStart w:id="1"/>
  <w:r><w:t>text</w:t></w:r>
  <w:commentRangeEnd w:id="1"/>
<w:commentRangeEnd w:id="0"/>
<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="0"/></w:r>
<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="1"/></w:r>
```

### Images

1. Add image file to `word/media/`
2. Add relationship to `word/_rels/document.xml.rels`:
```xml
<Relationship Id="rId5" Type=".../image" Target="media/image1.png"/>
```
3. Add content type to `[Content_Types].xml`:
```xml
<Default Extension="png" ContentType="image/png"/>
```
4. Reference in document.xml:
```xml
<w:drawing>
  <wp:inline>
    <wp:extent cx="914400" cy="914400"/>  <!-- EMUs: 914400 = 1 inch -->
    <a:graphic>
      <a:graphicData uri=".../picture">
        <pic:pic>
          <pic:blipFill><a:blip r:embed="rId5"/></pic:blipFill>
        </pic:pic>
      </a:graphicData>
    </a:graphic>
  </wp:inline>
</w:drawing>
```

### 关键词定位（与 document-editing 协作）

当被 `document-editing` skill 调用时，使用 `keyword_locator.py` 进行精确关键词定位。

#### LocatorSpec 格式

调用方（document-editing）会提供：

```json
{
  "primary": "REQ_001",
  "context_before": ["第3.2条", "违约责任"],
  "context_after": ["赔偿金额"],
  "match_mode": "run",
  "occurrence": 0
}
```

| 字段 | 说明 |
|------|------|
| `primary` | 主关键词（要定位/修改的文本） |
| `context_before` | 前置上下文词（提升唯一性） |
| `context_after` | 后置上下文词（提升唯一性） |
| `match_mode` | `"run"`（精确到 run）/ `"paragraph"`（段落级）/ `"fuzzy"`（模糊） |
| `occurrence` | 仍有多个匹配时，选择第几个（0-based） |

#### 使用方法

```bash
# CLI 调用
python scripts/keyword_locator.py locate --docx input.docx --locator '{
    "primary": "30",
    "context_before": ["第3.2条", "违约责任"],
    "context_after": ["天"]
}'

# 返回
# {"found": true, "paragraph_idx": 47, "run_idx": 3, "text": "30", "context": "..."}
```

```python
# Python 模块调用
from scripts.keyword_locator import locate_in_docx, LocatorSpec

spec = LocatorSpec(
    primary="REQ_001",
    context_before=["第3.2条", "违约责任"],
    context_after=["赔偿金额"],
    match_mode="run"
)
result = locate_in_docx("input.docx", spec)

if result.found:
    print(f"找到位置: para={result.paragraph_idx}, run={result.run_idx}")
else:
    print(f"未找到: {result.error}")
    if result.candidates:
        print(f"候选位置: {result.candidates}")
```

#### 消歧逻辑

1. 找到所有包含 `primary` 的候选位置
2. 检查 `context_before` 在前面 10 段内是否出现
3. 检查 `context_after` 在后面 10 段内是否出现
4. 按上下文匹配得分排序，返回最佳匹配

**无法消歧时**：返回候选列表，调用方需提供更多上下文。

#### 典型流程

```
document-editing                    本 skill (docx)
       │                                │
       ├── unified_search() ────────────┤ 获取 ES 位置（粗略）
       │                                │
       ├── 分析上下文 ──────────────────┤ 确定 LocatorSpec
       │                                │
       └── 调用 keyword_locator ────────┤
                                        │
                            ┌───────────┴───────────┐
                            │ 精确定位 XML 位置      │
                            │ 执行修改              │
                            └───────────────────────┘
```

---

### Cross-Document Hyperlinks and Bookmarks

**CRITICAL: For complete documentation including XML patterns, failure diagnosis, and validation checklists, see [references/hyperlinks.md](references/hyperlinks.md).**

This section provides essential rules for generating safe hyperlinks between Word `.docx` documents.

#### Automated Tool: docx_link_engine.py

For most hyperlink tasks, use the automated engine instead of manual XML editing:

```bash
# Insert bookmark at paragraph containing text
python scripts/docx_link_engine.py bookmark --docx spec.docx --text "REQ_1234" --name REQ_1234 --out spec_bookmarked.docx

# Insert internal hyperlink to bookmark
python scripts/docx_link_engine.py hyperlink --docx spec.docx --text "see REQ_1234" --name REQ_1234 --out spec_linked.docx

# Insert cross-document hyperlink
python scripts/docx_link_engine.py xlink --docx docA.docx --text "see page 15" --target docB.docx --name page_15 --out docA_linked.docx
```

Or import as Python module:

```python
from scripts.docx_link_engine import (
    insert_bookmark,
    insert_internal_hyperlink,
    insert_cross_document_hyperlink,
    batch_insert_bookmarks,
)

# Single operations
insert_bookmark("input.docx", "目标文本", "bookmark_name", "output.docx")
insert_internal_hyperlink("input.docx", "链接文本", "target_bookmark", "output.docx")

# Batch insert multiple bookmarks
specs = [("文本1", "bm1"), ("文本2", "bm2")]
batch_insert_bookmarks("input.docx", specs, "output.docx")
```

The engine handles: namespace management, ID collision prevention, XML structure validation.

#### docx_link_engine 常见错误

| 现象 | 原因 | 解决 |
|------|------|------|
| 书签/链接没加上 | **搜索文本跨多个 run** | 段落级函数（`insert_bookmark`）会拼接整段文本，可匹配；run 级函数（`insert_bookmark_on_run`）要求文本在**单个 run** 内。若跨 run，先用 `unpack.py`（默认 `--merge-runs`）合并相邻 run |
| 链接到错误位置 | **occurrence 选错** | 多个匹配时用 `occurrence` 指定第几个（0=第一个）。先 `grep` 或脚本统计匹配次数，再传正确的 occurrence |
| Hyperlink 蓝字但点不了 | Missing relationship entry 或 `Hyperlink` style | 跨文档必须用 `r:id` + relationship；内部用 `w:anchor` |
| 跨文档链接无效 | 用了 `w:anchor` 而非 `r:id` | 跨文档必须用 `r:id`，bookmark 写在 relationship 的 `Target="doc.docx#bm_name"` 中 |
| Word 导航失败 | Missing `bookmarkEnd` | 确保 `bookmarkStart` 与 `bookmarkEnd` 成对 |
| "Word experienced an error" | Broken XML structure | 检查命名空间、标签闭合、`xml:space="preserve"` |

**选择段落级 vs run 级**：
- 段落级（`insert_bookmark`, `insert_internal_hyperlink`）：按整段文本匹配，**支持跨 run**，适合需求编号在段落任意位置
- run 级（`insert_bookmark_on_run`, `batch_insert_bookmarks_on_run`）：按单个 run 匹配，**不支持跨 run**，适合编号在独立 run 中（如 "3.1." 单独一个 run）

#### Quick Reference

**Bookmark XML (paired nodes required):**
```xml
<w:bookmarkStart w:id="15" w:name="page_15"/>
<w:r><w:t>Target Text</w:t></w:r>
<w:bookmarkEnd w:id="15"/>
```

**Hyperlink XML (Hyperlink style required):**
```xml
<w:hyperlink r:id="rId25">
  <w:r>
    <w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>
    <w:t>Jump to page 15</w:t>
  </w:r>
</w:hyperlink>
```

**Relationship entry in `word/_rels/document.xml.rels`:**
```xml
<Relationship Id="rId25" Type=".../hyperlink" Target="docB.docx#page_15" TargetMode="External"/>
```

#### Key Rules

1. **Internal vs Cross-document:**
   - Internal: `<w:hyperlink w:anchor="bookmark_name">`
   - Cross-document: `<w:hyperlink r:id="rIdN">` (bookmark in Relationship Target)

2. **ID collision prevention:**
   - Scan existing rIds/bookmark IDs
   - Use `max_id + 1` for new entries

3. **Large-scale hyperlinks:** Rebuild relationship index every 500 hyperlinks

4. **Golden Rule:** A working hyperlink requires THREE components:
   - Bookmark definition (target document)
   - Hyperlink node (source document)
   - Relationship entry (source document's `document.xml.rels`)

---

## Dependencies

- **python-docx**: `pip install python-docx` — 优先用于段落/表格编辑
- **pandoc**: Text extraction
- **docx**: `npm install -g docx` (new documents)
- **LibreOffice**: PDF conversion (auto-configured for sandboxed environments via `scripts/office/soffice.py`)
- **Poppler**: `pdftoppm` for images
