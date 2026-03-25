#!/usr/bin/env python3
"""
keyword_locator.py - DOCX 关键词定位

支持 body 段落和表格内段落的搜索。
优先搜索 body 段落（与 ES para_start_int 索引对齐）；
若 body 中未找到，自动 fallback 搜索表格单元格内的段落。

用法:
    python keyword_locator.py locate --docx input.docx --keyword "FUNC_0092" --nearby "换挡"
    
    # 返回（body 段落命中）
    {"found": true, "paragraph_idx": 47, "run_idx": 3, "in_table": false, "context": "..."}
    
    # 返回（表格命中）
    {"found": true, "in_table": true, "table_idx": 2, "row_idx": 5, "cell_idx": 1,
     "cell_para_idx": 0, "context": "..."}
"""

from __future__ import annotations

import argparse
import json
import zipfile
import shutil
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from lxml import etree

# Word OOXML Namespaces
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}
W_NS = "{%s}" % NS["w"]


def unzip_docx(docx_path: str, tmp_dir: str) -> None:
    with zipfile.ZipFile(docx_path, 'r') as zip_ref:
        zip_ref.extractall(tmp_dir)


def load_document_xml(tmp_dir: str) -> etree._ElementTree:
    xml_path = Path(tmp_dir) / "word" / "document.xml"
    return etree.parse(str(xml_path))


def get_paragraphs(tree: etree._ElementTree) -> List[Tuple[int, etree._Element]]:
    """获取 body 下的顶层段落（不含表格内），索引与 ES para_start_int 对齐"""
    paragraphs = []
    body = tree.find(f".//{W_NS}body", NS)
    if body is None:
        return paragraphs
    
    para_idx = 0
    for child in body:
        if child.tag == f"{W_NS}p":
            paragraphs.append((para_idx, child))
            para_idx += 1
    return paragraphs


def get_table_paragraphs(tree: etree._ElementTree) -> List[Dict]:
    """获取表格内的所有段落，返回带位置元数据的列表。

    返回格式: [{"para": <w:p element>, "table_idx": int, "row_idx": int,
                 "cell_idx": int, "cell_para_idx": int}, ...]
    """
    body = tree.find(f".//{W_NS}body", NS)
    if body is None:
        return []
    results = []
    table_idx = 0
    for child in body:
        if child.tag != f"{W_NS}tbl":
            continue
        rows = child.findall(f"{W_NS}tr")
        for r_idx, row in enumerate(rows):
            cells = row.findall(f"{W_NS}tc")
            for c_idx, cell in enumerate(cells):
                paras = cell.findall(f"{W_NS}p")
                for p_idx, para in enumerate(paras):
                    results.append({
                        "para": para,
                        "table_idx": table_idx,
                        "row_idx": r_idx,
                        "cell_idx": c_idx,
                        "cell_para_idx": p_idx,
                    })
        table_idx += 1
    return results


def get_run_text(run: etree._Element) -> str:
    return "".join(run.xpath(".//w:t/text()", namespaces=NS))


def get_paragraph_text(paragraph: etree._Element) -> str:
    return "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))


def _find_run_in_para(para: etree._Element, keyword: str, match_mode: str) -> Dict:
    """在段落内查找包含 keyword 的 run，返回匹配信息。"""
    para_text = get_paragraph_text(para)
    if match_mode == "paragraph":
        return {"run_idx": -1, "context": para_text[:200]}

    run_idx = 0
    for child in para:
        if child.tag == f"{W_NS}r":
            run_text = get_run_text(child)
            if keyword in run_text:
                return {"run_idx": run_idx, "text": run_text, "context": para_text[:200]}
            run_idx += 1
        elif child.tag == f"{W_NS}ins":
            for sub in child:
                if sub.tag == f"{W_NS}r":
                    run_text = get_run_text(sub)
                    if keyword in run_text:
                        return {
                            "run_idx": run_idx, "text": run_text,
                            "context": para_text[:200], "inside_ins": True,
                        }
                    run_idx += 1

    return {"run_idx": -1, "context": para_text[:200]}


def _search_body_paragraphs(paragraphs, keyword, nearby, para_range, match_mode,
                            context=""):
    """在 body 段落中搜索关键词。"""
    candidates = []
    for para_idx, para in paragraphs:
        if para_range and not (para_range[0] <= para_idx <= para_range[1]):
            continue
        para_text = get_paragraph_text(para)
        if keyword not in para_text:
            continue
        if context and context not in para_text:
            continue
        if nearby:
            found_nearby = False
            for i in range(max(0, para_idx - 2), min(len(paragraphs), para_idx + 3)):
                if nearby in get_paragraph_text(paragraphs[i][1]):
                    found_nearby = True
                    break
            if not found_nearby:
                continue
        run_info = _find_run_in_para(para, keyword, match_mode)
        candidates.append({"paragraph_idx": para_idx, "in_table": False, **run_info})
    return candidates


def _search_table_paragraphs(table_paras, keyword, nearby, match_mode,
                             context=""):
    """在表格段落中搜索关键词。nearby 在同表格±3行内匹配。"""
    candidates = []
    for tp in table_paras:
        para = tp["para"]
        para_text = get_paragraph_text(para)
        if keyword not in para_text:
            continue
        if context and context not in para_text:
            continue
        if nearby:
            found_nearby = False
            for tp2 in table_paras:
                if tp2["table_idx"] != tp["table_idx"]:
                    continue
                if abs(tp2["row_idx"] - tp["row_idx"]) <= 3:
                    if nearby in get_paragraph_text(tp2["para"]):
                        found_nearby = True
                        break
            if not found_nearby:
                continue
        run_info = _find_run_in_para(para, keyword, match_mode)
        candidates.append({
            "paragraph_idx": -1,
            "in_table": True,
            "table_idx": tp["table_idx"],
            "row_idx": tp["row_idx"],
            "cell_idx": tp["cell_idx"],
            "cell_para_idx": tp["cell_para_idx"],
            **run_info,
        })
    return candidates


def _format_result(candidates, keyword, para_range=None):
    """将候选列表格式化为返回 dict。"""
    if not candidates:
        range_hint = f" (para_range={para_range})" if para_range else ""
        return {"found": False, "keyword": keyword,
                "error": f"未找到 '{keyword}'{range_hint}（已搜索 body 段落和表格）"}

    if len(candidates) == 1:
        return {"found": True, "keyword": keyword, **candidates[0]}

    summary_keys = ("paragraph_idx", "in_table", "table_idx", "row_idx", "cell_idx", "context")
    return {
        "found": True,
        "keyword": keyword,
        **candidates[0],
        "warning": f"找到 {len(candidates)} 处匹配，已选择第一个。建议提供更精确的 nearby 文本。",
        "all_matches": [
            {k: v for k, v in c.items() if k in summary_keys}
            for c in candidates[:5]
        ],
    }


def locate_keyword(
    docx_path: str,
    keyword: str,
    nearby: str = "",
    match_mode: str = "run",
    para_range: Optional[tuple] = None,
    context: str = "",
) -> Dict:
    """
    定位关键词。优先搜索 body 段落，未找到时自动 fallback 搜索表格。
    
    Args:
        docx_path: DOCX 文件路径
        keyword: 要定位的关键词
        nearby: 附近确认文本（body: 相邻段落; 表格: 同表±3行）
        match_mode: "run" 精确到 run / "paragraph" 段落级
        para_range: (start, end) body 段落索引范围（仅对 body 段落生效）
        context: 同段落上下文验证串。keyword 所在段落的文本必须同时包含
                 此字符串，用于在 keyword 出现多次时精确消歧。
                 推荐用法：从 chunk content 中截取 keyword 前后各 10-15
                 字拼成的子串（如 ``"告警与指示灯_FUNC_0103"``）。
    
    Returns:
        body 段落命中:
            {"found": True, "paragraph_idx": int, "run_idx": int, "in_table": False, ...}
        表格命中:
            {"found": True, "in_table": True, "table_idx": int, "row_idx": int,
             "cell_idx": int, "cell_para_idx": int, ...}
        未找到:
            {"found": False, "error": "..."}
    """
    tmp = f"tmp_locator_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    
    try:
        unzip_docx(docx_path, tmp)
        tree = load_document_xml(tmp)
        
        body_paras = get_paragraphs(tree)
        candidates = _search_body_paragraphs(
            body_paras, keyword, nearby, para_range, match_mode, context)
        
        if not candidates:
            table_paras = get_table_paragraphs(tree)
            candidates = _search_table_paragraphs(
                table_paras, keyword, nearby, match_mode, context)
        
        return _format_result(candidates, keyword, para_range)
    
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def batch_locate(docx_path: str, specs: List[Dict]) -> List[Dict]:
    """批量定位（单次解压，性能优于逐个调用 locate_keyword）。

    specs 格式::

        [
            {
                "keyword": "FUNC_0103",
                "context": "告警与指示灯_FUNC_0103",   # 同段落上下文消歧
                "nearby": "",                             # ±3 段落/行消歧
                "match_mode": "run",
                "para_range": [120, 150],                 # 可选，不推荐
            },
            ...
        ]
    """
    tmp = f"tmp_locator_{uuid.uuid4().hex}"
    Path(tmp).mkdir(exist_ok=True)
    try:
        unzip_docx(docx_path, tmp)
        tree = load_document_xml(tmp)
        body_paras = get_paragraphs(tree)
        table_paras = None

        results = []
        for s in specs:
            keyword = s["keyword"]
            ctx = s.get("context", "")
            nearby = s.get("nearby", "")
            match_mode = s.get("match_mode", "run")
            pr = s.get("para_range")
            if pr and isinstance(pr, (list, tuple)) and len(pr) == 2:
                pr = (int(pr[0]), int(pr[1]))
            else:
                pr = None

            candidates = _search_body_paragraphs(
                body_paras, keyword, nearby, pr, match_mode, ctx)

            if not candidates:
                if table_paras is None:
                    table_paras = get_table_paragraphs(tree)
                candidates = _search_table_paragraphs(
                    table_paras, keyword, nearby, match_mode, ctx)

            results.append(_format_result(candidates, keyword, pr))
        return results
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="DOCX 关键词定位")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # locate
    locate_parser = subparsers.add_parser("locate", help="定位关键词")
    locate_parser.add_argument("--docx", required=True, help="DOCX 文件")
    locate_parser.add_argument("--keyword", required=True, help="要定位的关键词")
    locate_parser.add_argument("--nearby", default="", help="附近确认文本")
    locate_parser.add_argument("--match-mode", default="run", choices=["run", "paragraph"])
    locate_parser.add_argument("--para-range", default=None,
                               help="段落范围 start,end（如 120,150）限定搜索区域")
    
    # batch
    batch_parser = subparsers.add_parser("batch", help="批量定位")
    batch_parser.add_argument("--docx", required=True)
    batch_parser.add_argument("--specs", required=True, help='JSON: [{"keyword": "30", "nearby": "违约"}]')
    
    args = parser.parse_args()
    
    if args.command == "locate":
        pr = None
        if args.para_range:
            parts = args.para_range.split(",")
            pr = (int(parts[0]), int(parts[1]))
        result = locate_keyword(args.docx, args.keyword, args.nearby, args.match_mode, para_range=pr)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        specs = json.loads(args.specs)
        results = batch_locate(args.docx, specs)
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
