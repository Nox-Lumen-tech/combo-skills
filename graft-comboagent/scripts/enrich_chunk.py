#!/usr/bin/env python3
"""把 URL 补进 chunk 正文（若尚未出现），供 patch_chunk 使用。

示例:
    python scripts/enrich_chunk.py --text "点击查看" --url "https://example.com"
    python scripts/enrich_chunk.py --text-file chunk.txt --url "https://example.com" --out enriched.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def merge_link_text(text: str, url: str, *, style: str = "paren") -> str:
    """若 url 不在 text 里，追加到正文末尾。"""
    url = (url or "").strip()
    base = (text or "").rstrip()
    if not url:
        return base
    if url in base:
        return base
    if not base:
        return url
    if style == "plain":
        return f"{base} {url}"
    # default: paren — 利于检索且可读
    return f"{base} ({url})"


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge hyperlink URL into chunk text")
    ap.add_argument("--text", default=None)
    ap.add_argument("--text-file", default=None)
    ap.add_argument("--url", required=True)
    ap.add_argument("--style", choices=("paren", "plain"), default="paren")
    ap.add_argument("--out", default=None, help="写入文件；默认 stdout")
    args = ap.parse_args()

    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    elif args.text is not None:
        text = args.text
    else:
        sys.exit("[ERR] 需要 --text 或 --text-file")

    merged = merge_link_text(text, args.url, style=args.style)
    changed = merged != (text or "").rstrip()

    if args.out:
        Path(args.out).write_text(merged, encoding="utf-8")
        print(json.dumps({
            "ok": True,
            "out": args.out,
            "changed": changed,
            "chars": len(merged),
        }, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(merged)


if __name__ == "__main__":
    main()
