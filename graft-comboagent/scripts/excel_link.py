#!/usr/bin/env python3
"""从 Excel 单元格抽取超链接 URL（本地后处理 graft patch 用）。

依赖 openpyxl（ragbase 环境通常已装）。

示例:
    python scripts/excel_link.py --file ./.graft/downloads/report.xlsx --sheet Sheet1 --cell B5
    python scripts/excel_link.py --file report.xlsx --scan-sheet Sheet1
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_HYPERLINK_RE = re.compile(r"""=HYPERLINK\(\s*"([^"]+)"\s*,""", re.IGNORECASE)


def _cell_url(cell) -> str | None:
    link = getattr(cell, "hyperlink", None)
    if link is not None:
        target = getattr(link, "target", None)
        if target:
            return str(target).strip()
    val = cell.value
    if isinstance(val, str):
        m = _HYPERLINK_RE.match(val.strip())
        if m:
            return m.group(1).strip()
    return None


def _cell_display(cell) -> str:
    val = cell.value
    if val is None:
        return ""
    if isinstance(val, str) and val.strip().upper().startswith("=HYPERLINK("):
        m = re.match(r"""=HYPERLINK\(\s*"[^"]+"\s*,\s*"([^"]*)""" , val.strip(), re.I)
        if m:
            return m.group(1)
    return str(val)


def main() -> None:
    try:
        from openpyxl import load_workbook
    except ImportError:
        sys.exit("[FATAL] 需要 openpyxl: pip install openpyxl")

    ap = argparse.ArgumentParser(description="Extract hyperlink URL(s) from xlsx")
    ap.add_argument("--file", required=True, help="本地 xlsx 路径")
    ap.add_argument("--sheet", default=None, help="工作表名（默认 active sheet）")
    ap.add_argument("--cell", default=None, help="单元格坐标，如 B5")
    ap.add_argument("--scan-sheet", action="store_true",
                    help="扫描整张 sheet 所有含链接的单元格")
    ap.add_argument("--data-only", action="store_true", default=True,
                    help="load_workbook(data_only=True)，默认开")
    ap.add_argument("--no-data-only", dest="data_only", action="store_false")
    args = ap.parse_args()

    path = Path(args.file).expanduser()
    if not path.is_file():
        sys.exit(f"[ERR] 文件不存在: {path}")

    wb = load_workbook(path, data_only=args.data_only, read_only=False)
    try:
        if args.cell:
            ws = wb[args.sheet] if args.sheet else wb.active
            cell = ws[args.cell]
            url = _cell_url(cell)
            out = {
                "ok": bool(url),
                "file": str(path),
                "sheet": ws.title,
                "cell": args.cell,
                "display": _cell_display(cell),
                "url": url,
            }
            print(json.dumps(out, ensure_ascii=False, indent=2))
            if not url:
                sys.exit(1)
            return

        if args.scan_sheet:
            sheet_name = args.sheet or wb.sheetnames[0]
            ws = wb[sheet_name]
            hits = []
            for row in ws.iter_rows():
                for cell in row:
                    url = _cell_url(cell)
                    if url:
                        hits.append({
                            "cell": cell.coordinate,
                            "display": _cell_display(cell),
                            "url": url,
                        })
            print(json.dumps({
                "ok": True,
                "file": str(path),
                "sheet": sheet_name,
                "count": len(hits),
                "links": hits,
            }, ensure_ascii=False, indent=2))
            return

        sys.exit("[ERR] 需要 --cell 或 --scan-sheet")
    finally:
        wb.close()


if __name__ == "__main__":
    main()
