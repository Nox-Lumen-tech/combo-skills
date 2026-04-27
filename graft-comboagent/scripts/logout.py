#!/usr/bin/env python3
"""删除 graft-comboagent 本地 token。"""
import os
from pathlib import Path

TOKEN_PATH = Path(
    os.environ.get(
        "GRAFT_COMBOAGENT_TOKEN",
        str(Path.home() / ".config" / "graft-comboagent" / "token.json"),
    )
)


def main() -> None:
    if TOKEN_PATH.exists():
        try:
            TOKEN_PATH.unlink()
            print(f"Removed {TOKEN_PATH}")
        except OSError as e:
            print(f"[ERR] 删除失败: {e}")
            raise SystemExit(1)
    else:
        print("Not logged in.")


if __name__ == "__main__":
    main()
