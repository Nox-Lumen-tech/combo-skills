#!/usr/bin/env python3
"""
docx_utils.py - DOCX 编辑辅助工具

提供安全的段落遍历和文本修改方法，避免常见错误：
- 误改目录（TOC）段落
- para.text = ... 破坏格式
- 整段高亮（应该只高亮关键词）
"""

from __future__ import annotations

import copy
from typing import List, Tuple, Optional, Set
import re
from lxml import etree

_XML_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

def _sanitize(text: str) -> str:
    """Strip XML-illegal control characters so lxml won't reject the string."""
    if not text:
        return text
    if text.count("\x00") > len(text) * 0.3:
        try:
            text = text.encode("latin-1", errors="replace").decode("utf-16-le", errors="replace")
        except Exception:
            pass
    return _XML_CTRL_RE.sub("", text)

_TOC_STYLE_PREFIXES = ("toc ", "toc1", "toc2", "toc3", "toc4", "toc5",
                        "toc6", "toc7", "toc8", "toc9",
                        "tableofcontents", "table of contents")
_SKIP_STYLE_KEYWORDS = {"header", "footer", "toc"}


def _is_toc_or_structural(style_name: str) -> bool:
    """判断段落样式是否为目录/页眉/页脚等结构性样式"""
    if not style_name:
        return False
    lower = style_name.lower().strip()
    if any(lower.startswith(p) for p in _TOC_STYLE_PREFIXES):
        return True
    for kw in _SKIP_STYLE_KEYWORDS:
        if kw in lower:
            return True
    return False


def get_body_paragraphs(doc, skip_styles: Optional[Set[str]] = None) -> List[Tuple[int, "Paragraph"]]:
    """
    返回文档正文段落（跳过 TOC / 页眉 / 页脚样式的段落）。

    Args:
        doc: python-docx Document 对象
        skip_styles: 额外需要跳过的样式名集合（小写）。默认跳过 TOC/header/footer。

    Returns:
        List[(para_index, Paragraph)] — para_index 与 ES para_start_int 对齐
    """
    result = []
    extra = {s.lower() for s in (skip_styles or set())}

    for idx, para in enumerate(doc.paragraphs):
        style_name = para.style.name if para.style else ""
        if _is_toc_or_structural(style_name):
            continue
        if extra and style_name.lower() in extra:
            continue
        result.append((idx, para))

    return result


def get_toc_paragraphs(doc) -> List[Tuple[int, "Paragraph"]]:
    """返回目录段落列表（仅包含 TOC 样式的段落）。"""
    result = []
    for idx, para in enumerate(doc.paragraphs):
        style_name = para.style.name if para.style else ""
        lower = style_name.lower().strip()
        if any(lower.startswith(p) for p in _TOC_STYLE_PREFIXES):
            result.append((idx, para))
    return result


def safe_append_text(para, text: str, copy_format: bool = True) -> None:
    """
    安全地在段落末尾追加文本，保留原有格式。

    Args:
        para: python-docx Paragraph 对象
        text: 要追加的文本
        copy_format: 是否复制最后一个 run 的格式
    """
    if para.runs:
        last_run = para.runs[-1]
        if copy_format:
            new_run = para.add_run(text)
            _copy_run_format(last_run, new_run)
        else:
            last_run.text += text
    else:
        para.add_run(text)


def safe_replace_text(para, old: str, new: str) -> bool:
    """
    在段落中替换文本，保留 run 格式。

    遍历每个 run，在包含 old 的 run 中执行替换。
    注意：如果文本跨 run 分布，此方法不生效（返回 False）。

    Returns:
        True 如果替换成功
    """
    for run in para.runs:
        if old in run.text:
            run.text = run.text.replace(old, new, 1)
            return True

    # python-docx para.runs 只返回 <w:p> 的直接 <w:r> 子元素，
    # 看不到 <w:ins> 内的 run。用 lxml 兜底。
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    for r_elem in para._element.iter(f"{W}r"):
        for t_elem in r_elem.findall(f"{W}t"):
            if t_elem.text and old in t_elem.text:
                t_elem.text = _sanitize(t_elem.text.replace(old, new, 1))
                return True

    return False


def _copy_run_format(source_run, target_run) -> None:
    """复制 run 格式属性"""
    try:
        target_run.bold = source_run.bold
        target_run.italic = source_run.italic
        target_run.underline = source_run.underline
        if source_run.font:
            if source_run.font.name:
                target_run.font.name = source_run.font.name
            if source_run.font.size:
                target_run.font.size = source_run.font.size
            if source_run.font.color and source_run.font.color.rgb:
                target_run.font.color.rgb = source_run.font.color.rgb
    except Exception:
        pass


def insert_paragraphs_after(
    doc,
    after_idx: int,
    texts: List[str],
    style_name: Optional[str] = None,
) -> dict:
    """
    在指定段落之后插入一组新段落。

    正确使用 lxml addnext() 在 XML body 中原地插入，
    **不调用 doc.add_paragraph()**（那会追加到末尾产生重复）。

    如果 after_idx 指向 TOC 段落，会自动复制 TOC 样式；
    如果指向正文段落，会自动复制正文样式。
    也可以通过 style_name 强制指定样式。

    Args:
        doc: python-docx Document 对象
        after_idx: 插入锚点的段落索引（新段落插在它后面）
        texts: 要插入的文本列表（按顺序）
        style_name: 强制指定段落样式名。None = 复制 after_idx 段落的样式。

    Returns:
        {"inserted": int, "first_idx": int, "last_idx": int,
         "style": str, "is_toc": bool}

    Raises:
        IndexError: after_idx 超出段落范围
    """
    if after_idx < 0 or after_idx >= len(doc.paragraphs):
        raise IndexError(
            f"after_idx={after_idx} 超出范围 [0, {len(doc.paragraphs) - 1}]"
        )
    if not texts:
        return {"inserted": 0, "first_idx": -1, "last_idx": -1,
                "style": "", "is_toc": False}

    anchor_para = doc.paragraphs[after_idx]
    anchor_elem = anchor_para._element

    resolved_style = style_name
    if not resolved_style:
        resolved_style = anchor_para.style.name if anchor_para.style else "Normal"

    is_toc = _is_toc_or_structural(resolved_style)

    # 从锚点段落提取 <w:pPr> 作为模板（保留缩进、字体等格式）
    source_pPr = anchor_elem.find(f"{_W_NS}pPr")
    # 提取第一个 run 的 <w:rPr> 作为文字格式模板
    source_rPr = None
    for r in anchor_elem.findall(f"{_W_NS}r"):
        rPr = r.find(f"{_W_NS}rPr")
        if rPr is not None:
            source_rPr = rPr
            break

    prev_elem = anchor_elem
    inserted_count = 0

    for text in texts:
        p = etree.Element(f"{_W_NS}p")

        # 复制段落属性
        if source_pPr is not None:
            p.append(copy.deepcopy(source_pPr))
        elif resolved_style and resolved_style != "Normal":
            pPr = etree.SubElement(p, f"{_W_NS}pPr")
            pStyle = etree.SubElement(pPr, f"{_W_NS}pStyle")
            pStyle.set(f"{_W_NS}val", resolved_style)

        # 创建 run
        r = etree.SubElement(p, f"{_W_NS}r")
        if source_rPr is not None:
            r.insert(0, copy.deepcopy(source_rPr))
        t = etree.SubElement(r, f"{_W_NS}t")
        text = _sanitize(text)
        t.text = text
        if text and (text[0] == " " or text[-1] == " "):
            t.set(_XML_SPACE, "preserve")

        prev_elem.addnext(p)
        prev_elem = p
        inserted_count += 1

    return {
        "inserted": inserted_count,
        "first_idx": after_idx + 1,
        "last_idx": after_idx + inserted_count,
        "style": resolved_style,
        "is_toc": is_toc,
    }


def find_heading_paragraphs(
    doc,
    level: Optional[int] = None,
    skip_toc: bool = True,
) -> List[Tuple[int, "Paragraph"]]:
    """
    查找标题段落。

    Args:
        doc: python-docx Document 对象
        level: 标题级别（1=Heading 1, 2=Heading 2, ...）。None 返回所有标题。
        skip_toc: 是否跳过 TOC 段落（默认 True）

    Returns:
        List[(para_index, Paragraph)]
    """
    result = []
    heading_pattern = re.compile(r"heading\s*(\d+)", re.IGNORECASE)

    for idx, para in enumerate(doc.paragraphs):
        style_name = para.style.name if para.style else ""

        if skip_toc and _is_toc_or_structural(style_name):
            continue

        match = heading_pattern.match(style_name)
        if match:
            heading_level = int(match.group(1))
            if level is None or heading_level == level:
                result.append((idx, para))

    return result


# ---------------------------------------------------------------------------
# Run-level highlight with automatic run splitting
# ---------------------------------------------------------------------------

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

_HIGHLIGHT_COLOR_MAP = {
    "FF0000": "red",    "FFFF00": "yellow",  "00FF00": "green",
    "0000FF": "blue",   "FF00FF": "magenta", "00FFFF": "cyan",
    "000000": "black",  "FFFFFF": "white",
}


def _collect_text_runs(p_elem: etree._Element) -> List[Tuple[etree._Element, str, int, int]]:
    """
    Collect all <w:r> elements contributing visible text in document order,
    including runs inside <w:hyperlink>.

    Returns:
        [(run_element, text, char_start, char_end), ...]
    """
    result: list = []
    char_pos = 0

    _WALK_INTO_TAGS = {
        f"{_W_NS}hyperlink",
        f"{_W_NS}ins",
    }

    def _walk(container: etree._Element) -> None:
        nonlocal char_pos
        for child in container:
            if child.tag == f"{_W_NS}r":
                text = "".join(
                    (t.text or "") for t in child.findall(f"{_W_NS}t")
                )
                if text:
                    result.append((child, text, char_pos, char_pos + len(text)))
                    char_pos += len(text)
            elif child.tag in _WALK_INTO_TAGS:
                _walk(child)

    _walk(p_elem)
    return result


def _make_run_elem(text: str, rPr_source: Optional[etree._Element]) -> etree._Element:
    """Create a <w:r> element with cloned rPr and a single <w:t>."""
    r = etree.Element(f"{_W_NS}r")
    if rPr_source is not None:
        r.append(copy.deepcopy(rPr_source))
    t = etree.SubElement(r, f"{_W_NS}t")
    text = _sanitize(text)
    t.text = text
    if text and (text[0] == " " or text[-1] == " "):
        t.set(_XML_SPACE, "preserve")
    return r


def _apply_run_highlight(
    run_elem: etree._Element,
    color: str,
    mode: str,
) -> None:
    """Apply visual highlight to a single <w:r> element in-place."""
    rPr = run_elem.find(f"{_W_NS}rPr")
    if rPr is None:
        rPr = etree.SubElement(run_elem, f"{_W_NS}rPr")
        run_elem.insert(0, rPr)

    if mode == "shading":
        shd = rPr.find(f"{_W_NS}shd")
        if shd is None:
            shd = etree.SubElement(rPr, f"{_W_NS}shd")
        shd.set(f"{_W_NS}val", "clear")
        shd.set(f"{_W_NS}color", "auto")
        shd.set(f"{_W_NS}fill", color)

    elif mode == "font_color":
        c = rPr.find(f"{_W_NS}color")
        if c is None:
            c = etree.SubElement(rPr, f"{_W_NS}color")
        c.set(f"{_W_NS}val", color)

    elif mode == "highlight":
        hl = rPr.find(f"{_W_NS}highlight")
        if hl is None:
            hl = etree.SubElement(rPr, f"{_W_NS}highlight")
        hl.set(f"{_W_NS}val", _HIGHLIGHT_COLOR_MAP.get(color.upper(), "red"))


def highlight_text_in_paragraph(
    para,
    keyword: str,
    color: str = "FF0000",
    mode: str = "highlight",
    max_count: int = 0,
) -> int:
    """
    Highlight every occurrence of *keyword* inside a paragraph with
    run-level precision.  Automatically splits runs when the keyword
    is a substring of a larger run or spans multiple runs.

    Args:
        para:      python-docx ``Paragraph`` object.
        keyword:   the exact text to highlight (case-sensitive).
        color:     hex RGB colour without '#' (default ``"FF0000"`` = red).
        mode:      ``"highlight"`` — Word's built-in highlighter pen
                   (visible even inside table cells with background shading).
                   ``"shading"``  — background fill.
                   ``"font_color"`` — change text colour.
        max_count: max occurrences to highlight; 0 means unlimited.

    Returns:
        Number of occurrences actually highlighted.
    """
    p_elem = para._element
    runs_info = _collect_text_runs(p_elem)
    if not runs_info:
        return 0

    full_text = "".join(info[1] for info in runs_info)

    # ── 1. find all keyword positions ──
    positions: List[Tuple[int, int]] = []
    start = 0
    while True:
        idx = full_text.find(keyword, start)
        if idx < 0:
            break
        positions.append((idx, idx + len(keyword)))
        start = idx + len(keyword)
    if not positions:
        return 0
    if max_count > 0:
        positions = positions[:max_count]

    # ── 2. build highlight mask (char_index → True) ──
    hl_mask = set()
    for s, e in positions:
        hl_mask.update(range(s, e))

    # ── 3. split & highlight affected runs (process last-to-first) ──
    for run_elem, run_text, c_start, c_end in reversed(runs_info):
        run_chars = range(c_start, c_end)
        has_hl = any(c in hl_mask for c in run_chars)
        if not has_hl:
            continue

        all_hl = all(c in hl_mask for c in run_chars)
        if all_hl:
            _apply_run_highlight(run_elem, color, mode)
            continue

        # need to split this run into segments
        parent = run_elem.getparent()
        pos_in_parent = list(parent).index(run_elem)
        rPr = run_elem.find(f"{_W_NS}rPr")

        segments: List[Tuple[str, bool]] = []
        buf = ""
        buf_hl = (c_start in hl_mask)
        for i, ch in enumerate(run_text):
            is_hl = (c_start + i) in hl_mask
            if is_hl == buf_hl:
                buf += ch
            else:
                if buf:
                    segments.append((buf, buf_hl))
                buf = ch
                buf_hl = is_hl
        if buf:
            segments.append((buf, buf_hl))

        parent.remove(run_elem)
        for seg_text, seg_hl in reversed(segments):
            new_run = _make_run_elem(seg_text, rPr)
            if seg_hl:
                _apply_run_highlight(new_run, color, mode)
            parent.insert(pos_in_parent, new_run)

    return len(positions)


def _iter_all_paragraphs(doc):
    """Yield ``(flat_index, Paragraph)`` for **every** paragraph in *doc*,
    including those nested inside table cells (recursively for nested
    tables).  ``doc.paragraphs`` only returns body-level paragraphs and
    misses table content entirely.
    """
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    idx = 0
    for child in doc.element.body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == "p":
            yield idx, Paragraph(child, doc)
            idx += 1
        elif tag == "tbl":
            table = Table(child, doc)
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        yield idx, para
                        idx += 1


def highlight_keywords_in_range(
    doc,
    keywords: List[str],
    para_start: int,
    para_end: int,
    color: str = "FF0000",
    mode: str = "highlight",
) -> dict:
    """
    Batch-highlight multiple keywords within a paragraph index range.

    Uses ``_iter_all_paragraphs`` so paragraphs inside table cells are
    included.  Default *mode* is ``"highlight"`` (Word built-in
    highlighter) which is visible even when cells have background
    shading.

    Args:
        doc:        python-docx ``Document``.
        keywords:   list of exact strings to highlight.
        para_start: first paragraph index (inclusive), from ES ``para_start_int``.
        para_end:   last paragraph index (inclusive), from ES ``para_end_int``.
        color:      hex RGB colour.
        mode:       ``"shading"`` / ``"font_color"`` / ``"highlight"``.

    Returns:
        ``{"total": int, "details": {keyword: count, ...}}``
    """
    details: dict = {}
    total = 0
    for idx, para in _iter_all_paragraphs(doc):
        if idx < para_start:
            continue
        if idx > para_end:
            break
        for kw in keywords:
            n = highlight_text_in_paragraph(para, kw, color=color, mode=mode)
            if n:
                details[kw] = details.get(kw, 0) + n
                total += n
    return {"total": total, "details": details}


def highlight_keywords_in_tables(
    doc,
    keywords: List[str],
    color: str = "FF0000",
    mode: str = "highlight",
    table_indices: Optional[List[int]] = None,
) -> dict:
    """
    Highlight keywords inside table cell paragraphs.

    Args:
        doc:            python-docx ``Document``.
        keywords:       list of exact strings to highlight.
        color:          hex RGB colour.
        mode:           ``"highlight"`` / ``"shading"`` / ``"font_color"``.
        table_indices:  optional list of table indices to search (default: all).

    Returns:
        ``{"total": int, "details": {keyword: count, ...}}``
    """
    details: dict = {}
    total = 0
    for t_idx, table in enumerate(doc.tables):
        if table_indices is not None and t_idx not in table_indices:
            continue
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    for kw in keywords:
                        n = highlight_text_in_paragraph(para, kw, color=color, mode=mode)
                        if n:
                            details[kw] = details.get(kw, 0) + n
                            total += n
    return {"total": total, "details": details}
