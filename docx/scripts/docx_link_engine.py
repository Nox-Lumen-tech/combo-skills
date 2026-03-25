#!/usr/bin/env python3
"""
docx_link_engine.py - Word DOCX Bookmark + Hyperlink Engine

Minimal, safe engine for adding bookmarks and internal hyperlinks to Word documents.
Designed for AI Agent / Skill usage.

Capabilities:
- Add bookmark to paragraph (by text match)
- Add internal hyperlink to bookmark (by text match)
- Safe XML rewrite with proper namespace handling
- Cross-document hyperlink support (via relationship entries)

Author: Agent Tooling
"""

from __future__ import annotations

import copy
import os
import zipfile
import shutil
import uuid
import re
from lxml import etree
from pathlib import Path
from typing import Optional, Tuple, List

# Word OOXML Namespaces
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

W_NS = "{%s}" % NS["w"]
R_NS = "{%s}" % NS["r"]


# -----------------------------
# DOCX Helpers
# -----------------------------

def unzip_docx(docx_path: str, tmp_dir: str) -> None:
    """Extract DOCX to temporary directory."""
    with zipfile.ZipFile(docx_path, 'r') as zip_ref:
        zip_ref.extractall(tmp_dir)


def zip_docx(tmp_dir: str, output_docx: str) -> None:
    """Repack directory to DOCX."""
    with zipfile.ZipFile(output_docx, 'w', zipfile.ZIP_DEFLATED) as zip_ref:
        for path in Path(tmp_dir).rglob("*"):
            if path.is_file():
                zip_ref.write(path, path.relative_to(tmp_dir))


def load_document_xml(tmp_dir: str) -> Tuple[etree._ElementTree, Path]:
    """Load document.xml as parsed tree."""
    xml_path = Path(tmp_dir) / "word" / "document.xml"
    tree = etree.parse(str(xml_path))
    return tree, xml_path


def load_rels_xml(tmp_dir: str) -> Tuple[etree._ElementTree, Path]:
    """Load document.xml.rels as parsed tree."""
    xml_path = Path(tmp_dir) / "word" / "_rels" / "document.xml.rels"
    if not xml_path.exists():
        # Create empty relationships file
        rels_content = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
</Relationships>'''
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        xml_path.write_text(rels_content)
    tree = etree.parse(str(xml_path))
    return tree, xml_path


# -----------------------------
# ID Management
# -----------------------------

def get_max_bookmark_id(tree: etree._ElementTree) -> int:
    """Find the highest bookmark ID in document."""
    max_id = 0
    for elem in tree.iter():
        if elem.tag == f"{W_NS}bookmarkStart":
            bid = elem.get(f"{W_NS}id", "0")
            try:
                max_id = max(max_id, int(bid))
            except ValueError:
                pass
    return max_id


def get_max_rid(tree: etree._ElementTree) -> int:
    """Find the highest rId in relationships."""
    max_id = 0
    for elem in tree.iter():
        if elem.tag == "Relationship" or (isinstance(elem.tag, str) and elem.tag.endswith("}Relationship")):
            rid = elem.get("Id", "rId0")
            match = re.search(r'rId(\d+)', rid)
            if match:
                max_id = max(max_id, int(match.group(1)))
    return max_id


# -----------------------------
# Body Paragraph Helpers (consistent with ES para_start_int/para_end_int)
# -----------------------------

def _get_body_paragraphs(tree: etree._ElementTree) -> List[Tuple[int, etree._Element]]:
    """Get top-level <w:p> elements under <w:body> with their indices.
    Index convention matches the ES indexer (para_start_int/para_end_int).
    """
    body = tree.find(f".//{W_NS}body")
    if body is None:
        return []
    result = []
    idx = 0
    for child in body:
        if child.tag == f"{W_NS}p":
            result.append((idx, child))
            idx += 1
    return result


def _get_all_paragraphs(tree: etree._ElementTree) -> List[Tuple[int, etree._Element]]:
    """Get ALL <w:p> elements in the document, including those inside table cells.

    Falls back to this when _get_body_paragraphs() can't find a match,
    which happens when the target text is inside <w:tbl>/<w:tr>/<w:tc>.
    Index is sequential across the entire document (top-level + nested).
    """
    body = tree.find(f".//{W_NS}body")
    if body is None:
        return []
    result = []
    idx = 0
    for p in body.iter(f"{W_NS}p"):
        result.append((idx, p))
        idx += 1
    return result


def _para_text(p: etree._Element) -> str:
    return "".join(p.xpath(".//w:t/text()", namespaces=NS))


def _filter_paragraphs(
    paragraphs: List[Tuple[int, etree._Element]],
    text: str,
    nearby: str = "",
    para_range: Optional[Tuple[int, int]] = None,
) -> List[Tuple[int, etree._Element]]:
    """Filter paragraphs by text match, optional para_range, and optional nearby."""
    hits = []
    for idx, p in paragraphs:
        if para_range and not (para_range[0] <= idx <= para_range[1]):
            continue
        if text not in _para_text(p):
            continue
        if nearby:
            found = False
            for j_idx, j_p in paragraphs:
                if abs(j_idx - idx) <= 3 and nearby in _para_text(j_p):
                    found = True
                    break
            if not found:
                continue
        hits.append((idx, p))
    return hits


# -----------------------------
# Bookmark Operations
# -----------------------------

def _run_text(run: etree._Element) -> str:
    """Get concatenated text from a run (w:r)."""
    return "".join(run.xpath(".//w:t/text()", namespaces=NS))


def _find_run_containing_text(paragraph: etree._Element, text: str) -> Optional[Tuple[etree._Element, int]]:
    """Find the first run (or wrapper element) that contains text.

    Searches:
      1. Direct child <w:r> elements
      2. <w:r> elements nested inside <w:hyperlink> children
      3. <w:r> elements nested inside <w:ins> children (tracked-change insertions)
      4. Text split across consecutive runs (cross-run matching)

    Returns (element, child_index) where element is the <w:r>,
    <w:hyperlink>, or <w:ins> that should be operated on.
    """
    _CONTAINER_TAGS = {f"{W_NS}hyperlink", f"{W_NS}ins"}

    candidates = []
    for i, child in enumerate(paragraph):
        if child.tag == f"{W_NS}r":
            candidates.append((i, child, _run_text(child)))
        elif child.tag in _CONTAINER_TAGS:
            container_text = "".join(child.xpath(".//w:t/text()", namespaces=NS))
            candidates.append((i, child, container_text))

    # Fast path: single element contains the text
    for idx, elem, elem_text in candidates:
        if text in elem_text:
            return (elem, idx)

    # Slow path: text split across adjacent runs
    for start in range(len(candidates)):
        concat = ""
        for end in range(start, len(candidates)):
            concat += candidates[end][2]
            if text in concat:
                return (candidates[start][1], candidates[start][0])
            if len(concat) > len(text) * 3:
                break

    return None


def _sanitize_bookmark_name(name: str) -> str:
    """Sanitize bookmark name for Word compatibility.

    Word allows up to 40 chars; spaces are replaced with underscores,
    and the name must not start with a digit.  We keep Unicode characters
    (Chinese, etc.) because modern Word handles them fine.
    """
    name = name.replace(" ", "_")
    if name and name[0].isdigit():
        name = "_" + name
    if len(name) > 40:
        name = name[:40]
    return name


def add_bookmark(paragraph: etree._Element, name: str, bid: int) -> None:
    """Add bookmark pair to paragraph.

    Args:
        paragraph: <w:p> element
        name: Bookmark name (auto-sanitized for Word compatibility)
        bid: Bookmark ID (must be unique)
    """
    name = _sanitize_bookmark_name(name)
    if not name:
        raise ValueError("Bookmark name is empty after sanitization")
    
    # Create bookmarkStart
    start = etree.Element(f"{W_NS}bookmarkStart")
    start.set(f"{W_NS}id", str(bid))
    start.set(f"{W_NS}name", name)
    
    # Create bookmarkEnd
    end = etree.Element(f"{W_NS}bookmarkEnd")
    end.set(f"{W_NS}id", str(bid))
    
    # Insert at beginning of paragraph
    paragraph.insert(0, start)
    paragraph.append(end)


def add_bookmark_to_run(paragraph: etree._Element, run: etree._Element, run_index: int, name: str, bid: int) -> None:
    """Add bookmark pair around a single run (bookmark and link on requirement ID only).

    Args:
        paragraph: <w:p> element (parent of run)
        run: <w:r> element that contains the requirement ID text
        run_index: index of run in paragraph
        name: Bookmark name (auto-sanitized for Word compatibility)
        bid: Bookmark ID (must be unique)
    """
    name = _sanitize_bookmark_name(name)
    if not name:
        raise ValueError("Bookmark name is empty after sanitization")
    start = etree.Element(f"{W_NS}bookmarkStart")
    start.set(f"{W_NS}id", str(bid))
    start.set(f"{W_NS}name", name)
    end = etree.Element(f"{W_NS}bookmarkEnd")
    end.set(f"{W_NS}id", str(bid))
    paragraph.insert(run_index, start)
    # Run is now at run_index+1; insert end after it
    paragraph.insert(run_index + 2, end)


def insert_bookmark(docx: str, text: str, bookmark_name: str, out: str, 
                    occurrence: int = 0, nearby: str = "",
                    para_range: Optional[Tuple[int, int]] = None) -> bool:
    """Insert bookmark at paragraph containing text.
    
    Args:
        docx: Input DOCX path
        text: Text to search for (paragraph containing this text gets bookmark)
        bookmark_name: Name for bookmark
        out: Output DOCX path
        occurrence: Which occurrence to bookmark (0 = first)
        nearby: Nearby text for disambiguation (must appear within 3 paragraphs)
        para_range: (start, end) paragraph index range from ES para_start_int/para_end_int
    
    Returns:
        True if bookmark was inserted
    """
    tmp = f"tmp_docx_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    
    try:
        unzip_docx(docx, tmp)
        tree, xml_path = load_document_xml(tmp)
        
        all_paras = _get_body_paragraphs(tree)
        hits = _filter_paragraphs(all_paras, text, nearby, para_range)
        if not hits:
            all_paras = _get_all_paragraphs(tree)
            hits = _filter_paragraphs(all_paras, text, nearby, None)
        
        bid = get_max_bookmark_id(tree) + 1
        
        if occurrence < len(hits):
            _, p = hits[occurrence]
            add_bookmark(p, bookmark_name, bid)
            tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)
            zip_docx(tmp, out)
            return True
        
        return False
    
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def insert_bookmark_on_run(docx: str, text: str, bookmark_name: str, out: str,
                           occurrence: int = 0, nearby: str = "",
                           para_range: Optional[Tuple[int, int]] = None) -> bool:
    """Insert bookmark on the run that contains the given text (requirement ID only).
    
    Args:
        docx: Input DOCX path
        text: Text to search for (run containing this text gets bookmark)
        bookmark_name: Name for bookmark
        out: Output DOCX path
        occurrence: Which occurrence (0 = first)
        nearby: Nearby text for disambiguation
        para_range: (start, end) paragraph index range from ES
    
    Returns:
        True if bookmark was inserted
    """
    tmp = f"tmp_docx_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    try:
        unzip_docx(docx, tmp)
        tree, xml_path = load_document_xml(tmp)
        all_paras = _get_body_paragraphs(tree)
        bid = get_max_bookmark_id(tree) + 1

        def _search_paras(paras):
            nonlocal bid
            m = 0
            for p_idx, p in paras:
                if para_range and not (para_range[0] <= p_idx <= para_range[1]):
                    continue
                if nearby:
                    nearby_found = any(
                        nearby in _para_text(jp) for ji, jp in paras if abs(ji - p_idx) <= 3
                    )
                    if not nearby_found:
                        continue
                found = _find_run_containing_text(p, text)
                if found:
                    run, idx = found
                    if m == occurrence:
                        add_bookmark_to_run(p, run, idx, bookmark_name, bid)
                        tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)
                        zip_docx(tmp, out)
                        return True
                    m += 1
            return False

        if _search_paras(all_paras):
            return True
        if _search_paras(_get_all_paragraphs(tree)):
            return True
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def insert_cross_document_hyperlink_on_run(docx: str, text: str, target_doc: str,
                                           bookmark_name: str, link_text: Optional[str] = None,
                                           out: str = "", occurrence: int = 0,
                                           nearby: str = "",
                                           para_range: Optional[Tuple[int, int]] = None) -> Tuple[bool, Optional[str]]:
    """Insert cross-document hyperlink on the run that contains the given text only.
    
    Args:
        docx: Input DOCX path
        text: Text to search for (this run becomes the hyperlink)
        target_doc: Target document filename
        bookmark_name: Bookmark name in target document
        link_text: Display text (default: text)
        out: Output DOCX path
        occurrence: Which occurrence (0 = first)
        nearby: Nearby text for disambiguation
        para_range: (start, end) paragraph index range from ES
    
    Returns:
        (success, rId) tuple
    """
    if not out:
        out = docx
    target_doc = os.path.basename(target_doc)
    display = link_text if link_text is not None else text
    tmp = f"tmp_docx_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    try:
        unzip_docx(docx, tmp)
        tree, xml_path = load_document_xml(tmp)
        rid, anchor = add_relationship(tmp, f"{target_doc}#{bookmark_name}", "External")

        def _search_paras(paras):
            m = 0
            for p_idx, p in paras:
                if para_range and not (para_range[0] <= p_idx <= para_range[1]):
                    continue
                if nearby:
                    nearby_found = any(
                        nearby in _para_text(jp) for ji, jp in paras if abs(ji - p_idx) <= 3
                    )
                    if not nearby_found:
                        continue
                found = _find_run_containing_text(p, text)
                if found:
                    run, idx = found
                    if m == occurrence:
                        _replace_with_hyperlink(
                            p, run,
                            lambda source_run: create_external_hyperlink(
                                rid, display, source_run=source_run, anchor=anchor),
                            text,
                        )
                        tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)
                        zip_docx(tmp, out)
                        return True, rid
                    m += 1
            return None

        all_paras = _get_body_paragraphs(tree)
        result = _search_paras(all_paras)
        if result:
            return result
        result = _search_paras(_get_all_paragraphs(tree))
        if result:
            return result
        return False, None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -----------------------------
# Tracked-change aware replacement
# -----------------------------

def _replace_with_hyperlink(
    para: etree._Element,
    target: etree._Element,
    link_creator,
    text: str,
) -> bool:
    """Replace *target* with a hyperlink, preserving <w:ins> wrappers.

    When *target* is a ``<w:ins>`` element the hyperlink is created
    **inside** ``<w:ins>`` (replacing the inner ``<w:r>``), so the
    tracked-change context is preserved.  For plain ``<w:r>`` or
    ``<w:hyperlink>`` the replacement happens directly on *para*.

    Args:
        para:         parent ``<w:p>`` element.
        target:       element returned by ``_find_run_containing_text``.
        link_creator: ``callable(source_run) -> hyperlink_element``.
        text:         the search text (used to locate the inner run).
    """
    if target.tag == f"{W_NS}ins":
        for child in target:
            if child.tag == f"{W_NS}r" and text in _run_text(child):
                link = link_creator(source_run=child)
                target.replace(child, link)
                return True
        first_run = target.find(f"{W_NS}r")
        if first_run is not None:
            link = link_creator(source_run=first_run)
            target.replace(first_run, link)
            return True
        return False

    link = link_creator(source_run=target)
    para.replace(target, link)
    return True


# -----------------------------
# Hyperlink Operations
# -----------------------------

def _wrap_run_in_hyperlink(run: etree._Element, hyperlink: etree._Element) -> etree._Element:
    """Move an existing run into a hyperlink element, adding Hyperlink rStyle.

    Preserves the original run's formatting (font, size, bold, etc.)
    and only adds the Hyperlink rStyle on top.
    """
    run_copy = copy.deepcopy(run)

    rpr = run_copy.find(f"{W_NS}rPr")
    if rpr is None:
        rpr = etree.Element(f"{W_NS}rPr")
        run_copy.insert(0, rpr)

    has_style = any(
        child.tag == f"{W_NS}rStyle" and child.get(f"{W_NS}val") == "Hyperlink"
        for child in rpr
    )
    if not has_style:
        style = etree.Element(f"{W_NS}rStyle")
        style.set(f"{W_NS}val", "Hyperlink")
        rpr.insert(0, style)

    hyperlink.append(run_copy)
    return hyperlink


def create_internal_hyperlink(anchor: str, text: str,
                               source_run: Optional[etree._Element] = None) -> etree._Element:
    """Create internal hyperlink element (w:anchor style).

    If source_run is provided, its formatting is preserved.
    Otherwise a plain run is created.
    """
    hyperlink = etree.Element(f"{W_NS}hyperlink")
    hyperlink.set(f"{W_NS}anchor", anchor)

    if source_run is not None:
        _wrap_run_in_hyperlink(source_run, hyperlink)
    else:
        run = etree.SubElement(hyperlink, f"{W_NS}r")
        rpr = etree.SubElement(run, f"{W_NS}rPr")
        style = etree.SubElement(rpr, f"{W_NS}rStyle")
        style.set(f"{W_NS}val", "Hyperlink")
        t = etree.SubElement(run, f"{W_NS}t")
        t.text = text

    return hyperlink


def create_external_hyperlink(rid: str, text: str,
                               source_run: Optional[etree._Element] = None,
                               anchor: Optional[str] = None) -> etree._Element:
    """Create external hyperlink element (r:id style for cross-document).

    If source_run is provided, its formatting is preserved.
    Otherwise a plain run is created.

    Args:
        rid: Relationship ID referencing the target document.
        text: Display text (used only when source_run is None).
        source_run: Existing <w:r> element whose formatting is preserved.
        anchor: Bookmark name in the target document.  When set, the
                ``w:anchor`` attribute is written on the hyperlink so Word
                navigates to the bookmark after opening the file.  This is
                the OOXML-standard way and works reliably with non-ASCII
                bookmark names (Chinese, etc.).
    """
    hyperlink = etree.Element(f"{W_NS}hyperlink")
    hyperlink.set(f"{R_NS}id", rid)
    if anchor:
        hyperlink.set(f"{W_NS}anchor", anchor)

    if source_run is not None:
        _wrap_run_in_hyperlink(source_run, hyperlink)
    else:
        run = etree.SubElement(hyperlink, f"{W_NS}r")
        rpr = etree.SubElement(run, f"{W_NS}rPr")
        style = etree.SubElement(rpr, f"{W_NS}rStyle")
        style.set(f"{W_NS}val", "Hyperlink")
        t = etree.SubElement(run, f"{W_NS}t")
        t.text = text

    return hyperlink


def add_relationship(tmp_dir: str, target: str, target_mode: str = "External") -> Tuple[str, Optional[str]]:
    """Add relationship entry for external hyperlink.

    If *target* contains a ``#fragment`` (e.g. ``"docB.docx#bookmark"``),
    the fragment is stripped from the relationship Target and returned
    separately so the caller can put it in ``w:anchor`` on the hyperlink
    element — the OOXML-standard approach that works with non-ASCII
    bookmark names.

    Args:
        tmp_dir: Unpacked DOCX directory.
        target: ``"docB.docx"`` or ``"docB.docx#bookmark_name"``.
        target_mode: ``"External"`` for cross-document.

    Returns:
        ``(rId, anchor_or_None)`` — anchor is the bookmark part after
        ``#``, or ``None`` when there is no fragment.
    """
    anchor: Optional[str] = None
    if "#" in target:
        target, anchor = target.rsplit("#", 1)

    tree, xml_path = load_rels_xml(tmp_dir)

    max_rid = get_max_rid(tree)
    new_rid = f"rId{max_rid + 1}"

    root = tree.getroot()

    rel = etree.SubElement(root, "Relationship")
    rel.set("Id", new_rid)
    rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink")
    rel.set("Target", target)
    rel.set("TargetMode", target_mode)

    tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)

    return new_rid, anchor


def insert_internal_hyperlink(docx: str, text: str, bookmark_name: str, 
                               link_text: Optional[str] = None, out: str = "",
                               occurrence: int = 0, nearby: str = "",
                               para_range: Optional[Tuple[int, int]] = None) -> bool:
    """Insert internal hyperlink at paragraph containing text.
    
    Args:
        docx: Input DOCX path
        text: Text to search for (hyperlink replaces this text)
        bookmark_name: Target bookmark name
        link_text: Custom display text (default: use original text)
        out: Output DOCX path (default: overwrite input)
        occurrence: Which occurrence to hyperlink (0 = first)
        nearby: Nearby text for disambiguation
        para_range: (start, end) paragraph index range from ES
    
    Returns:
        True if hyperlink was inserted
    """
    if not out:
        out = docx
    
    tmp = f"tmp_docx_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    
    try:
        unzip_docx(docx, tmp)
        tree, xml_path = load_document_xml(tmp)
        
        all_paras = _get_body_paragraphs(tree)
        hits = _filter_paragraphs(all_paras, text, nearby, para_range)
        if not hits:
            all_paras = _get_all_paragraphs(tree)
            hits = _filter_paragraphs(all_paras, text, nearby, None)
        display_text = link_text if link_text else text
        
        if occurrence < len(hits):
            _, p = hits[occurrence]
            target_run = _find_run_containing_text(p, text)
            if target_run:
                run, run_idx = target_run
                _replace_with_hyperlink(
                    p, run,
                    lambda source_run: create_internal_hyperlink(
                        bookmark_name, display_text, source_run=source_run),
                    text,
                )
            else:
                link = create_internal_hyperlink(bookmark_name, display_text)
                p.append(link)
            
            tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)
            zip_docx(tmp, out)
            return True
        
        return False
    
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def insert_cross_document_hyperlink(docx: str, text: str, target_doc: str,
                                      bookmark_name: str, out: str = "",
                                      occurrence: int = 0, nearby: str = "",
                                      para_range: Optional[Tuple[int, int]] = None) -> Tuple[bool, Optional[str]]:
    """Insert cross-document hyperlink.
    
    Args:
        docx: Input DOCX path
        text: Text to search for
        target_doc: Target document filename (e.g., "docB.docx")
        bookmark_name: Bookmark name in target document
        out: Output DOCX path (default: overwrite input)
        occurrence: Which occurrence to hyperlink (0 = first)
        nearby: Nearby text for disambiguation
        para_range: (start, end) paragraph index range from ES
    
    Returns:
        (success, rId) tuple
    """
    if not out:
        out = docx
    target_doc = os.path.basename(target_doc)
    
    tmp = f"tmp_docx_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    
    try:
        unzip_docx(docx, tmp)
        tree, xml_path = load_document_xml(tmp)
        
        target_with_bookmark = f"{target_doc}#{bookmark_name}"
        rid, anchor = add_relationship(tmp, target_with_bookmark, "External")
        
        all_paras = _get_body_paragraphs(tree)
        hits = _filter_paragraphs(all_paras, text, nearby, para_range)
        if not hits:
            all_paras = _get_all_paragraphs(tree)
            hits = _filter_paragraphs(all_paras, text, nearby, None)
        
        if occurrence < len(hits):
            _, p = hits[occurrence]
            target_run = _find_run_containing_text(p, text)
            if target_run:
                run, run_idx = target_run
                _replace_with_hyperlink(
                    p, run,
                    lambda source_run: create_external_hyperlink(
                        rid, text, source_run=source_run, anchor=anchor),
                    text,
                )
            else:
                link = create_external_hyperlink(rid, text, anchor=anchor)
                p.append(link)
            
            tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)
            zip_docx(tmp, out)
            return True, rid
        
        return False, None
    
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -----------------------------
# One-to-many: split text into N segments with N hyperlinks
# -----------------------------

def _split_text_evenly(text: str, n: int) -> List[str]:
    """Split *text* into *n* non-empty segments of roughly equal length."""
    if n <= 0:
        return []
    if n == 1:
        return [text]
    total = len(text)
    base, extra = divmod(total, n)
    segments, pos = [], 0
    for i in range(n):
        length = base + (1 if i < extra else 0)
        segments.append(text[pos:pos + length])
        pos += length
    return [s for s in segments if s]


def _clone_run_with_text(source_run: etree._Element, text: str) -> etree._Element:
    """Create a new <w:r> with the same rPr as *source_run* but different text."""
    run = copy.deepcopy(source_run)
    for t_elem in run.findall(f".//{W_NS}t"):
        t_elem.getparent().remove(t_elem)
    t = etree.SubElement(run, f"{W_NS}t")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    return run


def split_run_with_cross_document_hyperlinks(
    docx: str,
    text: str,
    targets: List[Tuple[str, str]],
    out: str = "",
    nearby: str = "",
    para_range: Optional[Tuple[int, int]] = None,
) -> Tuple[int, List[str]]:
    """Split a text run into N segments, each becoming a cross-document hyperlink.

    Designed for **one-to-many** mapping: one source ID text (e.g.
    ``"GAC_驾驶信息_07"``) links to multiple targets.

    The text is split into ``len(targets)`` approximately equal segments by
    character count.  Each segment becomes an independent clickable hyperlink
    pointing to its corresponding target document + bookmark.

    Example::

        split_run_with_cross_document_hyperlinks(
            "eea_out.docx", "GAC_驾驶信息_07",
            targets=[
                ("gac_out.docx", "BM_FUNC_0103"),
                ("gac_out.docx", "BM_FUNC_0105"),
                ("gac_out.docx", "BM_FUNC_0073"),
            ],
            out="eea_out.docx",
        )
        # "GAC_驾" → link to BM_FUNC_0103
        # "驶信息" → link to BM_FUNC_0105
        # "_07"   → link to BM_FUNC_0073

    Args:
        docx: Input DOCX path.
        text: Text to find and split.
        targets: ``[(target_doc_filename, bookmark_name), ...]`` — one per
                 segment.  When only 1 target, no splitting; the whole text
                 becomes a single hyperlink.
        out: Output DOCX path (default: overwrite input).
        nearby: Nearby text for disambiguation.
        para_range: ``(start, end)`` paragraph index range from ES.

    Returns:
        ``(links_created, rIds)`` tuple.
    """
    if not out:
        out = docx
    if not targets:
        return 0, []

    tmp = f"tmp_docx_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    try:
        unzip_docx(docx, tmp)
        tree, xml_path = load_document_xml(tmp)

        rids: List[str] = []
        anchors: List[Optional[str]] = []
        for target_doc, bm_name in targets:
            target_doc = os.path.basename(target_doc)
            rid, anchor = add_relationship(tmp, f"{target_doc}#{bm_name}", "External")
            rids.append(rid)
            anchors.append(anchor)

        def _try_paras(paras):
            for p_idx, p in paras:
                if para_range and not (para_range[0] <= p_idx <= para_range[1]):
                    continue
                if nearby:
                    if not any(nearby in _para_text(jp) for ji, jp in paras if abs(ji - p_idx) <= 3):
                        continue
                found = _find_run_containing_text(p, text)
                if not found:
                    continue
                run, run_idx = found

                # Resolve the actual <w:r> when the match is inside <w:ins>
                actual_run = run
                parent_container = p
                if run.tag == f"{W_NS}ins":
                    for child in run:
                        if child.tag == f"{W_NS}r" and text in _run_text(child):
                            actual_run = child
                            parent_container = run
                            break

                run_full_text = _run_text(actual_run)
                start_offset = run_full_text.find(text)
                if start_offset < 0:
                    continue
                target_text = run_full_text[start_offset:start_offset + len(text)]

                segments = _split_text_evenly(target_text, len(targets))
                if len(segments) != len(targets):
                    continue

                prefix = run_full_text[:start_offset]
                suffix = run_full_text[start_offset + len(text):]

                new_elements: list = []
                if prefix:
                    new_elements.append(_clone_run_with_text(actual_run, prefix))
                for i, seg in enumerate(segments):
                    seg_run = _clone_run_with_text(actual_run, seg)
                    link = create_external_hyperlink(
                        rids[i], seg, source_run=seg_run, anchor=anchors[i],
                    )
                    new_elements.append(link)
                if suffix:
                    new_elements.append(_clone_run_with_text(actual_run, suffix))

                idx_in_parent = list(parent_container).index(actual_run)
                parent_container.remove(actual_run)
                for offset, elem in enumerate(new_elements):
                    parent_container.insert(idx_in_parent + offset, elem)

                tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)
                zip_docx(tmp, out)
                return len(segments), rids
            return None

        result = _try_paras(_get_body_paragraphs(tree))
        if result:
            return result
        result = _try_paras(_get_all_paragraphs(tree))
        if result:
            return result
        return 0, []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -----------------------------
# Coordinate-based navigation (consumed by batch_operations)
# -----------------------------

def _navigate_to_paragraph(
    body: etree._Element, locator: dict,
) -> Optional[etree._Element]:
    """Navigate to a ``<w:p>`` element using a Locator dict from keyword_locator.

    Supports both body paragraphs (``in_table=False``) and table cells
    (``in_table=True``).  Returns ``None`` on out-of-range coordinates.
    """
    if not locator.get("in_table"):
        idx = 0
        for child in body:
            if child.tag == f"{W_NS}p":
                if idx == locator.get("paragraph_idx", -1):
                    return child
                idx += 1
    else:
        t_idx = 0
        for child in body:
            if child.tag == f"{W_NS}tbl":
                if t_idx == locator.get("table_idx", -1):
                    rows = child.findall(f"{W_NS}tr")
                    r = locator.get("row_idx", 0)
                    if r >= len(rows):
                        return None
                    cells = rows[r].findall(f"{W_NS}tc")
                    c = locator.get("cell_idx", 0)
                    if c >= len(cells):
                        return None
                    paras = cells[c].findall(f"{W_NS}p")
                    cp = locator.get("cell_para_idx", 0)
                    if cp >= len(paras):
                        return None
                    return paras[cp]
                t_idx += 1
    return None


def batch_operations(
    docx: str,
    operations: List[dict],
    out: str = "",
) -> dict:
    """Execute multiple bookmark / hyperlink operations in one pass using
    pre-located coordinates from ``keyword_locator``.

    Each operation dict must contain:

    - ``"op"``: one of ``"bookmark"``, ``"hyperlink"``, ``"split_hyperlink"``
    - ``"locator"``: a Locator dict as returned by ``keyword_locator``
      (must include ``keyword``, ``in_table``, and coordinate fields)

    Operation-specific fields:

    ``bookmark``
        ``"bookmark_name"``

    ``hyperlink``
        ``"target_doc"``, ``"bookmark_name"``

    ``split_hyperlink``
        ``"targets"``: ``[(target_doc, bookmark_name), ...]``

    Returns a dict with::

        {
            "bookmarks": int,
            "hyperlinks": int,
            "splits": int,
            "failed": int,
            "failed_details": [
                {
                    "index": int,       # position in operations list
                    "op": str,          # "bookmark" / "hyperlink" / "split_hyperlink" / unknown
                    "keyword": str,     # keyword that was being located
                    "reason": str,      # machine-readable failure code
                    "detail": str,      # human-readable explanation
                },
                ...
            ]
        }

    Failure reason codes:

    - ``nav_failed``         — locator coordinates did not resolve to a paragraph
    - ``keyword_not_in_para`` — paragraph found but keyword text absent
    - ``run_not_found``      — no run/container element holds the keyword
    - ``coalesce_failed``    — keyword spans multiple runs and merge failed
    - ``empty_targets``      — split_hyperlink with empty targets list
    - ``keyword_not_in_run`` — keyword not found in the resolved run text
    - ``segment_mismatch``   — split produced fewer segments than targets
    - ``unknown_op``         — unrecognised operation type
    """
    if not out:
        out = docx
    if not operations:
        return {"bookmarks": 0, "hyperlinks": 0, "splits": 0, "failed": 0,
                "failed_details": []}

    tmp = f"tmp_docx_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    try:
        unzip_docx(docx, tmp)
        tree, xml_path = load_document_xml(tmp)
        body = tree.find(f".//{W_NS}body")
        bid = get_max_bookmark_id(tree) + 1

        stats: dict = {"bookmarks": 0, "hyperlinks": 0, "splits": 0,
                        "failed": 0, "failed_details": []}

        def _fail(idx: int, op: str, keyword: str, reason: str, detail: str) -> None:
            stats["failed"] += 1
            stats["failed_details"].append({
                "index": idx,
                "op": op,
                "keyword": keyword,
                "reason": reason,
                "detail": detail,
            })

        for op_idx, spec in enumerate(operations):
            op = spec.get("op", "")
            loc = spec.get("locator", {})
            kw = loc.get("keyword", spec.get("keyword", ""))

            para = _navigate_to_paragraph(body, loc)
            if para is None:
                _fail(op_idx, op, kw, "nav_failed",
                      f"locator coordinates did not resolve: "
                      f"in_table={loc.get('in_table')}, "
                      f"paragraph_idx={loc.get('paragraph_idx')}, "
                      f"table_idx={loc.get('table_idx')}")
                continue
            para_txt = _para_text(para)
            if kw not in para_txt:
                _fail(op_idx, op, kw, "keyword_not_in_para",
                      f"paragraph resolved but keyword absent; "
                      f"para_text[:80]={para_txt[:80]!r}")
                continue

            found = _find_run_containing_text(para, kw)
            if not found:
                _fail(op_idx, op, kw, "run_not_found",
                      "keyword exists in paragraph text but no single run or "
                      "container element holds it (may be split across runs)")
                continue

            run, run_child_idx = found

            need_coalesce = (kw not in _run_text(run)
                             and run.tag != f"{W_NS}ins"
                             and run.tag != f"{W_NS}hyperlink")
            if need_coalesce:
                coalesced = _coalesce_runs(para, kw)
                if coalesced:
                    run, run_child_idx = coalesced
                else:
                    _fail(op_idx, op, kw, "coalesce_failed",
                          "keyword spans multiple runs and automatic merge failed")
                    continue

            if op == "bookmark":
                bm_name = spec["bookmark_name"]
                add_bookmark_to_run(para, run, run_child_idx, bm_name, bid)
                bid += 1
                stats["bookmarks"] += 1

            elif op == "hyperlink":
                target_doc = os.path.basename(spec["target_doc"])
                bm_name = spec["bookmark_name"]
                rid, anchor = add_relationship(
                    tmp, f"{target_doc}#{bm_name}", "External")

                actual_run = run
                parent_container = para
                if run.tag == f"{W_NS}ins":
                    for ch in run:
                        if ch.tag == f"{W_NS}r" and kw in _run_text(ch):
                            actual_run = ch
                            parent_container = run
                            break

                run_full_text = _run_text(actual_run)
                start_off = run_full_text.find(kw)

                if start_off < 0 or run_full_text == kw:
                    _replace_with_hyperlink(
                        para, run,
                        lambda source_run, _r=rid, _d=kw, _a=anchor: create_external_hyperlink(
                            _r, _d, source_run=source_run, anchor=_a),
                        kw,
                    )
                else:
                    prefix = run_full_text[:start_off]
                    suffix = run_full_text[start_off + len(kw):]
                    kw_run = _clone_run_with_text(actual_run, kw)
                    link = create_external_hyperlink(
                        rid, kw, source_run=kw_run, anchor=anchor)

                    new_elems: list = []
                    if prefix:
                        new_elems.append(_clone_run_with_text(actual_run, prefix))
                    new_elems.append(link)
                    if suffix:
                        new_elems.append(_clone_run_with_text(actual_run, suffix))

                    idx_in_parent = list(parent_container).index(actual_run)
                    parent_container.remove(actual_run)
                    for offset, elem in enumerate(new_elems):
                        parent_container.insert(idx_in_parent + offset, elem)

                stats["hyperlinks"] += 1

            elif op == "split_hyperlink":
                targets = spec.get("targets", [])
                if not targets:
                    _fail(op_idx, op, kw, "empty_targets",
                          "split_hyperlink requires non-empty targets list")
                    continue
                rids_a: List[str] = []
                anchors_a: List[Optional[str]] = []
                for td, bn in targets:
                    td = os.path.basename(td)
                    r_id, anc = add_relationship(
                        tmp, f"{td}#{bn}", "External")
                    rids_a.append(r_id)
                    anchors_a.append(anc)

                actual_run = run
                parent_container = para
                if run.tag == f"{W_NS}ins":
                    for ch in run:
                        if ch.tag == f"{W_NS}r" and kw in _run_text(ch):
                            actual_run = ch
                            parent_container = run
                            break

                run_full_text = _run_text(actual_run)
                start_off = run_full_text.find(kw)
                if start_off < 0:
                    _fail(op_idx, op, kw, "keyword_not_in_run",
                          f"keyword not found in resolved run text: "
                          f"run_text[:80]={run_full_text[:80]!r}")
                    continue
                segments = _split_text_evenly(kw, len(targets))
                if len(segments) != len(targets):
                    _fail(op_idx, op, kw, "segment_mismatch",
                          f"split produced {len(segments)} segments "
                          f"but {len(targets)} targets given")
                    continue

                prefix = run_full_text[:start_off]
                suffix = run_full_text[start_off + len(kw):]

                new_elems: list = []
                if prefix:
                    new_elems.append(_clone_run_with_text(actual_run, prefix))
                for i, seg in enumerate(segments):
                    seg_run = _clone_run_with_text(actual_run, seg)
                    link = create_external_hyperlink(
                        rids_a[i], seg, source_run=seg_run,
                        anchor=anchors_a[i])
                    new_elems.append(link)
                if suffix:
                    new_elems.append(_clone_run_with_text(actual_run, suffix))

                idx_in_parent = list(parent_container).index(actual_run)
                parent_container.remove(actual_run)
                for offset, elem in enumerate(new_elems):
                    parent_container.insert(idx_in_parent + offset, elem)
                stats["splits"] += 1

            else:
                _fail(op_idx, op, kw, "unknown_op",
                      f"unrecognised operation type: {op!r}")

        tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)
        zip_docx(tmp, out)
        return stats
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _coalesce_runs(para: etree._Element, keyword: str) -> Optional[Tuple[etree._Element, int]]:
    """Merge adjacent runs/containers that together span *keyword* into one run.

    When Word fragments text across multiple ``<w:r>`` elements (e.g.
    ``_F`` + ``UN`` + ``C_`` + ``0082`` for ``FUNC_0082``), this helper
    finds the contiguous span, concatenates the text into the first run,
    removes the consumed elements, and returns ``(merged_run, child_idx)``.

    Returns ``None`` if the keyword cannot be found even across runs.
    """
    _RUN_TAGS = {f"{W_NS}r", f"{W_NS}hyperlink", f"{W_NS}ins"}
    children = list(para)
    texts: List[Tuple[int, etree._Element, str]] = []
    for i, ch in enumerate(children):
        if ch.tag in _RUN_TAGS:
            t = "".join(ch.xpath(".//w:t/text()", namespaces=NS))
            texts.append((i, ch, t))

    for si in range(len(texts)):
        concat = ""
        for ei in range(si, len(texts)):
            concat += texts[ei][2]
            if keyword in concat:
                if si == ei:
                    return (texts[si][1], texts[si][0])
                first_elem = texts[si][1]
                first_idx = texts[si][0]
                merged_text = concat

                rpr = first_elem.find(f"{W_NS}rPr")
                new_run = etree.Element(f"{W_NS}r")
                if rpr is not None:
                    new_run.append(copy.deepcopy(rpr))
                t_el = etree.SubElement(new_run, f"{W_NS}t")
                t_el.text = merged_text
                if merged_text and (merged_text[0] == " " or merged_text[-1] == " "):
                    t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

                para.insert(first_idx, new_run)
                for j in range(si, ei + 1):
                    elem = texts[j][1]
                    if elem.getparent() is para:
                        para.remove(elem)
                return (new_run, first_idx)
            if len(concat) > len(keyword) * 4:
                break
    return None


# -----------------------------
# Batch helpers
# -----------------------------

def _find_run_in_para_list(
    paras: List[Tuple[int, etree._Element]], text: str,
) -> Optional[Tuple[int, etree._Element, etree._Element, int]]:
    """Search *paras* for the first run containing *text*.

    Returns ``(para_index, paragraph, run, run_child_index)`` or ``None``.
    """
    for pi, p in paras:
        found = _find_run_containing_text(p, text)
        if found:
            run, ri = found
            return pi, p, run, ri
    return None


# -----------------------------
# Batch Operations
# -----------------------------

def batch_insert_bookmarks(docx: str, bookmark_specs: List[Tuple[str, str]], 
                           out: str = "") -> int:
    """Insert multiple bookmarks at once.

    Uses body-first search: prefers ``w:body`` direct-child paragraphs,
    falls back to all paragraphs (tables, TOC, etc.) per item.
    
    Args:
        docx: Input DOCX path
        bookmark_specs: List of (text_to_find, bookmark_name) tuples
        out: Output DOCX path
    
    Returns:
        Number of bookmarks successfully inserted
    """
    if not out:
        out = docx
    
    tmp = f"tmp_docx_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    
    try:
        unzip_docx(docx, tmp)
        tree, xml_path = load_document_xml(tmp)
        
        body_paras = _get_body_paragraphs(tree)
        all_paras = _get_all_paragraphs(tree)
        bid = get_max_bookmark_id(tree) + 1
        inserted = 0
        
        for text, name in bookmark_specs:
            target_p = None
            for _, p in body_paras:
                if text in _para_text(p):
                    target_p = p
                    break
            if target_p is None:
                for _, p in all_paras:
                    if text in _para_text(p):
                        target_p = p
                        break
            if target_p is not None:
                add_bookmark(target_p, name, bid)
                bid += 1
                inserted += 1
        
        tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)
        zip_docx(tmp, out)
        return inserted
    
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def batch_insert_bookmarks_on_run(docx: str, bookmark_specs: List[Tuple[str, str]],
                                  out: str = "") -> int:
    """Insert multiple bookmarks on runs (requirement ID only) in one pass.

    Uses body-first search: prefers ``w:body`` direct-child paragraphs,
    falls back to all paragraphs (tables, TOC, etc.) per item.
    
    Args:
        docx: Input DOCX path
        bookmark_specs: List of (text_to_find, bookmark_name) - each text should be in a single run
        out: Output DOCX path
    
    Returns:
        Number of bookmarks inserted
    """
    if not out:
        out = docx
    tmp = f"tmp_docx_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    try:
        unzip_docx(docx, tmp)
        tree, xml_path = load_document_xml(tmp)
        body_paras = _get_body_paragraphs(tree)
        all_paras = _get_all_paragraphs(tree)
        bid = get_max_bookmark_id(tree) + 1
        to_add: List[Tuple[int, int, etree._Element, etree._Element, str, int]] = []
        for text, name in bookmark_specs:
            hit = _find_run_in_para_list(body_paras, text)
            if hit is None:
                hit = _find_run_in_para_list(all_paras, text)
            if hit is not None:
                pi, p, run, ri = hit
                to_add.append((pi, ri, p, run, name, bid))
                bid += 1
        to_add.sort(key=lambda x: (x[0], x[1]), reverse=True)
        for (_pi, _ri, p, run, name, bid_val) in to_add:
            idx = list(p).index(run)
            add_bookmark_to_run(p, run, idx, name, bid_val)
        tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)
        zip_docx(tmp, out)
        return len(to_add)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def batch_insert_cross_document_hyperlinks_on_run(
    docx: str,
    specs: List[Tuple[str, str, str, Optional[str]]],
    out: str = "",
) -> int:
    """Insert multiple cross-document hyperlinks on runs in one pass.

    Uses body-first search: for each spec, prefers ``w:body``
    direct-child paragraphs; falls back to all paragraphs (tables,
    TOC, etc.) when the text is not found in the body.
    
    Args:
        docx: Input DOCX path
        specs: List of (text_to_find, target_doc_filename, bookmark_name, link_text optional)
        out: Output DOCX path
    
    Returns:
        Number of hyperlinks inserted
    """
    if not out:
        out = docx
    tmp = f"tmp_docx_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    try:
        unzip_docx(docx, tmp)
        tree, xml_path = load_document_xml(tmp)
        rids: List[str] = []
        anchors: List[Optional[str]] = []
        for (text, target_doc, bm_name, link_text) in specs:
            target_doc = os.path.basename(target_doc)
            rid, anchor = add_relationship(tmp, f"{target_doc}#{bm_name}", "External")
            rids.append(rid)
            anchors.append(anchor)

        body_paras = _get_body_paragraphs(tree)
        all_paras = _get_all_paragraphs(tree)

        inserted = 0
        used_runs: set = set()
        for idx, (text, target_doc, bm_name, link_text) in enumerate(specs):
            hit = _find_run_in_para_list(body_paras, text)
            if hit is None or id(hit[2]) in used_runs:
                hit = _find_run_in_para_list(all_paras, text)
            if hit is None or id(hit[2]) in used_runs:
                continue
            _pi, p, run, _ri = hit
            used_runs.add(id(run))
            display = link_text if link_text else text
            link = create_external_hyperlink(rids[idx], display, source_run=run, anchor=anchors[idx])
            p.replace(run, link)
            inserted += 1
        tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)
        zip_docx(tmp, out)
        return inserted
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -----------------------------
# CLI
# -----------------------------

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Word DOCX Bookmark + Hyperlink Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Add bookmark
  python docx_link_engine.py bookmark --docx spec.docx --text "REQ_1234" --name REQ_1234 --out spec_bookmarked.docx
  
  # Add internal hyperlink
  python docx_link_engine.py hyperlink --docx spec.docx --text "see REQ_1234" --name REQ_1234 --out spec_linked.docx
  
  # Add cross-document hyperlink
  python docx_link_engine.py xlink --docx docA.docx --text "see page 15" --target docB.docx --name page_15 --out docA_linked.docx
        """)
    
    subparsers = parser.add_subparsers(dest="mode", required=True)
    
    # Bookmark subcommand
    bm_parser = subparsers.add_parser("bookmark", help="Insert bookmark")
    bm_parser.add_argument("--docx", required=True, help="Input DOCX file")
    bm_parser.add_argument("--text", required=True, help="Text to find (paragraph containing this gets bookmark)")
    bm_parser.add_argument("--name", required=True, help="Bookmark name")
    bm_parser.add_argument("--out", required=True, help="Output DOCX file")
    bm_parser.add_argument("--occurrence", type=int, default=0, help="Which occurrence (0=first)")
    
    # Internal hyperlink subcommand
    hl_parser = subparsers.add_parser("hyperlink", help="Insert internal hyperlink")
    hl_parser.add_argument("--docx", required=True, help="Input DOCX file")
    hl_parser.add_argument("--text", required=True, help="Text to find and convert to hyperlink")
    hl_parser.add_argument("--name", required=True, help="Target bookmark name")
    hl_parser.add_argument("--link-text", help="Custom display text (default: use --text)")
    hl_parser.add_argument("--out", required=True, help="Output DOCX file")
    hl_parser.add_argument("--occurrence", type=int, default=0, help="Which occurrence (0=first)")
    
    # Cross-document hyperlink subcommand
    xl_parser = subparsers.add_parser("xlink", help="Insert cross-document hyperlink")
    xl_parser.add_argument("--docx", required=True, help="Input DOCX file")
    xl_parser.add_argument("--text", required=True, help="Text to find and convert to hyperlink")
    xl_parser.add_argument("--target", required=True, help="Target document (e.g., docB.docx)")
    xl_parser.add_argument("--name", required=True, help="Bookmark name in target document")
    xl_parser.add_argument("--out", required=True, help="Output DOCX file")
    xl_parser.add_argument("--occurrence", type=int, default=0, help="Which occurrence (0=first)")
    
    args = parser.parse_args()
    
    if args.mode == "bookmark":
        result = insert_bookmark(args.docx, args.text, args.name, args.out, args.occurrence)
        if result:
            print(f"✅ Bookmark '{args.name}' inserted")
        else:
            print(f"❌ Text '{args.text}' not found")
            exit(1)
    
    elif args.mode == "hyperlink":
        result = insert_internal_hyperlink(
            args.docx, args.text, args.name, args.link_text, args.out, args.occurrence
        )
        if result:
            print(f"✅ Hyperlink to '{args.name}' inserted")
        else:
            print(f"❌ Text '{args.text}' not found")
            exit(1)
    
    elif args.mode == "xlink":
        result, rid = insert_cross_document_hyperlink(
            args.docx, args.text, args.target, args.name, args.out, args.occurrence
        )
        if result:
            print(f"✅ Cross-document hyperlink inserted (rId: {rid})")
        else:
            print(f"❌ Text '{args.text}' not found")
            exit(1)
