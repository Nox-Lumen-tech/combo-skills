#!/usr/bin/env python3
"""显示 graft-comboagent 当前登录身份。"""
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

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
    print(f"{email} @ {server}")
    print(f"  user_id / 自己的 tenant_id: {uid}")
    print(f"  token file: {TOKEN_PATH}")
    print("  共享 KB 的 tenant_id 见 list_kbs 每条里的 tenant_id，一般不用手填。")

    if requests and server and t.get("auth_token"):
        try:
            resp = requests.post(
                f"{server.rstrip('/')}/v1/kb/list",
                json={"owner_ids": []},
                headers={"Authorization": t["auth_token"]},
                timeout=30,
            )
            body = resp.json()
            if body.get("code") == 0:
                kbs = (body.get("data") or {}).get("kbs") or []
                if kbs:
                    print(f"  可见 KB: {len(kbs)} 个（list_kbs 可查详情）")
        except Exception:
            pass


if __name__ == "__main__":
    main()
