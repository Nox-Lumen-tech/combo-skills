#!/usr/bin/env python3
"""显示 graft-comboagent 当前登录身份。"""
import json
import os
import sys
from pathlib import Path

TOKEN_PATH = Path(
    os.environ.get(
        "GRAFT_COMBOAGENT_TOKEN",
        str(Path.home() / ".config" / "graft-comboagent" / "token.json"),
    )
)


def main() -> None:
    if not TOKEN_PATH.exists():
        print("Not logged in.")
        sys.exit(1)
    try:
        t = json.loads(TOKEN_PATH.read_text())
    except Exception as e:
        sys.exit(f"[ERR] 无法解析 token 文件 {TOKEN_PATH}: {e}")

    email = t.get("email") or "?"
    server = t.get("server") or "?"
    uid = t.get("user_id") or "?"
    uid_short = uid[:8] + "…" if len(uid) > 8 else uid
    print(f"{email} @ {server} (user_id={uid_short})")
    print(f"  token file: {TOKEN_PATH}")


if __name__ == "__main__":
    main()
