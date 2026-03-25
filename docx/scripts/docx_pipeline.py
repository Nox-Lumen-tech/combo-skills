"""
docx_pipeline.py — 组合层：在 keyword_locator / docx_link_engine 原语之上
提供跨文档批量定位、一键「定位→操作」、双向交叉链接三个通用函数。

所有底层原语仍然完整暴露；pipeline 仅是薄胶水。
Agent 可按需选择调用层级：
  Layer 0: keyword_locator.batch_locate / dle.batch_operations  (最灵活)
  Layer 1: pipeline.locate_and_apply                            (省一步)
  Layer 2: pipeline.bidirectional_link                          (一键完成)

Usage:
    from ragbase_skills.docx import docx_pipeline as pipeline
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Any

from . import keyword_locator
from . import docx_link_engine as dle
from . import docx_validator


# ================================================================
# Layer 1-A: multi_doc_locate
# ================================================================

def multi_doc_locate(
    docs_specs: Dict[str, List[Dict]],
) -> Dict[str, List[Dict]]:
    """跨 N 个文档批量定位关键词。

    Args:
        docs_specs: ``{doc_path: [spec, ...]}``
            每个 spec 与 ``keyword_locator.batch_locate`` 格式一致::

                {"keyword": "FUNC_0028", "context": "", "nearby": "", "para_range": None}

    Returns:
        ``{doc_path: [locator_dict, ...]}`` — 与输入 specs 顺序一一对应。
        每个 locator_dict 即 ``batch_locate`` 的返回，可直接喂给
        ``batch_operations`` 的 ``"locator"`` 字段。

    Example::

        results = pipeline.multi_doc_locate({
            "CHASSIS.docx": [{"keyword": "GAC_ESP配置_01"}, {"keyword": "GAC_IBCS配置_01"}],
            "GAC_multi.docx": [{"keyword": "FUNC_0028"}],
        })
        # results["CHASSIS.docx"][0]["found"] == True
    """
    out: Dict[str, List[Dict]] = {}
    for doc_path, specs in docs_specs.items():
        if not specs:
            out[doc_path] = []
            continue
        out[doc_path] = keyword_locator.batch_locate(doc_path, specs)
    return out


# ================================================================
# Layer 1-B: locate_and_apply
# ================================================================

def locate_and_apply(
    doc: str,
    specs: List[Dict],
    out: str = "",
) -> Dict[str, Any]:
    """定位 + 操作一步完成。

    每个 spec 在 ``batch_locate`` spec 基础上增加操作字段::

        {
            # --- 定位字段（传给 batch_locate）---
            "keyword": "FUNC_0028",
            "context": "",
            "nearby": "",
            "para_range": None,

            # --- 操作字段（传给 batch_operations）---
            "op": "bookmark" | "hyperlink" | "split_hyperlink",
            "bookmark_name": "bm_FUNC_0028",          # bookmark / hyperlink
            "target_doc": "GAC_multi_对比版.docx",     # hyperlink
            "targets": [("GAC.docx", "bm_X"), ...],   # split_hyperlink
        }

    Internal flow:
        1. 提取定位字段 → ``keyword_locator.batch_locate(doc, locate_specs)``
        2. 将定位结果与操作字段合并 → ``dle.batch_operations(doc, operations, out)``

    Returns::

        {
            "locate_results": [locator_dict, ...],   # 定位结果（调试/补救用）
            "apply_results": {bookmarks, hyperlinks, splits, failed, failed_details},
            "not_found": [{"keyword": "...", "spec_index": i}, ...],
        }
    """
    if not out:
        out = doc

    locate_keys = {"keyword", "context", "nearby", "match_mode", "para_range"}
    locate_specs = [{k: v for k, v in s.items() if k in locate_keys} for s in specs]
    locators = keyword_locator.batch_locate(doc, locate_specs)

    operations: List[Dict] = []
    not_found: List[Dict] = []

    for i, (loc, spec) in enumerate(zip(locators, specs)):
        if not loc.get("found"):
            not_found.append({"keyword": spec.get("keyword", ""), "spec_index": i,
                              "error": loc.get("error", "")})
            continue

        op_dict: Dict[str, Any] = {
            "op": spec["op"],
            "locator": loc,
        }
        if spec["op"] == "bookmark":
            op_dict["bookmark_name"] = spec["bookmark_name"]
        elif spec["op"] == "hyperlink":
            op_dict["target_doc"] = spec["target_doc"]
            op_dict["bookmark_name"] = spec["bookmark_name"]
        elif spec["op"] == "split_hyperlink":
            op_dict["targets"] = spec["targets"]

        operations.append(op_dict)

    apply_results: Dict[str, Any]
    if operations:
        apply_results = dle.batch_operations(doc, operations, out)
    else:
        apply_results = {"bookmarks": 0, "hyperlinks": 0, "splits": 0,
                         "failed": 0, "failed_details": []}

    return {
        "locate_results": locators,
        "apply_results": apply_results,
        "not_found": not_found,
    }


# ================================================================
# Layer 2: bidirectional_link
# ================================================================

def bidirectional_link(
    pairs: List[Dict],
    output_dir: str = "",
    validate: bool = True,
) -> Dict[str, Any]:
    """N 对文档双向交叉链接。

    自动完成跨文档链接的完整 4 步流程：
        ① doc_a 建 bookmark → ② doc_b 建 bookmark
        → ③ doc_a 建 hyperlink→doc_b → ④ doc_b 建 hyperlink→doc_a

    Args:
        pairs: 映射表，每项::

            {
                "doc_a": "CHASSIS.docx",
                "doc_b": "GAC_multi.docx",
                "mappings": [
                    {
                        "keyword_a": "GAC_ESP配置制动系统提示_01",
                        "keyword_b": "FUNC_0028",
                        "bookmark_a": "bm_GAC_ESP配置_01",
                        "bookmark_b": "bm_FUNC_0028",
                        "match_type": "many_to_one",
                        # 可选定位辅助
                        "context_a": "", "nearby_a": "", "para_range_a": None,
                        "context_b": "", "nearby_b": "", "para_range_b": None,
                    },
                    ...
                ],
                # 可选：自定义输出路径（默认在 output_dir 下）
                "out_a": "",
                "out_b": "",
            }

        output_dir: 输出目录。如为空则覆盖原文件。
        validate: 是否对输出文件运行 ``docx_validator.validate_docx``。

    Returns::

        {
            "doc_results": {
                "CHASSIS.docx": {
                    "out_path": "...",
                    "bookmarks": N, "hyperlinks": N, "failed": N,
                    "not_found": [...],
                    "validation": {...} | None,
                },
                ...
            },
            "total_bookmarks": N,
            "total_hyperlinks": N,
            "total_failed": N,
        }

    match_type handling:
        - ``"one_to_one"`` / ``"many_to_one"``:
          双方各建 bookmark + hyperlink (op="hyperlink")
        - ``"one_to_many"``:
          doc_b 侧 keyword_b 可能对应多个 doc_a 目标 →
          自动使用 op="split_hyperlink"
    """
    doc_results: Dict[str, Dict[str, Any]] = {}
    totals = {"total_bookmarks": 0, "total_hyperlinks": 0, "total_failed": 0}

    # Group all operations per document: two passes — bookmarks first, then hyperlinks
    # This ensures bookmarks exist before hyperlinks reference them.
    doc_ops: Dict[str, Dict[str, Any]] = {}

    for pair in pairs:
        doc_a = pair["doc_a"]
        doc_b = pair["doc_b"]
        mappings = pair.get("mappings", [])
        out_a = pair.get("out_a", "")
        out_b = pair.get("out_b", "")

        if output_dir:
            if not out_a:
                out_a = os.path.join(output_dir, os.path.basename(doc_a))
            if not out_b:
                out_b = os.path.join(output_dir, os.path.basename(doc_b))

        if doc_a not in doc_ops:
            doc_ops[doc_a] = {"source": doc_a, "out": out_a or doc_a,
                              "bm_specs": [], "link_specs": []}
        if doc_b not in doc_ops:
            doc_ops[doc_b] = {"source": doc_b, "out": out_b or doc_b,
                              "bm_specs": [], "link_specs": []}

        # Collect split_hyperlink targets per (doc, keyword) for one_to_many
        split_targets_b: Dict[str, List[tuple]] = {}

        for m in mappings:
            kw_a = m["keyword_a"]
            kw_b = m["keyword_b"]
            bm_a = m["bookmark_a"]
            bm_b = m["bookmark_b"]
            mt = m.get("match_type", "one_to_one")

            _loc_a = {k.replace("_a", ""): v for k, v in {
                "keyword": kw_a,
                "context": m.get("context_a", ""),
                "nearby": m.get("nearby_a", ""),
                "para_range": m.get("para_range_a"),
            }.items()}
            _loc_b = {k.replace("_b", ""): v for k, v in {
                "keyword": kw_b,
                "context": m.get("context_b", ""),
                "nearby": m.get("nearby_b", ""),
                "para_range": m.get("para_range_b"),
            }.items()}

            # ① doc_a bookmark
            doc_ops[doc_a]["bm_specs"].append({
                **_loc_a, "op": "bookmark", "bookmark_name": bm_a,
            })
            # ② doc_b bookmark
            doc_ops[doc_b]["bm_specs"].append({
                **_loc_b, "op": "bookmark", "bookmark_name": bm_b,
            })

            out_b_name = os.path.basename(doc_ops[doc_b]["out"])
            out_a_name = os.path.basename(doc_ops[doc_a]["out"])

            if mt == "one_to_many":
                # doc_a side: normal hyperlink → doc_b
                doc_ops[doc_a]["link_specs"].append({
                    **_loc_a, "op": "hyperlink",
                    "target_doc": out_b_name, "bookmark_name": bm_b,
                })
                # doc_b side: accumulate targets for split_hyperlink
                key = kw_b
                if key not in split_targets_b:
                    split_targets_b[key] = {"loc": _loc_b, "targets": []}
                split_targets_b[key]["targets"].append((out_a_name, bm_a))
            else:
                # ③ doc_a hyperlink → doc_b#bm_b
                doc_ops[doc_a]["link_specs"].append({
                    **_loc_a, "op": "hyperlink",
                    "target_doc": out_b_name, "bookmark_name": bm_b,
                })
                # ④ doc_b hyperlink → doc_a#bm_a
                doc_ops[doc_b]["link_specs"].append({
                    **_loc_b, "op": "hyperlink",
                    "target_doc": out_a_name, "bookmark_name": bm_a,
                })

        for kw_b, info in split_targets_b.items():
            doc_ops[doc_b]["link_specs"].append({
                **info["loc"], "op": "split_hyperlink",
                "targets": info["targets"],
            })

    # Execute: bookmarks first (pass 1), then hyperlinks (pass 2)
    for doc_path, ops in doc_ops.items():
        source = ops["source"]
        out_path = ops["out"]

        combined_result = {"bookmarks": 0, "hyperlinks": 0, "splits": 0,
                           "failed": 0, "not_found": [], "failed_details": []}

        # Pass 1: bookmarks
        if ops["bm_specs"]:
            bm_result = locate_and_apply(source, ops["bm_specs"], out_path)
            combined_result["bookmarks"] = bm_result["apply_results"].get("bookmarks", 0)
            combined_result["failed"] += bm_result["apply_results"].get("failed", 0)
            combined_result["not_found"].extend(bm_result["not_found"])
            combined_result["failed_details"].extend(
                bm_result["apply_results"].get("failed_details", []))
            # Pass 2 reads from the bookmark-enriched file
            source = out_path

        # Pass 2: hyperlinks
        if ops["link_specs"]:
            link_result = locate_and_apply(source, ops["link_specs"], out_path)
            combined_result["hyperlinks"] = link_result["apply_results"].get("hyperlinks", 0)
            combined_result["splits"] = link_result["apply_results"].get("splits", 0)
            combined_result["failed"] += link_result["apply_results"].get("failed", 0)
            combined_result["not_found"].extend(link_result["not_found"])
            combined_result["failed_details"].extend(
                link_result["apply_results"].get("failed_details", []))

        validation_result = None
        if validate and os.path.isfile(out_path):
            validation_result = docx_validator.validate_docx(out_path)

        doc_results[doc_path] = {
            "out_path": out_path,
            **combined_result,
            "validation": validation_result,
        }
        totals["total_bookmarks"] += combined_result["bookmarks"]
        totals["total_hyperlinks"] += combined_result["hyperlinks"] + combined_result["splits"]
        totals["total_failed"] += combined_result["failed"]

    return {"doc_results": doc_results, **totals}
