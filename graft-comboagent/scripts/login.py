#!/usr/bin/env python3
"""graft-comboagent 登录脚本

用法:
    python login.py                              # 交互式输入
    python login.py --server <URL>               # 指定服务器
    python login.py --server <URL> --email <e>   # 预填 email
    GRAFT_COMBOAGENT_SERVER=<URL> python login.py

做的事:
    1. 读 public.pem（和 skill 包同目录）
    2. RSA 加密 password（照搬 api/utils/t_crypt.py::crypt）
    3. POST /v1/user/login → 取 signed_auth_token
    4. 写到 ~/.config/graft-comboagent/token.json (chmod 0600)

环境变量:
    GRAFT_COMBOAGENT_SERVER    默认服务器 URL
    GRAFT_COMBOAGENT_EMAIL     默认 email
    GRAFT_COMBOAGENT_TOKEN     token 文件路径（默认 ~/.config/graft-comboagent/token.json）

依赖:
    pip install requests pycryptodome
"""
import argparse
import base64
import getpass
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("[FATAL] 需要 requests: pip install requests")

try:
    from Cryptodome.Cipher import PKCS1_v1_5 as Cipher_pkcs1_v1_5
    from Cryptodome.PublicKey import RSA
except ImportError:
    try:
        from Crypto.Cipher import PKCS1_v1_5 as Cipher_pkcs1_v1_5
        from Crypto.PublicKey import RSA
    except ImportError:
        sys.exit("[FATAL] 需要 pycryptodome: pip install pycryptodome")


SKILL_DIR = Path(__file__).resolve().parent.parent
PUB_KEY_PATH = SKILL_DIR / "public.pem"
TOKEN_PATH = Path(
    os.environ.get(
        "GRAFT_COMBOAGENT_TOKEN",
        str(Path.home() / ".config" / "graft-comboagent" / "token.json"),
    )
)

# 默认服务器 URL（开发环境）。用户回车即用；--server 或 GRAFT_COMBOAGENT_SERVER 可覆盖。
# 生产上线后把此值换成 prod URL 再发布即可。
DEFAULT_SERVER = "http://ec2-43-203-183-212.ap-northeast-2.compute.amazonaws.com:9222"


def _normalize_server(url: str) -> str:
    """用户可能粘前端页面 URL（带 /combospace/...），这里只保留 scheme + netloc。"""
    from urllib.parse import urlparse
    p = urlparse(url.strip())
    if p.scheme and p.netloc:
        return f"{p.scheme}://{p.netloc}"
    # 无 scheme 当成 host，默认补 http
    return f"http://{url.strip().rstrip('/')}"


def crypt_password(password: str) -> str:
    """照搬 api/utils/t_crypt.py::crypt 的实现。"""
    if not PUB_KEY_PATH.exists():
        sys.exit(
            f"[FATAL] public.pem 不存在: {PUB_KEY_PATH}\n"
            "请从 ragbase 仓库 conf/public.pem 复制到本 skill 目录。"
        )
    rsa_key = RSA.importKey(PUB_KEY_PATH.read_bytes(), "Welcome")
    cipher = Cipher_pkcs1_v1_5.new(rsa_key)
    b64 = base64.b64encode(password.encode("utf-8")).decode("utf-8")
    encrypted = cipher.encrypt(b64.encode())
    return base64.b64encode(encrypted).decode("utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="graft-comboagent login")
    ap.add_argument(
        "--server",
        default=os.environ.get("GRAFT_COMBOAGENT_SERVER"),
        help=f"ragbase 服务器 URL（默认 {DEFAULT_SERVER}）",
    )
    ap.add_argument("--email", default=os.environ.get("GRAFT_COMBOAGENT_EMAIL"))
    ap.add_argument(
        "--password",
        default=None,
        help="(不推荐) 命令行传密码；留空会走 getpass 从 TTY 读",
    )
    ap.add_argument(
        "--insecure",
        action="store_true",
        help="忽略 TLS 校验（仅调试用）",
    )
    args = ap.parse_args()

    if not args.server:
        entered = input(f"ragbase server URL [回车默认: {DEFAULT_SERVER}]: ").strip()
        args.server = entered or DEFAULT_SERVER
    args.server = _normalize_server(args.server)
    if not args.email:
        args.email = input("email: ").strip()
    pwd = args.password or getpass.getpass("password: ")

    if not args.server or not args.email or not pwd:
        sys.exit("[FATAL] server / email / password 都不能为空")

    enc = crypt_password(pwd)
    url = f"{args.server}/v1/user/login"
    try:
        resp = requests.post(
            url,
            json={"email": args.email, "password": enc},
            timeout=15,
            verify=not args.insecure,
        )
    except requests.exceptions.RequestException as e:
        sys.exit(f"[FATAL] 无法连接到 {url}: {e}")

    try:
        body = resp.json()
    except Exception:
        sys.exit(
            f"[FATAL] 非 JSON 响应: HTTP {resp.status_code} {resp.text[:300]}"
        )
    if body.get("code") != 0:
        sys.exit(f"[FATAL] Login failed: {body.get('message', body)}")

    data = body.get("data") or {}
    signed = data.get("signed_auth_token")
    if not signed:
        sys.exit(
            "[FATAL] 服务器没有返回 signed_auth_token。\n"
            "请确认服务端已部署相应改动（api/apps/user_app.py login 端点）。"
        )

    token_doc = {
        "auth_token": signed,
        "server": args.server,
        "email": args.email,
        "user_id": data.get("id") or data.get("user_id"),
    }

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    TOKEN_PATH.write_text(json.dumps(token_doc, ensure_ascii=False, indent=2))
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass

    uid = token_doc.get("user_id") or "?"
    uid_short = uid[:8] + "…" if len(uid) > 8 else uid
    print(f"[OK] Logged in as {args.email} (user={uid_short})")
    print(f"     Token saved to {TOKEN_PATH}")


if __name__ == "__main__":
    main()
