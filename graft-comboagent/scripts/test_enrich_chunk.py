#!/usr/bin/env python3
"""Self-check for enrich_chunk.merge_link_text (no pytest)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_chunk import merge_link_text  # noqa: E402


def main() -> None:
    assert merge_link_text("点击查看", "https://x.com") == "点击查看 (https://x.com)"
    assert merge_link_text("已有 https://x.com", "https://x.com") == "已有 https://x.com"
    assert merge_link_text("", "https://x.com") == "https://x.com"
    assert merge_link_text("a", "https://x.com", style="plain") == "a https://x.com"
    print("ok")


if __name__ == "__main__":
    main()
