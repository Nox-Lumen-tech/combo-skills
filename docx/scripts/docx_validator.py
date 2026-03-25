#!/usr/bin/env python3
"""
docx_validator.py - DOCX 后置验证

在 Agent 生成 DOCX 后验证文件完整性，防止输出损坏文档。

检查项:
1. ZIP 结构完整性
2. [Content_Types].xml 存在
3. document.xml 可解析
4. XML 命名空间正确
5. <w:hyperlink> 内不含 <w:pPr>
6. bookmarkStart/bookmarkEnd 成对
7. 所有 r:id 在 rels 中有对应 Relationship

用法:
    python docx_validator.py validate --docx output.docx
    
    # 返回
    {"valid": true, "warnings": [], "errors": []}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import zipfile
import shutil
import uuid
from pathlib import Path
from typing import Dict, List
from lxml import etree

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
W_NS = "{%s}" % NS["w"]
R_NS = "{%s}" % NS["r"]
RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


_UNSAFE_PATH_RE = re.compile(r"^(/|\\|[A-Za-z]:\\|\.\.)")


def sanitize_relationships(docx_path: str) -> List[str]:
    """Scan all .rels files in the DOCX and fix unsafe Target paths in-place.

    For external hyperlink relationships, strips directory components so only
    the filename remains (e.g. "/tmp/x/doc.docx#bm" → "doc.docx#bm").

    Returns a list of fixes applied (empty = nothing changed).
    """
    fixes: List[str] = []
    if not zipfile.is_zipfile(docx_path):
        return fixes

    tmp = f"tmp_sanitize_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    try:
        with zipfile.ZipFile(docx_path, "r") as z:
            z.extractall(tmp)

        changed = False
        rels_glob = list(Path(tmp).rglob("*.rels"))
        for rels_file in rels_glob:
            try:
                tree = etree.parse(str(rels_file))
            except etree.XMLSyntaxError:
                continue

            for rel in tree.iter():
                if rel.tag and "Relationship" in rel.tag:
                    target = rel.get("Target", "")
                    target_mode = rel.get("TargetMode", "")
                    rel_type = rel.get("Type", "")

                    if target_mode != "External" or "hyperlink" not in rel_type:
                        continue

                    bookmark_part = ""
                    path_part = target
                    if "#" in target:
                        path_part, bookmark_part = target.rsplit("#", 1)
                        bookmark_part = "#" + bookmark_part

                    if _UNSAFE_PATH_RE.match(path_part) or "/" in path_part or "\\" in path_part:
                        clean_name = os.path.basename(path_part)
                        new_target = clean_name + bookmark_part
                        fix_msg = f"{rels_file.name}: {target} → {new_target}"
                        fixes.append(fix_msg)
                        rel.set("Target", new_target)
                        changed = True

            if changed:
                tree.write(str(rels_file), encoding="utf-8", xml_declaration=True)

        if changed:
            with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as zout:
                for root_dir, _dirs, files in os.walk(tmp):
                    for fname in files:
                        full = os.path.join(root_dir, fname)
                        arcname = os.path.relpath(full, tmp)
                        zout.write(full, arcname)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return fixes


def validate_docx(docx_path: str, auto_fix: bool = True) -> Dict:
    errors: List[str] = []
    warnings: List[str] = []

    # 1. ZIP integrity
    if not zipfile.is_zipfile(docx_path):
        return {"valid": False, "errors": ["Not a valid ZIP file"], "warnings": []}

    tmp = f"tmp_validate_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    try:
        with zipfile.ZipFile(docx_path, "r") as z:
            bad = z.testzip()
            if bad:
                errors.append(f"Corrupted ZIP entry: {bad}")
                return {"valid": False, "errors": errors, "warnings": warnings}

            names = z.namelist()

            # 2. [Content_Types].xml
            if "[Content_Types].xml" not in names:
                errors.append("Missing [Content_Types].xml")
            elif names[0] != "[Content_Types].xml":
                warnings.append("[Content_Types].xml should be the first entry in ZIP")

            # 3. document.xml exists
            if "word/document.xml" not in names:
                errors.append("Missing word/document.xml")
                return {"valid": False, "errors": errors, "warnings": warnings}

            z.extractall(tmp)

        # 4. Parse document.xml
        doc_path = Path(tmp) / "word" / "document.xml"
        try:
            tree = etree.parse(str(doc_path))
        except etree.XMLSyntaxError as e:
            errors.append(f"document.xml XML parse error: {e}")
            return {"valid": False, "errors": errors, "warnings": warnings}

        root = tree.getroot()
        nsmap = root.nsmap

        # 4b. Namespace check
        if "w" not in nsmap and None not in nsmap:
            warnings.append("Missing 'w' namespace declaration in document.xml root")

        # 5. <w:hyperlink> must not contain <w:pPr>
        for hl in tree.iter(f"{W_NS}hyperlink"):
            for child in hl:
                if child.tag == f"{W_NS}pPr":
                    parent_p = hl.getparent()
                    p_text = "".join(parent_p.xpath(".//w:t/text()", namespaces=NS)) if parent_p is not None else ""
                    errors.append(
                        f"<w:hyperlink> contains <w:pPr> (WRONG: hyperlink should only wrap <w:r>). "
                        f"Context: '{p_text[:80]}'"
                    )

        # 6. bookmarkStart / bookmarkEnd pairing
        bm_starts = set()
        bm_ends = set()
        for elem in tree.iter():
            if elem.tag == f"{W_NS}bookmarkStart":
                bid = elem.get(f"{W_NS}id")
                if bid:
                    bm_starts.add(bid)
            elif elem.tag == f"{W_NS}bookmarkEnd":
                bid = elem.get(f"{W_NS}id")
                if bid:
                    bm_ends.add(bid)

        orphan_starts = bm_starts - bm_ends
        orphan_ends = bm_ends - bm_starts
        if orphan_starts:
            errors.append(f"bookmarkStart without bookmarkEnd: ids={sorted(orphan_starts)}")
        if orphan_ends:
            warnings.append(f"bookmarkEnd without bookmarkStart: ids={sorted(orphan_ends)}")

        # 7. r:id references vs rels
        rels_path = Path(tmp) / "word" / "_rels" / "document.xml.rels"
        defined_rids = set()
        if rels_path.exists():
            try:
                rels_tree = etree.parse(str(rels_path))
                for rel in rels_tree.iter():
                    rid = rel.get("Id")
                    if rid:
                        defined_rids.add(rid)
            except etree.XMLSyntaxError:
                errors.append("document.xml.rels XML parse error")

        used_rids = set()
        for elem in tree.iter():
            rid = elem.get(f"{R_NS}id")
            if rid:
                used_rids.add(rid)

        missing_rels = used_rids - defined_rids
        if missing_rels:
            errors.append(f"r:id referenced but missing from rels: {sorted(missing_rels)}")

        # 8. <w:t> with leading/trailing spaces missing xml:space="preserve"
        space_issues = 0
        for t_elem in tree.iter(f"{W_NS}t"):
            text = t_elem.text or ""
            if text and (text[0] == " " or text[-1] == " "):
                space_attr = t_elem.get("{http://www.w3.org/XML/1998/namespace}space")
                if space_attr != "preserve":
                    space_issues += 1
        if space_issues > 0:
            warnings.append(f"{space_issues} <w:t> elements with leading/trailing spaces missing xml:space=\"preserve\"")

        result = {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 9. Auto-fix: sanitize unsafe paths in hyperlink relationships
    if auto_fix:
        try:
            fixes = sanitize_relationships(docx_path)
            if fixes:
                result.setdefault("auto_fixed", []).extend(
                    f"path_sanitized: {f}" for f in fixes
                )
        except Exception:
            pass

    return result


def main():
    parser = argparse.ArgumentParser(description="DOCX 后置验证")
    subparsers = parser.add_subparsers(dest="command", required=True)

    v_parser = subparsers.add_parser("validate", help="验证 DOCX 文件")
    v_parser.add_argument("--docx", required=True, help="DOCX 文件路径")

    args = parser.parse_args()

    if args.command == "validate":
        result = validate_docx(args.docx)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["valid"]:
            exit(1)


if __name__ == "__main__":
    main()
