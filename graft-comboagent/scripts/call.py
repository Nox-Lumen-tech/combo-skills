#!/usr/bin/env python3
"""graft-comboagent 统一调用入口。

两种模式:
    1. JSON action（list_sessions / get_digest / get_round / search / read_file ...）
       → POST /v1/graft/memory/unified_search
    2. download（特殊 action）
       → GET /v1/graft/memory/download，字节流直接写文件（默认 ./.graft/downloads/）

用法示例:
    call.py list_sessions --query 冷却
    call.py get_digest --session-id 冷却系统分析
    call.py get_round  --session-id 冷却系统分析 --round-id 5
    call.py search     --query "DFMEA 结论" --session-id "*" --source round
    call.py read_file  --path "workspace/sessions/<sid>/output/report.docx"
    call.py download   --path "workspace/sessions/<sid>/output/report.docx"
    call.py download   --path "workspace/sessions/<sid>/output/report.docx" --out ./report.docx
"""
import argparse
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("[FATAL] 需要 requests: pip install requests")


TOKEN_PATH = Path(
    os.environ.get(
        "GRAFT_COMBOAGENT_TOKEN",
        str(Path.home() / ".config" / "graft-comboagent" / "token.json"),
    )
)
DEFAULT_DL_DIR = Path(
    os.environ.get(
        "GRAFT_COMBOAGENT_DL_DIR",
        str(Path.cwd() / ".graft" / "downloads"),
    )
)

# 参数映射：脚本友好 CLI flag → unified_search 字段名
_ARG_ALIAS = {
    "session_id": ["--session-id", "--sid"],
    "round_id":   ["--round-id"],
    "end_round":  ["--end-round"],
    "max_tokens": ["--max-tokens"],
    "line_start": ["--line-start"],
    "line_end":   ["--line-end"],
    "source":     ["--source"],
    "path":       ["--path"],
    "offset":     ["--offset"],
    "limit":      ["--limit"],
    "top_k":      ["--top-k"],
    "query":      ["--query", "-q"],
    "kb_ids":     ["--kb-ids"],
    "doc_ids":    ["--doc-ids"],
    "epoch":      ["--epoch"],
    "run":        ["--run"],
}
_INT_FIELDS = {
    "round_id", "end_round", "max_tokens", "line_start", "line_end",
    "offset", "limit", "top_k", "epoch", "run",
}
_LIST_FIELDS = {"kb_ids", "doc_ids"}


def load_token() -> dict:
    if not TOKEN_PATH.exists():
        sys.exit("[ERR] 未登录。请先运行: python scripts/login.py")
    try:
        return json.loads(TOKEN_PATH.read_text())
    except Exception as e:
        sys.exit(f"[ERR] 无法解析 token 文件 {TOKEN_PATH}: {e}")


def do_download(args, tok: dict) -> None:
    if not args.path:
        sys.exit("[ERR] download 需要 --path")

    params = {"path": args.path}
    if args.session_id:
        params["session_id"] = args.session_id
    if args.filename:
        params["filename"] = args.filename

    out_path = Path(args.out) if args.out else (
        DEFAULT_DL_DIR / args.path.rsplit("/", 1)[-1]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        resp = requests.get(
            f"{tok['server']}/v1/graft/memory/download",
            params=params,
            headers={"Authorization": tok["auth_token"]},
            stream=True,
            timeout=300,
            verify=not args.insecure,
        )
    except requests.exceptions.RequestException as e:
        sys.exit(f"[ERR] 请求失败: {e}")

    if resp.status_code == 401:
        sys.exit("[ERR] 认证失效，请重新运行: python scripts/login.py")

    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "application/json" in ctype:
        try:
            body = resp.json()
        except Exception:
            sys.exit(f"[ERR] HTTP {resp.status_code}: {resp.text[:300]}")
        sys.exit(f"[ERR] {body.get('message', body)}")

    if resp.status_code != 200:
        sys.exit(f"[ERR] HTTP {resp.status_code}: {resp.text[:300]}")

    total = 0
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
                total += len(chunk)

    print(json.dumps({
        "ok": True,
        "saved_to": str(out_path),
        "bytes": total,
        "source": args.path,
    }, ensure_ascii=False, indent=2))


def do_unified(args, tok: dict) -> None:
    body: dict = {"action": args.action}
    for field in _ARG_ALIAS:
        v = getattr(args, field, None)
        if v is None:
            continue
        # read_file 的 unified_search 签名用 query 表达路径，我们用 --path 传进来
        if args.action == "read_file" and field == "path":
            body["query"] = v
            continue
        if field in _LIST_FIELDS and isinstance(v, str):
            items = [x.strip() for x in v.split(",") if x.strip()]
            body[field] = ",".join(items)  # unified_search 接受逗号分隔的字符串
            continue
        if field in _INT_FIELDS:
            try:
                body[field] = int(v)
            except ValueError:
                sys.exit(f"[ERR] {field} 需要整数: {v!r}")
            continue
        body[field] = v

    try:
        resp = requests.post(
            f"{tok['server']}/v1/graft/memory/unified_search",
            json=body,
            headers={"Authorization": tok["auth_token"]},
            timeout=120,
            verify=not args.insecure,
        )
    except requests.exceptions.RequestException as e:
        sys.exit(f"[ERR] 请求失败: {e}")

    if resp.status_code == 401:
        sys.exit("[ERR] 认证失效，请重新运行: python scripts/login.py")
    try:
        data = resp.json()
    except Exception:
        sys.exit(f"[ERR] 非 JSON 响应: HTTP {resp.status_code} {resp.text[:300]}")
    if data.get("code") != 0:
        sys.exit(f"[ERR] {data.get('message', data)}")

    payload = data.get("data")
    indent = None if args.raw else 2
    print(json.dumps(payload, ensure_ascii=False, indent=indent))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="graft-comboagent 调用入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "action",
        help="list_sessions | get_digest | get_round | search | "
             "search_by_artifact | read_file | list_files | grep_file | "
             "list_documents | get_doc_profile | list_chunks | download",
    )
    for field, flags in _ARG_ALIAS.items():
        ap.add_argument(*flags, dest=field, default=None)
    ap.add_argument("--filename", default=None,
                    help="download: HTTP 附件名；默认 path basename")
    ap.add_argument("--out", default=None,
                    help="download: 本地落盘路径；默认 .graft/downloads/<basename>")
    ap.add_argument("--raw", action="store_true",
                    help="JSON 输出不 pretty-print")
    ap.add_argument("--insecure", action="store_true",
                    help="忽略 TLS 校验（仅调试）")
    args = ap.parse_args()

    tok = load_token()
    if not tok.get("server") or not tok.get("auth_token"):
        sys.exit(f"[ERR] token 文件字段不完整: {TOKEN_PATH}")

    if args.action == "download":
        do_download(args, tok)
    else:
        do_unified(args, tok)


if __name__ == "__main__":
    main()
