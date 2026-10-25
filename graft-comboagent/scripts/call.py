#!/usr/bin/env python3
"""graft-comboagent 统一调用入口。

七种模式:
    1. JSON action（list_sessions / get_digest / get_round / search / read_file ...）
       → POST /v1/graft/memory/unified_search                   [只读]
    2. download（特殊 action）
       → GET /v1/graft/memory/download，字节流直接写文件         [只读]
    3. list_kbs（KB 发现）
       → POST /v1/kb/list                                      [只读]
    4. kb_detail（KB 详情）
       → GET /v1/kb/detail?kb_id=<id>                          [只读]
    5. dispatch_task（派发任务给已有 session）
       → POST /v1/graft/dispatch_task                          [写：异步触发]
    6. upload（把本地文件灌进云端 KB，可选触发解析）
       → POST /v1/document/upload （+ 可选 POST /v1/document/run） [写：入库]
    7. install_skill（把本地 skill 目录装进云端个人技能库）
       → POST /v1/skills/install_bundle（zip 上传，git 可选）     [写：装技能]

⚠️ 写边界很窄：本 skill 只有三个写动作 —— dispatch_task（向**已存在**的 session
排队一次执行，不创建/删除资源）、upload（把本地文件上传到指定 KB，可选触发解析）
和 install_skill（把本地 skill 目录打包上传到**本人**技能库）。除此之外不提供
delete / remove / save / create / update 类命令，即使后端 token 技术上能调那些端点。
upload 复用平台现成的 /v1/document/upload（@login_required，与云端 agent 的 kb_upload
走同一端点）；install_skill 复用 /v1/skills/install_bundle，服务端走 Layer-8 安全校验
后只写进 skills/users/<本人 uid>/，不碰他人/ builtin。本地侧把 upload 的
content_hash → local_path 记到 .graft/uploads/manifest.jsonl，便于召回时跳回原文。

用法示例:
    call.py list_sessions --query 冷却
    call.py get_digest --session-id 冷却系统分析
    call.py get_round  --session-id 冷却系统分析 --round-id 5
    call.py search     --query "DFMEA 结论" --session-id "*" --source round
    call.py read_file  --path "workspace/sessions/<sid>/output/report.docx"
    call.py download   --path "workspace/sessions/<sid>/output/report.docx"
    call.py download   --path "workspace/sessions/<sid>/output/report.docx" --out ./report.docx
    # KB 检索（独立于 session，不需要云端有 session 跑过）：
    call.py list_kbs                              # 我有哪些 KB
    call.py list_kbs --keywords ASPICE            # 按名字搜
    call.py kb_detail --kb-id <kb_id>             # KB 详情
    call.py search --source document --query "传感器精度要求" --kb-ids <kb_id>
    call.py list_documents --kb-ids <kb_id>       # 列 KB 里的所有文档
    call.py list_chunks --doc-ids <doc_id>        # 翻一份文档的 chunks
    # 派发任务（异步，立即返回；用 get_round 轮询进度）：
    call.py dispatch_task --session-id <sid> --prompt "请把附件文档总结成中文要点"
    # 上传本地文件到 KB（默认只上传不解析；要入库检索加 --parse）：
    call.py upload --kb-id <kb_id> --file ./缺陷分析.md
    call.py upload --kb-id <kb_id> --file a.docx --file b.xlsx --parse
    call.py upload --kb-id <kb_id> --dir ./findings --glob "*.md" --parse
    # 安装本地 skill 目录到云端个人技能库（目录名须等于 skill 名，目录内含 SKILL.md）：
    call.py install_skill --skill-path ./my-skill
    call.py install_skill --skill-path ./my-skill --overwrite
    # KB chunk 修补（不改 parse；patch 时云端 re-embed）：
    call.py download_document --doc-id <doc_id> [--out ./local.xlsx]
    call.py list_doc_chunks --doc-id <doc_id>
    call.py patch_chunk --doc-id <id> --chunk-id <id> --content "补全后的正文"
    call.py create_chunk --doc-id <id> --content "..."
    call.py delete_chunks --doc-id <id> --chunk-ids id1,id2
"""
import argparse
import hashlib
import io
import json
import mimetypes
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
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
# 本地上传清单：content_hash(sha256) → local_path 映射（M4 架构边界：云端零知情，
# 本地自己存映射，便于召回时把云端 chunk 跳回本地原文）。append-only JSONL。
UPLOAD_MANIFEST_PATH = Path(
    os.environ.get(
        "GRAFT_COMBOAGENT_UPLOAD_MANIFEST",
        str(Path.cwd() / ".graft" / "uploads" / "manifest.jsonl"),
    )
)
# 单文件上传上限（与 download 一致）：防误把超大文件塞爆带宽/KB。
# 真正的大批量入库走前端 KB 或云端 Source SKILL。
_MAX_UPLOAD = 200 * 1024 * 1024

# 参数映射：脚本友好 CLI flag → unified_search 字段名
# 与 AgentFlow/src/memory/memory_os.py::create_tool() 的 unified_search 签名对齐
_ARG_ALIAS = {
    # ── 通用 ──
    "session_id": ["--session-id", "--sid"],
    "query":      ["--query", "-q"],
    "source":     ["--source"],
    "path":       ["--path"],
    # ── 分页 / 限额 ──
    "offset":     ["--offset"],
    "limit":      ["--limit"],
    "top_k":      ["--top-k"],
    "max_tokens": ["--max-tokens"],
    # ── round / epoch / run ──
    "round_id":   ["--round-id"],
    "end_round":  ["--end-round"],
    "epoch":      ["--epoch"],
    "run":        ["--run"],
    # ── KB / doc / chunk ──
    "kb_ids":     ["--kb-ids"],
    "doc_ids":    ["--doc-ids"],
    "doc_id":     ["--doc-id"],
    "chunk_ids":  ["--chunk-ids"],
    "chunk_id":   ["--chunk-id"],
    "window":     ["--window"],
    # ── read_file 行模式 ──
    "line_start": ["--line-start"],
    "line_end":   ["--line-end"],
    "center_line":   ["--center-line"],
    "context_lines": ["--context-lines"],
    # ── read_file 内文搜索模式 ──
    "find":            ["--find"],
    "find_context":    ["--find-context"],
    "max_find_matches": ["--max-find-matches"],
    # ── search 过滤器 ──
    "time_start": ["--time-start"],
    "time_end":   ["--time-end"],
    "speaker":    ["--speaker"],
    "chat_id":    ["--chat-id"],
    # ── KB 发现（list_kbs / kb_detail 用）──
    "kb_id":      ["--kb-id"],
    "keywords":   ["--keywords"],
    "page":       ["--page"],
    "page_size":  ["--page-size"],
    "orderby":    ["--orderby"],
    # ── dispatch_task 用 ──
    "prompt":     ["--prompt", "-p"],
}
_INT_FIELDS = {
    "round_id", "end_round", "max_tokens", "line_start", "line_end",
    "center_line", "context_lines",
    "find_context", "max_find_matches",
    "offset", "limit", "top_k", "epoch", "run", "window",
    "page", "page_size",
}
_LIST_FIELDS = {"kb_ids", "doc_ids", "chunk_ids"}


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


def _api_json(method: str, path: str, tok: dict, *, json_body=None, params=None, insecure=False):
    """HTTP 调 ragbase JSON API；401/非 0 code 直接 sys.exit。"""
    url = f"{tok['server'].rstrip('/')}{path}"
    headers = {"Authorization": tok["auth_token"]}
    try:
        resp = requests.request(
            method, url, json=json_body, params=params,
            headers=headers, timeout=120, verify=not insecure,
        )
    except requests.exceptions.RequestException as e:
        sys.exit(f"[ERR] 请求失败: {e}")
    if resp.status_code == 401:
        sys.exit("[ERR] 认证失效，请重新运行: python scripts/login.py")
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "application/json" not in ctype:
        sys.exit(f"[ERR] 非 JSON 响应: HTTP {resp.status_code} {resp.text[:300]}")
    try:
        data = resp.json()
    except Exception:
        sys.exit(f"[ERR] JSON 解析失败: HTTP {resp.status_code} {resp.text[:300]}")
    if data.get("code") != 0:
        sys.exit(f"[ERR] {data.get('message', data)}")
    return data.get("data")


def _read_content_arg(args) -> str:
    if getattr(args, "content_file", None):
        p = Path(args.content_file).expanduser()
        if not p.is_file():
            sys.exit(f"[ERR] --content-file 不是文件: {p}")
        return p.read_text(encoding="utf-8")
    if getattr(args, "content", None) is not None:
        return args.content
    sys.exit("[ERR] 需要 --content 或 --content-file")


def _resolve_doc_filename(doc_id: str, tok: dict, insecure: bool = False) -> str:
    """从 /v1/chunk/list 拿 doc 元信息里的文件名（轻量）。"""
    try:
        doc = _api_json(
            "POST", "/v1/chunk/list", tok,
            json_body={"doc_id": doc_id, "page": 1, "size": 1},
            insecure=insecure,
        ).get("doc") or {}
        name = doc.get("name") or doc.get("doc_name") or ""
        return name if isinstance(name, str) else ""
    except SystemExit:
        return ""


def do_download_document(args, tok: dict) -> None:
    """下载 KB 文档原始字节（xlsx/docx/pdf…）。

    走 /v1/document/get/<doc_id>，与前端 KB 页「下载」同源。
    """
    doc_id = args.doc_id
    if not doc_id and args.doc_ids:
        parts = [x.strip() for x in str(args.doc_ids).split(",") if x.strip()]
        doc_id = parts[0] if parts else None
    if not doc_id:
        sys.exit("[ERR] download_document 需要 --doc-id（或 --doc-ids 取第一个）")

    url = f"{tok['server'].rstrip('/')}/v1/document/get/{doc_id}"
    try:
        resp = requests.get(
            url,
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

    fname = args.filename or _resolve_doc_filename(doc_id, tok, insecure=args.insecure) or doc_id
    out_path = Path(args.out) if args.out else (DEFAULT_DL_DIR / fname)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
                total += len(chunk)

    out = {
        "ok": True,
        "action": "download_document",
        "doc_id": doc_id,
        "saved_to": str(out_path),
        "bytes": total,
        "hint": "本地 openpyxl 抽链接: python scripts/excel_link.py --file <path> --cell B5",
    }
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def _resolve_doc_id(args) -> str | None:
    doc_id = getattr(args, "doc_id", None)
    if not doc_id and getattr(args, "doc_ids", None):
        parts = _split_csv_ids(args.doc_ids)
        doc_id = parts[0] if parts else None
    return doc_id or None


def _fetch_doc_chunks_page(
    tok: dict, doc_id: str, *, page: int, size: int, keywords: str = "", insecure: bool = False,
) -> dict:
    body = {"doc_id": doc_id, "page": page, "size": size}
    if keywords:
        body["keywords"] = keywords
    return _api_json("POST", "/v1/chunk/list", tok, json_body=body, insecure=insecure)


def _fetch_doc_chunks_all(
    tok: dict, doc_id: str, *, keywords: str = "", page_size: int = 100, insecure: bool = False,
) -> tuple[list, dict | None, int]:
    """按文档顺序拉全量 chunks（/v1/chunk/list 分页），team 共享库可用。"""
    page_size = max(1, min(int(page_size), 200))
    all_chunks: list = []
    doc_meta = None
    total = 0
    page = 1
    while page <= 100:
        data = _fetch_doc_chunks_page(
            tok, doc_id, page=page, size=page_size, keywords=keywords, insecure=insecure,
        )
        batch = data.get("chunks") or []
        if doc_meta is None:
            doc_meta = data.get("doc")
        total = int(data.get("total") or total or len(batch))
        if not batch:
            break
        all_chunks.extend(batch)
        if len(all_chunks) >= total:
            break
        page += 1
    return all_chunks, doc_meta, total


def _chunk_list_items(chunks: list, *, target_ids: set | None = None) -> tuple[list, list]:
    """graft list_chunks 兼容输出：metadata.items + content.items。"""
    metadata_items, content_items = [], []
    for c in chunks:
        cid = c.get("chunk_id") or c.get("id") or ""
        text = c.get("content_with_weight") or c.get("content") or ""
        meta = {
            "chunk_id": cid,
            "doc_type": c.get("doc_type_kwd") or "text",
            "token_estimate": max(1, len(text) // 4),
        }
        positions = c.get("positions") or c.get("position_int") or []
        if positions:
            meta["page_num"] = positions[0][0] if isinstance(positions[0], list) else positions[0]
        img_id = c.get("image_id") or c.get("img_id") or ""
        if img_id:
            meta["image_url"] = f"/v1/document/image/{img_id}"
        if target_ids and cid in target_ids:
            meta["is_target"] = True
        metadata_items.append(meta)
        content_items.append({"chunk_id": cid, "text": text})
    return metadata_items, content_items


def do_list_doc_chunks(args, tok: dict) -> None:
    """列某 KB 文档的 chunk（含 content_with_weight，可分页）。

    走 /v1/chunk/list（前端 KB chunk 页同源），比 unified_search list_chunks
    更适合 patch 前读取现有正文。
    """
    doc_id = _resolve_doc_id(args)
    if not doc_id:
        sys.exit("[ERR] list_doc_chunks 需要 --doc-id")

    page = int(args.page or 1)
    size = int(args.page_size or args.limit or 30)
    keywords = (args.query or "").strip()
    data = _fetch_doc_chunks_page(tok, doc_id, page=page, size=size, keywords=keywords, insecure=args.insecure)
    out = {
        "ok": True,
        "action": "list_doc_chunks",
        "doc_id": doc_id,
        "total": data.get("total", 0),
        "page": page,
        "size": size,
        "doc": data.get("doc"),
        "chunks": data.get("chunks", []),
        "via": "native:/v1/chunk/list",
        "hint": (
            "改某条: patch_chunk --doc-id <id> --chunk-id <chunk_id> --content '...'"
        ),
    }
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def do_list_chunks_native(args, tok: dict) -> None:
    """KB 文档 list_chunks — 走 /v1/chunk/list + /v1/chunk/get，不经 graft MemoryOS。

    与 unified_search list_chunks 输出格式兼容（metadata + content），team 共享库可用。
    """
    chunk_ids = _split_csv_ids(getattr(args, "chunk_ids", None))
    window = max(0, int(getattr(args, "window", None) or 0))
    limit = max(0, int(getattr(args, "limit", None) or 0))
    offset = max(0, int(getattr(args, "offset", None) or 0))
    insecure = getattr(args, "insecure", False)

    if chunk_ids:
        fetched: list = []
        for cid in chunk_ids:
            data = _api_json(
                "GET", "/v1/chunk/get", tok, params={"chunk_id": cid}, insecure=insecure,
            )
            if isinstance(data, dict):
                row = dict(data)
                row.setdefault("chunk_id", row.get("id") or cid)
                fetched.append(row)

        target_ids = set(chunk_ids)
        mode = "chunk_ids"
        if window > 0 and fetched:
            doc_id = fetched[0].get("doc_id")
            if doc_id:
                all_chunks, _, _ = _fetch_doc_chunks_all(tok, doc_id, insecure=insecure)
                id_order = [c.get("chunk_id") or c.get("id") for c in all_chunks]
                want: list = []
                seen: set = set()
                for tid in chunk_ids:
                    if tid not in id_order:
                        continue
                    idx = id_order.index(tid)
                    lo, hi = max(0, idx - window), min(len(all_chunks), idx + window + 1)
                    for c in all_chunks[lo:hi]:
                        cid = c.get("chunk_id") or c.get("id")
                        if cid and cid not in seen:
                            seen.add(cid)
                            want.append(c)
                if want:
                    fetched = want
                mode = f"chunk_ids+window({window})"

        if not fetched:
            out = {
                "metadata": {
                    "status": "no_result",
                    "action": "list_chunks",
                    "mode": mode,
                    "chunk_ids": chunk_ids,
                    "total_chunks": 0,
                    "items": [],
                    "via": "native:/v1/chunk/get",
                },
                "content": {"items": []},
                "compressible": True,
                "flush_group": "retrieval",
            }
        else:
            meta_items, content_items = _chunk_list_items(fetched, target_ids=target_ids if window > 0 else None)
            if limit > 0:
                meta_items, content_items = meta_items[:limit], content_items[:limit]
            out = {
                "metadata": {
                    "status": "success",
                    "action": "list_chunks",
                    "mode": mode,
                    "total_chunks": len(meta_items),
                    "items": meta_items,
                    "via": "native:/v1/chunk/get" + ("/v1/chunk/list" if window > 0 else ""),
                },
                "content": {"items": content_items},
                "compressible": True,
                "flush_group": "retrieval",
            }
        indent = None if args.raw else 2
        print(json.dumps(out, ensure_ascii=False, indent=indent))
        return

    doc_id = _resolve_doc_id(args)
    if not doc_id:
        sys.exit("[ERR] list_chunks 需要 --doc-ids 或 --chunk-ids")

    all_chunks, doc_meta, total = _fetch_doc_chunks_all(tok, doc_id, insecure=insecure)
    doc_name = (doc_meta or {}).get("name") or doc_id
    if not all_chunks:
        out = {
            "metadata": {
                "status": "no_result",
                "action": "list_chunks",
                "doc_id": doc_id,
                "doc_name": doc_name,
                "offset": offset,
                "has_more": False,
                "next_offset": None,
                "total_chunks": 0,
                "items": [],
                "via": "native:/v1/chunk/list",
            },
            "content": {"items": []},
            "compressible": True,
            "flush_group": "retrieval",
        }
    else:
        sliced = all_chunks[offset: offset + limit if limit > 0 else None]
        meta_items, content_items = _chunk_list_items(sliced)
        next_offset = offset + len(sliced)
        has_more = next_offset < total
        out = {
            "metadata": {
                "status": "success",
                "action": "list_chunks",
                "doc_id": doc_id,
                "doc_name": doc_name,
                "offset": offset,
                "has_more": has_more,
                "next_offset": next_offset if has_more else None,
                "total_chunks": total,
                "returned_chunks": len(meta_items),
                "remaining_chunks": max(0, total - next_offset),
                "items": meta_items,
                "via": "native:/v1/chunk/list",
            },
            "content": {"items": content_items},
            "compressible": True,
            "flush_group": "retrieval",
        }
        if has_more:
            out["budget_hint"] = (
                f"续读: list_chunks --doc-ids {doc_id} --offset {next_offset}"
                + (f" --limit {limit}" if limit > 0 else "")
            )
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def do_get_chunk(args, tok: dict) -> None:
    """取单条 chunk 全文（去掉向量字段）。"""
    if not args.chunk_id:
        sys.exit("[ERR] get_chunk 需要 --chunk-id")
    data = _api_json(
        "GET", "/v1/chunk/get", tok,
        params={"chunk_id": args.chunk_id},
        insecure=args.insecure,
    )
    out = {"ok": True, "action": "get_chunk", "chunk_id": args.chunk_id, "chunk": data}
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def do_patch_chunk(args, tok: dict) -> None:
    """更新 KB chunk 正文；服务端自动 re-tokenize + re-embed。

    走 /v1/chunk/set，与前端「编辑 chunk」同源。用于本地补全 Excel 超链接等。
    """
    if not args.doc_id:
        sys.exit("[ERR] patch_chunk 需要 --doc-id")
    if not args.chunk_id:
        sys.exit("[ERR] patch_chunk 需要 --chunk-id")
    content = _read_content_arg(args)
    _api_json(
        "POST", "/v1/chunk/set", tok,
        json_body={
            "doc_id": args.doc_id,
            "chunk_id": args.chunk_id,
            "content_with_weight": content,
        },
        insecure=args.insecure,
    )
    out = {
        "ok": True,
        "action": "patch_chunk",
        "doc_id": args.doc_id,
        "chunk_id": args.chunk_id,
        "content_chars": len(content),
        "re_embedded": True,
        "hint": "用 search --source document --query '<URL关键词>' 验证检索",
    }
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def do_create_chunk(args, tok: dict) -> None:
    """为 KB 文档新增一条 chunk；服务端 embed 并 increment_chunk_num。"""
    if not args.doc_id:
        sys.exit("[ERR] create_chunk 需要 --doc-id")
    content = _read_content_arg(args)
    data = _api_json(
        "POST", "/v1/chunk/create", tok,
        json_body={"doc_id": args.doc_id, "content_with_weight": content},
        insecure=args.insecure,
    )
    out = {
        "ok": True,
        "action": "create_chunk",
        "doc_id": args.doc_id,
        "chunk_id": data.get("chunk_id") if isinstance(data, dict) else data,
        "content_chars": len(content),
        "re_embedded": True,
    }
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def do_delete_chunks(args, tok: dict) -> None:
    """删除 KB 文档下指定 chunk（整 doc 重建前清空用）。

    走 /v1/chunk/rm。⚠️ 云端 document/run 重新解析也会删 chunk，与 patch 互斥。
    """
    if not args.doc_id:
        sys.exit("[ERR] delete_chunks 需要 --doc-id")
    if not args.chunk_ids:
        sys.exit("[ERR] delete_chunks 需要 --chunk-ids（逗号分隔）")
    ids = [x.strip() for x in str(args.chunk_ids).split(",") if x.strip()]
    if not ids:
        sys.exit("[ERR] delete_chunks: --chunk-ids 为空")
    _api_json(
        "POST", "/v1/chunk/rm", tok,
        json_body={"doc_id": args.doc_id, "chunk_ids": ids},
        insecure=args.insecure,
    )
    out = {
        "ok": True,
        "action": "delete_chunks",
        "doc_id": args.doc_id,
        "deleted": ids,
        "count": len(ids),
    }
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def do_kb_list(args, tok: dict) -> None:
    """列出当前用户可访问的所有知识库。

    走 ragbase 现有的 `/v1/kb/list` 端点（前端 KB 列表页同款），与 graft 共享
    同一种 itsdangerous token 鉴权。本 skill 仅作只读包装。
    """
    qs: dict = {}
    if args.keywords:
        qs["keywords"] = args.keywords
    if args.page:
        qs["page"] = args.page
    if args.page_size:
        qs["page_size"] = args.page_size
    if args.orderby:
        qs["orderby"] = args.orderby
    body = {"owner_ids": []}

    try:
        resp = requests.post(
            f"{tok['server']}/v1/kb/list",
            params=qs,
            json=body,
            headers={"Authorization": tok["auth_token"]},
            timeout=60,
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

    payload = data.get("data") or {}
    kbs = payload.get("kbs", [])
    # 投影：只保留对本地 agent 真正有用的字段，避免把整张 ragbase 表 dump 出去。
    summary = [
        {
            "kb_id": kb.get("id"),
            "name": kb.get("name"),
            "description": kb.get("description"),
            "doc_num": kb.get("doc_num"),
            "chunk_num": kb.get("chunk_num"),
            "language": kb.get("language"),
            "parser_id": kb.get("parser_id"),
            "tenant_id": kb.get("tenant_id"),
            "permission": kb.get("permission"),
            "create_date": kb.get("create_date"),
            "update_date": kb.get("update_date"),
        }
        for kb in kbs
    ]

    out = {
        "metadata": {
            "action": "list_kbs",
            "total": payload.get("total", len(summary)),
            "returned": len(summary),
        },
        "kbs": summary,
    }
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def do_kb_detail(args, tok: dict) -> None:
    """看单个 KB 的元信息（doc_num / chunk_num / size 等）。

    走 ragbase 现有的 `/v1/kb/detail?kb_id=<id>` 端点，只读。
    """
    if not args.kb_id:
        sys.exit("[ERR] kb_detail 需要 --kb-id")

    try:
        resp = requests.get(
            f"{tok['server']}/v1/kb/detail",
            params={"kb_id": args.kb_id},
            headers={"Authorization": tok["auth_token"]},
            timeout=60,
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

    indent = None if args.raw else 2
    print(json.dumps(data.get("data"), ensure_ascii=False, indent=indent))


def _split_csv_ids(raw) -> list:
    if not raw:
        return []
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def _fetch_visible_kb_ids(tok: dict, keywords: str = "", insecure: bool = False) -> list:
    """与 list_kbs 同源：用户可见的全部 KB id（含 team 共享）。"""
    qs = {"keywords": keywords} if keywords else {}
    data = _api_json(
        "POST", "/v1/kb/list", tok,
        params=qs, json_body={"owner_ids": []}, insecure=insecure,
    )
    kbs = data.get("kbs") if isinstance(data, dict) else data
    if not isinstance(kbs, list):
        return []
    return [k["id"] for k in kbs if k.get("id")]


def _kb_ids_for_action(args, tok: dict) -> list:
    ids = _split_csv_ids(getattr(args, "kb_ids", None) or getattr(args, "kb_id", None))
    if ids:
        return ids
    kw = (getattr(args, "keywords", None) or getattr(args, "query", None) or "").strip()
    return _fetch_visible_kb_ids(tok, keywords=kw, insecure=getattr(args, "insecure", False))


def do_list_documents_native(args, tok: dict) -> None:
    """列 KB 文档 — /v1/document/list，与前端 KB 页同源（不经 graft MemoryOS）。"""
    kb_ids = _kb_ids_for_action(args, tok)
    if not kb_ids:
        sys.exit("[ERR] list_documents: 无可见 KB。先 list_kbs 或加 --kb-ids")

    page = max(1, int(args.page or 1))
    page_size = min(100, max(1, int(args.page_size or 100)))
    keywords = (args.query or args.keywords or "").strip()

    all_items = []
    grand_total = 0
    for kb_id in kb_ids:
        params = {
            "kb_id": kb_id,
            "page": page,
            "page_size": page_size,
            "orderby": args.orderby or "create_time",
            "desc": "true",
        }
        if keywords:
            params["keywords"] = keywords
        payload = _api_json(
            "POST", "/v1/document/list", tok,
            params=params, json_body={}, insecure=args.insecure,
        )
        total = int(payload.get("total") or 0)
        grand_total += total
        for d in payload.get("docs") or []:
            all_items.append({
                "doc_id": d.get("id"),
                "doc_name": d.get("name"),
                "kb_id": kb_id,
                "chunks": d.get("chunk_num", 0),
                "run": d.get("run"),
            })

    out = {
        "metadata": {
            "action": "list_documents",
            "status": "success" if all_items else "no_result",
            "total": grand_total,
            "returned": len(all_items),
            "items": all_items,
            "via": "native:/v1/document/list",
        },
    }
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def _search_items_from_chunks(chunks: list) -> list:
    return [{
        "chunk_id": c.get("chunk_id") or c.get("id"),
        "doc_id": c.get("doc_id"),
        "doc_name": c.get("docnm_kwd"),
        "content": c.get("content_with_weight") or c.get("content") or "",
    } for c in chunks]


def do_search_document_native(args, tok: dict) -> None:
    """KB 文档检索。默认混合语义；--exact 走精确检索（全文，正文子串必含）。"""
    query = (args.query or "").strip()
    if not query:
        sys.exit("[ERR] search 需要 --query")

    kb_ids = _kb_ids_for_action(args, tok)
    if not kb_ids:
        sys.exit("[ERR] search: 无可见 KB。加 --kb-ids 或先 list_kbs")

    exact = bool(getattr(args, "exact", False))
    doc_ids = _split_csv_ids(getattr(args, "doc_ids", None))
    # 精确检索多召回候选再子串过滤，混合检索按 top_k
    top_k = max(30, int(args.top_k or 5)) if exact else max(1, min(int(args.top_k or 5), 50))

    body = {
        "kb_id": kb_ids if len(kb_ids) > 1 else kb_ids[0],
        "question": query,
        "top_k": top_k,
        "page": 1,
        "size": top_k,
        "highlight": True,
    }
    if doc_ids:
        body["doc_ids"] = doc_ids
    if exact:
        # 关掉向量权重，纯全文；子串过滤在下面做
        body["vector_similarity_weight"] = 0.0
        body["similarity_threshold"] = 0.0

    payload = _api_json(
        "POST", "/v1/chunk/retrieval_test", tok,
        json_body=body, insecure=args.insecure,
    )
    chunks = payload.get("chunks") or []

    if exact:
        # 精确 = 正文真的包含 query（大小写、空白不敏感），像 WHERE content LIKE '%q%'
        def _norm(s: str) -> str:
            return re.sub(r"\s+", "", (s or "")).lower()
        qn = _norm(query)
        chunks = [c for c in chunks if qn in _norm(c.get("content_with_weight"))]

    items = _search_items_from_chunks(chunks)
    out = {
        "metadata": {
            "action": "search",
            "source": "document",
            "mode": "exact" if exact else "hybrid",
            "status": "success" if items else "no_result",
            "total": len(items),
            "items": items,
            "kb_ids": kb_ids,
            "doc_ids": doc_ids or None,
        },
        "content": "\n\n---\n\n".join((it.get("content") or "")[:2000] for it in items),
    }
    if exact and not items:
        out["metadata"]["diagnosis_hint"] = (
            "精确检索 0 命中：若原文件里确实有该字符串，多半是 parse 没把它写进 chunk 正文"
            "（表格/扫描页/图片常见）。验收：download_document + 本地 grep；修复：patch_chunk 或重跑 parse。"
        )
    elif not exact and not items:
        out["metadata"]["hint"] = "精确/字面量查找请加 --exact；建议配 --doc-ids 缩小范围"
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def _should_use_native_kb_search(args) -> bool:
    src = (getattr(args, "source", None) or "").strip().lower()
    if src in ("round", "memory", "channel_history", "episode", "workspace"):
        return False
    if getattr(args, "session_id", None):
        return False
    return True


def _should_use_native_kb_list_chunks(args) -> bool:
    """KB 文档读 chunk 走原生 API；workspace / session 内 ws_ 文档仍走 graft。"""
    if getattr(args, "session_id", None):
        return False
    doc_id = _resolve_doc_id(args)
    if doc_id and str(doc_id).startswith("ws_"):
        return False
    return True


_UUID32_RE = __import__("re").compile(r"^[0-9a-fA-F]{32}$")


def _resolve_session_id(name: str, tok: dict, insecure: bool = False) -> str:
    """把 session 名 → UUID。HTTP /v1/graft/dispatch_task 端点只认 UUID（设计保守）。

    已经是 32 位 hex → 直接返回；否则走 list_sessions(query=name) 名称匹配：
      - 0 命中 → 报错
      - 1 命中 → 返回 UUID
      - 多命中 → 提示用户用更精确名称或直接用 UUID
    """
    if _UUID32_RE.match(name or ""):
        return name
    try:
        resp = requests.post(
            f"{tok['server']}/v1/graft/memory/unified_search",
            json={"action": "list_sessions", "query": name},
            headers={"Authorization": tok["auth_token"]},
            timeout=30,
            verify=not insecure,
        )
    except requests.exceptions.RequestException as e:
        sys.exit(f"[ERR] 解析 session 名称失败 (list_sessions): {e}")
    if resp.status_code == 401:
        sys.exit("[ERR] 认证失效，请重新运行: python scripts/login.py")
    try:
        data = resp.json()
    except Exception:
        sys.exit(f"[ERR] 非 JSON 响应: HTTP {resp.status_code}: {resp.text[:300]}")
    if data.get("code") != 0:
        sys.exit(f"[ERR] {data.get('message', data)}")
    items = (data.get("data") or {}).get("metadata", {}).get("items", []) or []
    # 先精确匹配（session_name 完全相等），再退化到部分匹配
    exact = [it for it in items if it.get("session_name") == name]
    candidates = exact or items
    if len(candidates) == 0:
        sys.exit(f"[ERR] 没有名为 '{name}' 的 session（list_sessions 0 命中）")
    if len(candidates) > 1:
        names = [f"  - {it.get('session_name')} ({it.get('session_id')})" for it in candidates[:8]]
        sys.exit(
            f"[ERR] 名称 '{name}' 匹配多个 session，请用 UUID 或更精确名称:\n"
            + "\n".join(names)
        )
    return candidates[0]["session_id"]


def _dispatch_to_session(session_uuid: str, prompt: str, tok: dict, insecure: bool = False) -> dict:
    """POST /v1/graft/dispatch_task：向已有 session 排队一轮执行（异步）。

    被 do_dispatch（独立派发）和 do_create_session（--first-prompt 建会话即驱动）
    共用，保证两条路径的派发语义、错误处理完全一致。返回服务端 data dict。
    """
    body = {"target_session_id": session_uuid, "prompt": prompt, "wait": False}
    try:
        resp = requests.post(
            f"{tok['server']}/v1/graft/dispatch_task",
            json=body,
            headers={"Authorization": tok["auth_token"]},
            timeout=60,
            verify=not insecure,
        )
    except requests.exceptions.RequestException as e:
        sys.exit(f"[ERR] dispatch 请求失败: {e}")
    if resp.status_code == 401:
        sys.exit("[ERR] 认证失效，请重新运行: python scripts/login.py")
    try:
        data = resp.json()
    except Exception:
        sys.exit(f"[ERR] 非 JSON 响应: HTTP {resp.status_code} {resp.text[:300]}")
    if data.get("code") != 0:
        sys.exit(f"[ERR] {data.get('message', data)}")
    return data.get("data") or {}


def do_dispatch(args, tok: dict) -> None:
    """派发任务到已有 session（异步）。

    走 ragbase 后端的 `/v1/graft/dispatch_task` 端点，等价于云端 Agent 的
    `dispatch_task_tool(wait=False)`：HTTP 立即返回，目标 session 在后台跑。

    要等结果，调用方应轮询 `get_round`（或 `list_sessions` 看 last_round_id 是否前进）。
    本接口只创建一次执行，不创建新 session、不删/写任何持久化资源。

    名称 → UUID 的解析在**本地**做（多调一次 list_sessions），保持 HTTP 端点契约简单。
    """
    if not args.session_id:
        sys.exit("[ERR] dispatch_task 需要 --session-id（目标 session 名称或 UUID）")
    if not args.prompt:
        sys.exit("[ERR] dispatch_task 需要 --prompt")

    target_uuid = _resolve_session_id(args.session_id, tok, insecure=args.insecure)
    if target_uuid != args.session_id:
        # 解析过名字才提示，避免直接传 UUID 时多余刷屏
        print(f"[INFO] resolved '{args.session_id}' → {target_uuid}", file=sys.stderr)

    payload = _dispatch_to_session(
        target_uuid, args.prompt, tok, insecure=args.insecure
    )
    out = {
        "ok": True,
        "queued": True,
        "target_session_id": payload.get("target_session_id"),
        "agent_id": payload.get("agent_id"),
        "queued_at_ms": payload.get("queued_at_ms"),
        "hint": (
            "用 get_digest --session-id <target_session_id> 看新一轮概览"
            "（服务端 get_round 需具体 round 号，不支持 -1）。"
        ),
    }
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def do_memories(args, tok: dict) -> None:
    """扫「我的记忆」+ 能读的「团队记忆」，guardian 格式。不写云端。"""
    payload = _api_json(
        "POST", "/v1/graft/memory/prologue", tok,
        json_body={"query": args.query or ""},
        insecure=args.insecure,
    ) or {}
    indent = None if args.raw else 2
    print(json.dumps(payload, ensure_ascii=False, indent=indent))


def do_team_memory(args, tok: dict) -> None:
    """把一条个人记忆提交到团队候选池 / 列团队 / 撤回。"""
    op = (getattr(args, "op", None) or "").strip()
    if op not in ("teams", "share", "revoke"):
        sys.exit("[ERR] team_memory 需要 --op teams|share|revoke")
    if op in ("share", "revoke") and not (getattr(args, "memory", None) or "").strip():
        sys.exit("[ERR] team_memory --op share/revoke 需要 --memory（记忆 id 或原话）")
    payload = _api_json(
        "POST", "/v1/graft/memory/team_memory", tok,
        json_body={
            "action": op,
            "memory": getattr(args, "memory", None) or "",
            "team": getattr(args, "team", None) or "",
            "memory_type": getattr(args, "memory_type", None) or "",
        },
        insecure=args.insecure,
    ) or {}
    indent = None if args.raw else 2
    print(json.dumps(payload, ensure_ascii=False, indent=indent))


_CURATE_OPS = ("pending", "list", "approve", "reject", "demote", "merge", "rewrite", "policy")
_CURATE_NEED_MEMORY = ("approve", "reject", "demote", "merge", "rewrite")


def do_team_curate(args, tok: dict) -> None:
    """团队所有者策展自己团队的记忆库：看候选池 / 批准 / 拒绝 / 下架 / 合并 / 改写 / 策略。
    只有团队所有者能调，成员会被服务端拒。"""
    op = (getattr(args, "op", None) or "").strip()
    if op not in _CURATE_OPS:
        sys.exit(f"[ERR] team_curate 需要 --op {'|'.join(_CURATE_OPS)}")
    memory = (getattr(args, "memory", None) or "").strip()
    into = (getattr(args, "into", None) or "").strip()
    has_content = getattr(args, "content", None) is not None or getattr(args, "content_file", None)
    # rewrite 必须给正文；policy 不给正文 = 只读当前策略
    content = _read_content_arg(args).strip() if (op == "rewrite" or (op == "policy" and has_content)) else ""
    if op in _CURATE_NEED_MEMORY and not memory:
        sys.exit(f"[ERR] team_curate --op {op} 需要 --memory（条目 id 或原话）")
    if op == "merge" and not into:
        sys.exit("[ERR] team_curate --op merge 需要 --into（保留哪一条）")
    if op == "rewrite" and not content:
        sys.exit("[ERR] team_curate --op rewrite 需要 --content / --content-file（改成什么）")
    body = {"action": op, "memory": memory, "into": into, "content": content}
    if getattr(args, "limit", None):
        body["limit"] = int(args.limit)
    payload = _api_json(
        "POST", "/v1/graft/memory/team_curate", tok, json_body=body, insecure=args.insecure,
    ) or {}
    indent = None if args.raw else 2
    print(json.dumps(payload, ensure_ascii=False, indent=indent))


def do_record(args, tok: dict) -> None:
    """用户决定记住的一句话 → 写入云端「我的记忆」。不扫本地文件。"""
    memory = (getattr(args, "memory", None) or "").strip()
    if not memory:
        sys.exit("[ERR] record 需要 --memory（要记住的原话）")
    payload = _api_json(
        "POST", "/v1/graft/memory/record", tok,
        json_body={
            "memory": memory,
            "memory_type": (getattr(args, "memory_type", None) or "fact").strip() or "fact",
        },
        insecure=args.insecure,
    ) or {}
    indent = None if args.raw else 2
    print(json.dumps(payload, ensure_ascii=False, indent=indent))


_DISPATCH_ONLY_FIELDS = frozenset({"prompt"})  # 只在 dispatch_task 里有意义
_KB_ONLY_FIELDS = frozenset({"kb_id", "keywords", "page", "page_size", "orderby"})
_CHUNK_API_FIELDS = frozenset({"chunk_id", "doc_id"})  # chunk API / download_document，不进 unified_search

# 显式放行的写动作（裸 create/rm/save 等仍拒绝；带后缀的具体动作在此登记）
_WRITE_ACTIONS = frozenset({
    "dispatch_task",
    "upload",
    "upload_document",
    "install_skill",
    "create_session",
    "patch_chunk",
    "create_chunk",
    "delete_chunks",
    "team_memory",
    "team_curate",
    "record",
})


def do_unified(args, tok: dict) -> None:
    body: dict = {"action": args.action}
    for field in _ARG_ALIAS:
        # 防止把 dispatch / kb_detail 专属字段误透传到 unified_search
        if field in _DISPATCH_ONLY_FIELDS or field in _KB_ONLY_FIELDS or field in _CHUNK_API_FIELDS:
            continue
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


def _collect_upload_files(args) -> list:
    """把 --file（可多次，逗号可分隔）+ --dir/--glob 解析成有序去重的本地文件列表。"""
    files: list = []
    for raw in (args.file or []):
        for part in str(raw).split(","):
            part = part.strip()
            if part:
                files.append(Path(part).expanduser())
    if args.dir:
        d = Path(args.dir).expanduser()
        if not d.is_dir():
            sys.exit(f"[ERR] --dir 不是目录: {d}")
        pattern = args.glob or "*"
        files.extend(sorted(p for p in d.glob(pattern) if p.is_file()))
    seen, uniq = set(), []
    for p in files:
        try:
            key = p.resolve()
        except Exception:
            key = p
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def _upload_one(args, tok: dict, upload_name: str, data: bytes):
    """上传单个文件到 /v1/document/upload。返回 (doc_id, returned_name)。失败 → 抛 RuntimeError。

    逐个文件上传（而非一次多文件）是刻意的：保证返回的 doc 行与本地文件 1:1 对齐，
    sha256 → doc_id → local_path 映射才精确（多文件批量时服务端可能重命名/丢弃，
    顺序对齐不可靠）。需要并行大批量请走前端 KB / 云端 Source。
    """
    mime, _ = mimetypes.guess_type(upload_name)
    form = {"kb_id": args.kb_id}
    if args.parser_id:
        form["parser_id"] = args.parser_id
    if args.kb_path:
        form["path"] = args.kb_path  # KB 内子目录（服务端 getlist('path') 接受单值）
    files = {"file": (upload_name, data, mime or "application/octet-stream")}
    try:
        resp = requests.post(
            f"{tok['server']}/v1/document/upload",
            data=form,
            files=files,
            headers={"Authorization": tok["auth_token"]},
            timeout=300,
            verify=not args.insecure,
        )
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"请求失败: {e}")
    # 401 在并发 worker 里抛 RuntimeError（不能 sys.exit，会变成 SystemExit 串到主线程）
    if resp.status_code == 401:
        raise RuntimeError("认证失效，请重新运行: python scripts/login.py")
    try:
        body = resp.json()
    except Exception:
        raise RuntimeError(f"非 JSON 响应: HTTP {resp.status_code} {resp.text[:300]}")
    if body.get("code") != 0:
        raise RuntimeError(body.get("message", body))
    docs = body.get("data") or []
    if isinstance(docs, dict):
        docs = [docs]
    if not docs or not isinstance(docs[0], dict) or not docs[0].get("id"):
        raise RuntimeError(f"上传成功但未返回 doc_id: {body}")
    return docs[0].get("id"), docs[0].get("name")


def do_upload(args, tok: dict) -> None:
    """把本地文件灌进指定 KB（写）。默认只上传不解析；--parse 才触发解析。

    复用平台现成端点 /v1/document/upload（+ 可选 /v1/document/run），与云端 agent 的
    kb_upload / kb_parse 同源；graft token 是完整用户会话签名，技术上即可命中这些
    @login_required 端点。KB 归属/权限校验、parser 白名单均由服务端 upload() 兜底。
    """
    if not args.kb_id:
        sys.exit("[ERR] upload 需要 --kb-id（目标知识库；用 list_kbs 查 kb_id）")
    paths = _collect_upload_files(args)
    if not paths:
        sys.exit("[ERR] upload 需要 --file <本地文件>（可多次）或 --dir <目录>[ --glob <模式>]")
    if args.name and len(paths) != 1:
        sys.exit("[ERR] --name 只能配合单个 --file 使用")

    # 并发上传：每个 worker 跑单文件（读字节 + sha + 一次 HTTP），按提交项回填结果，
    # 所以 sha256 → doc_id → local_path 的 1:1 映射不依赖完成顺序，并发也精确。
    # 与云端 kb_upload_batch 同策略；最多同时 workers 个文件的字节在内存里。
    workers = max(1, min(int(args.workers or 8), len(paths)))

    def _work(p):
        if not p.exists() or not p.is_file():
            return {"_ok": False, "local_path": str(p), "error": "文件不存在或不是文件"}
        size = p.stat().st_size
        if size > _MAX_UPLOAD:
            return {"_ok": False, "local_path": str(p),
                    "error": f"文件过大 {size} bytes > {_MAX_UPLOAD}（大文件请走前端 KB）"}
        try:
            data = p.read_bytes()
        except Exception as e:
            return {"_ok": False, "local_path": str(p), "error": f"读文件失败: {e}"}
        sha = hashlib.sha256(data).hexdigest()
        upload_name = args.name or p.name
        try:
            doc_id, returned_name = _upload_one(args, tok, upload_name, data)
        except RuntimeError as e:
            return {"_ok": False, "local_path": str(p), "error": str(e)}
        return {"_ok": True, "doc_id": doc_id, "name": returned_name or upload_name,
                "bytes": size, "sha256": sha, "local_path": str(p.resolve())}

    results = [None] * len(paths)
    if workers == 1:
        for i, p in enumerate(paths):
            results[i] = _work(p)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fut_to_idx = {pool.submit(_work, p): i for i, p in enumerate(paths)}
            for fut in as_completed(fut_to_idx):
                results[fut_to_idx[fut]] = fut.result()

    uploaded = [{k: v for k, v in r.items() if k != "_ok"} for r in results if r and r.get("_ok")]
    failed = [{k: v for k, v in r.items() if k != "_ok"} for r in results if r and not r.get("_ok")]

    doc_ids = [u["doc_id"] for u in uploaded if u["doc_id"]]

    parse_triggered, parse_error = False, None
    if args.parse and doc_ids:
        try:
            presp = requests.post(
                f"{tok['server']}/v1/document/run",
                json={"doc_ids": doc_ids, "run": 1},
                headers={"Authorization": tok["auth_token"]},
                timeout=600,
                verify=not args.insecure,
            )
            if presp.status_code == 401:
                sys.exit("[ERR] 认证失效，请重新运行: python scripts/login.py")
            try:
                pbody = presp.json()
            except Exception:
                pbody = {}
            if presp.status_code == 200 and pbody.get("code") == 0:
                parse_triggered = True
            else:
                parse_error = pbody.get("message") or f"HTTP {presp.status_code}: {presp.text[:200]}"
        except requests.exceptions.RequestException as e:
            parse_error = str(e)

    # 本地 content_hash → local_path 映射（append-only，写本地，不回传云端）
    manifest_written = None
    if not args.no_manifest and uploaded:
        try:
            UPLOAD_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
            ts = int(time.time() * 1000)
            with open(UPLOAD_MANIFEST_PATH, "a", encoding="utf-8") as mf:
                for u in uploaded:
                    mf.write(json.dumps({
                        "ts_ms": ts,
                        "kb_id": args.kb_id,
                        "doc_id": u["doc_id"],
                        "name": u["name"],
                        "sha256": u["sha256"],
                        "local_path": u["local_path"],
                        "bytes": u["bytes"],
                        "parsed": parse_triggered,
                    }, ensure_ascii=False) + "\n")
            manifest_written = str(UPLOAD_MANIFEST_PATH)
        except Exception as e:
            print(f"[WARN] 写本地 manifest 失败: {e}", file=sys.stderr)

    out = {
        "ok": len(failed) == 0 and bool(uploaded),
        "kb_id": args.kb_id,
        "count": len(uploaded),
        "uploaded": uploaded,
        "parse_triggered": parse_triggered,
        "manifest": manifest_written,
        "hint": (
            f"已触发解析，用 `list_documents --kb-ids {args.kb_id}` 轮询 run/progress。"
            if parse_triggered else
            f"已上传未解析。要入库检索加 --parse，或前端 KB 页点解析；"
            f"进度用 `list_documents --kb-ids {args.kb_id}` 看。"
        ),
    }
    if failed:
        out["failed"] = failed
    if parse_error:
        out["parse_error"] = parse_error
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


# 打包 skill 目录时跳过的目录（graft 是独立 requests 客户端，不 import ragbase，
# 这里维护一份与后端 SKIP_DIRS 等价的客户端副本）。
_SKILL_SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".pytest_cache", ".mypy_cache", ".idea", ".vscode",
    "tmp",  # 与仓库 .gitignore 的 tmp/ 一致：本地 code-exec 落盘，不是技能内容
})

# Windows 编辑器的「UTF-8 with BOM」会在文件头塞 \ufeff。SKILL.md 带 BOM 时
# 服务端 front-matter 正则（锚在第 0 字节）直接 miss，技能元数据退化成
# description="\ufeff---"，整段 front-matter 还会漏进正文注入给模型。
# 上传前按扩展名剥掉，脏字节永远进不了技能库。二进制（assets 里的图/表）不碰。
_BOM = b"\xef\xbb\xbf"
_BOM_STRIP_SUFFIXES = frozenset({
    ".md", ".py", ".json", ".txt", ".yaml", ".yml", ".sh", ".csv", ".toml", ".cfg",
})

# 技能根目录在两个执行引擎里不是同一个绝对路径（Full: materialize_skill() 的返回值，
# Fast/CC: /workspace/.claude/skills/<name>/），当前目录两边都不是技能目录。CC 原生会把
# 技能正文里的 ${CLAUDE_SKILL_DIR} 就地展开成真实绝对路径，所以它是唯一一份两个引擎都能
# 认的写法 —— 上传前把跑不起来的路径改写成它。
_SKILL_DIR_VAR = "${CLAUDE_SKILL_DIR}"
_ABS_WORKSPACE_RE = re.compile(r"/workspace/([\w.-]+|\.\.\.)(/[\w./<>-]*)?")
# /workspace 下真实存在的顶层目录：会话产物两个引擎都有，写绝对路径是对的；``...`` 是文档占位。
# 其余顶层目录一律不存在 —— 多半是作者拿技能名或某个子目录当了 /workspace 的一级。
_REAL_WORKSPACE_DIRS = frozenset({"sessions", "outputs", "inputs", "..."})


def _fix_skill_paths(skill_md: str, rel_paths: list) -> tuple:
    """按 bundle 的文件清单校正 SKILL.md 里换个引擎就读不到的路径。

    1. 指向技能目录的 ``/workspace/...`` 绝对路径 **自动改写**成
       ``${CLAUDE_SKILL_DIR}/<相对路径>``（按最长后缀匹配包里的文件/目录）。这类无歧义：
       那个绝对路径在另一个引擎里根本不存在，包里又只有一个位置对得上。
    2. 裸文件名（包里在子目录下、正文别处也没给出相对路径）**只提醒不改**。同一个裸名
       可能是要执行的命令参数，也可能是目录树示意图里的一格、或泛指某类文件
       （``改 theme.yaml 里的 colors`` 说的是复制出来的那份，不是包里那份），
       这些改了就是错的，而区分只有作者做得到。

    只动上传副本，本地文件不变。返回 ``(新正文, 改写记录, 只能提醒的问题)``。
    """
    known = set(rel_paths) | {p.rsplit("/", 1)[0] for p in rel_paths if "/" in p}
    by_base = {}
    for p in rel_paths:
        by_base.setdefault(p.rsplit("/", 1)[-1], []).append(p)

    fixes, warns = [], []

    def _rewrite_abs(m):
        if m.group(1) in _REAL_WORKSPACE_DIRS:
            return m.group(0)  # 会话目录 / 文档占位，绝对路径是对的
        segs = m.group(0)[len("/workspace/"):].strip("/").split("/")
        for i in range(len(segs)):  # 最长后缀优先：剥掉 builtin-skills/<name> 这类前缀
            cand = "/".join(segs[i:])
            if cand in known:
                fixes.append(f"{m.group(0)} → {_SKILL_DIR_VAR}/{cand}")
                return f"{_SKILL_DIR_VAR}/{cand}"
        warns.append(f"绝对路径 {m.group(0)}：包里没有对应文件，改不了，请自己确认")
        return m.group(0)

    body = _ABS_WORKSPACE_RE.sub(_rewrite_abs, skill_md)

    for base, hits in sorted(by_base.items()):
        if not any("/" in h for h in hits):
            continue  # 文件就在技能根目录，裸名引用本来就对
        if "." not in base:
            continue  # 没扩展名的多半是普通英文词（dist/browse、bin/gstack-config）
        if any(h in body for h in hits):
            continue  # 正文别处给了完整相对路径，模型找得到
        # 裸名：前面不能连着路径分隔符或别的标识符，否则是 scripts/x.py 里的那一段
        if not re.search(rf"(?<![\w/.\-]){re.escape(base)}(?![\w-])", body):
            continue
        want = f"{_SKILL_DIR_VAR}/{hits[0]}" if len(hits) == 1 else "/".join(("…",) + tuple(hits))
        warns.append(f"裸文件名 {base}：正文没给出目录，模型读不到 → 命令里请写 {want}")

    return body, list(dict.fromkeys(fixes)), list(dict.fromkeys(warns))


def do_install_skill(args, tok: dict) -> None:
    """把本地 skill 目录打包成 zip 上传到云端**个人**技能库（写）。

    复用后端 /v1/skills/install_bundle：服务端解压 → Layer-8 SkillSafetyValidator
    校验 → 只写进 skills/users/<本人 uid>/<skill>/，git 可选（未配仓库也能装）。
    与前端「技能上传」、离线 install_user_skill.py 同一条 save_skill_validated 入口，
    安全校验 / shadow 冲突语义一致。

    目录约定：--skill-path 指向的目录必须直接含 SKILL.md，且**目录名 == SKILL.md
    里的 name**（后端 parser 强制 dir-name invariant）。scripts/ references/ assets/
    等子目录会一并打包（自动跳过 .git / __pycache__ 等）。
    """
    if not args.skill_path:
        sys.exit("[ERR] install_skill 需要 --skill-path（本地 skill 目录，含 SKILL.md）")
    skill_dir = Path(args.skill_path).expanduser()
    if not skill_dir.is_dir():
        sys.exit(f"[ERR] --skill-path 不是目录: {skill_dir}")
    if not (skill_dir / "SKILL.md").is_file():
        sys.exit(f"[ERR] {skill_dir} 下找不到 SKILL.md（skill 目录必须含 SKILL.md）")

    top = skill_dir.name  # 顶层目录名，后端按它做 dir-name invariant 校验
    contents = {}  # rel → bytes，先全收齐：路径改写要拿整份文件清单当依据
    debommed = []
    for root, dirs, files in os.walk(skill_dir):
        dirs[:] = [
            d for d in dirs
            if d not in _SKILL_SKIP_DIRS and not d.startswith(".")
        ]
        for fn in sorted(files):
            if fn.startswith("."):  # .DS_Store / .gitignore 之类
                continue
            fp = Path(root) / fn
            rel = fp.relative_to(skill_dir).as_posix()
            data = fp.read_bytes()
            if data.startswith(_BOM) and fp.suffix.lower() in _BOM_STRIP_SUFFIXES:
                data = data[len(_BOM):]
                debommed.append(rel)
            contents[rel] = data
    if "SKILL.md" not in contents:
        sys.exit("[ERR] 打包后竟无 SKILL.md，请检查目录")
    if debommed:
        print(f"[i] 已剥掉 UTF-8 BOM（上传副本，本地文件不变）: {', '.join(debommed)}")

    fixed, fixes, warns = _fix_skill_paths(
        contents["SKILL.md"].decode("utf-8", "replace"), sorted(contents),
    )
    if fixes:
        contents["SKILL.md"] = fixed.encode("utf-8")
        print("[i] SKILL.md 路径已改写为 ${CLAUDE_SKILL_DIR}（上传副本，本地文件不变）:")
        for fix in fixes:
            print(f"    {fix}")
    for warn in warns:
        print(f"[!] 可移植性: {warn}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, data in contents.items():
            zf.writestr(f"{top}/{rel}", data)
    zip_bytes = buf.getvalue()
    if len(zip_bytes) > _MAX_UPLOAD:
        sys.exit(f"[ERR] 打包体积过大 {len(zip_bytes)} bytes > {_MAX_UPLOAD}")

    form = {}
    if args.overwrite:
        form["overwrite"] = "true"
    if args.allow_shadow:
        form["allow_shadow"] = "true"
    files = {"file": (f"{top}.zip", zip_bytes, "application/zip")}

    try:
        resp = requests.post(
            f"{tok['server']}/v1/skills/install_bundle",
            data=form,
            files=files,
            headers={"Authorization": tok["auth_token"]},
            timeout=300,
            verify=not args.insecure,
        )
    except requests.exceptions.RequestException as e:
        sys.exit(f"[ERR] 请求失败: {e}")

    if resp.status_code == 401:
        sys.exit("[ERR] 认证失效，请重新运行: python scripts/login.py")
    try:
        body = resp.json()
    except Exception:
        sys.exit(f"[ERR] 非 JSON 响应: HTTP {resp.status_code} {resp.text[:300]}")

    data = body.get("data") or {}
    # 业务失败：shadow 冲突 / 校验错误 / 已存在，给可操作提示
    if body.get("code") != 0 or not data.get("success"):
        if data.get("needs_confirmation") and data.get("shadow_conflicts"):
            names = ", ".join(
                sc.get("tool_name") for sc in data["shadow_conflicts"]
            )
            sys.exit(
                f"[ERR] 与 builtin 工具同名冲突: {names}。"
                "确认要覆盖请加 --allow-shadow。"
            )
        sys.exit(f"[ERR] {body.get('message', data)}")

    out = {
        "ok": True,
        "skill_name": data.get("skill_name", top),
        "file_count": data.get("file_count", len(contents)),
        "packed_files": sorted(contents),
        "hint": (
            "已装入个人技能库（skills/users/<你>/）。"
            "在 ComboAgent 会话或前端「技能设置」即可见。"
        ),
    }
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def do_list_agents(args, tok: dict) -> None:
    """列当前用户的 combo agents（只读），供 create_session 选 agent_id。

    复用前端端点 GET /v1/combo_web/agents（与「新建会话」选 bot 同源），不写任何
    云端资源。可选 --keywords 在本地按 agent 名过滤。
    """
    params = {
        "canvas_type": args.canvas_type or "combo",
        "limit": int(args.limit) if args.limit else 30,
        "offset": int(args.offset) if args.offset else 0,
    }
    try:
        resp = requests.get(
            f"{tok['server']}/v1/combo_web/agents",
            params=params,
            headers={"Authorization": tok["auth_token"]},
            timeout=30,
            verify=not args.insecure,
        )
    except requests.exceptions.RequestException as e:
        sys.exit(f"[ERR] 请求失败: {e}")
    if resp.status_code == 401:
        sys.exit("[ERR] 认证失效，请重新运行: python scripts/login.py")
    try:
        body = resp.json()
    except Exception:
        sys.exit(f"[ERR] 非 JSON 响应: HTTP {resp.status_code} {resp.text[:300]}")
    if body.get("code") != 0:
        sys.exit(f"[ERR] {body.get('message', body)}")
    data = body.get("data") or {}
    agents = data.get("agents") or []
    kw = (args.keywords or "").strip().lower()
    if kw:
        agents = [
            a for a in agents
            if kw in (a.get("name") or a.get("title") or "").lower()
        ]
    items = [
        {
            "agent_id": a.get("agent_id") or a.get("id"),
            "name": a.get("name") or a.get("title"),
            "canvas_type": a.get("canvas_type"),
            "updated_at": a.get("updated_at"),
        }
        for a in agents
    ]
    out = {
        "ok": True,
        "action": "list_agents",
        "count": len(items),
        "total": data.get("total"),
        "agents": items,
        "hint": (
            "用 agent_id 建会话："
            "create_session --agent-id <id> [--name <会话名>] [--first-prompt <指令>]"
        ),
    }
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def _resolve_agent_id(name: str, tok: dict, insecure: bool = False) -> str:
    """agent 名 → UUID。已是 32 位 hex 直接返回；否则 GET /v1/combo_web/agents 名称匹配。

    与 _resolve_session_id 同构：0 命中报错，多命中提示用更精确名称或 UUID。
    """
    if _UUID32_RE.match(name or ""):
        return name
    try:
        resp = requests.get(
            f"{tok['server']}/v1/combo_web/agents",
            params={"canvas_type": "combo", "limit": 200, "offset": 0},
            headers={"Authorization": tok["auth_token"]},
            timeout=30,
            verify=not insecure,
        )
    except requests.exceptions.RequestException as e:
        sys.exit(f"[ERR] 解析 agent 名称失败 (list_agents): {e}")
    if resp.status_code == 401:
        sys.exit("[ERR] 认证失效，请重新运行: python scripts/login.py")
    try:
        body = resp.json()
    except Exception:
        sys.exit(f"[ERR] 非 JSON 响应: HTTP {resp.status_code} {resp.text[:300]}")
    if body.get("code") != 0:
        sys.exit(f"[ERR] {body.get('message', body)}")
    agents = (body.get("data") or {}).get("agents") or []

    def _nm(a):
        return a.get("name") or a.get("title") or ""

    exact = [a for a in agents if _nm(a) == name]
    candidates = exact or [a for a in agents if name.lower() in _nm(a).lower()]
    if len(candidates) == 0:
        sys.exit(f"[ERR] 没有名为 '{name}' 的 agent（list_agents 0 命中）")
    if len(candidates) > 1:
        names = [
            f"  - {_nm(a)} ({a.get('agent_id') or a.get('id')})"
            for a in candidates[:8]
        ]
        sys.exit(
            f"[ERR] 名称 '{name}' 匹配多个 agent，请用 UUID 或更精确名称:\n"
            + "\n".join(names)
        )
    return candidates[0].get("agent_id") or candidates[0].get("id")


def do_create_session(args, tok: dict) -> None:
    """为指定 agent 在云端新建一个 session（写）。

    复用前端端点 POST /v1/combo_web/agents/<agent_id>/sessions（与前端「新建会话」
    同一入口）。--first-prompt 可在建好后立即 dispatch_task 驱动首轮，实现
    “本地一步建会话并驱动”的闭环。

    注意：服务端默认 allow_duplicate=False 时，若该 agent 已有 session，会**复用**
    已存在的那个（不新建）；要强制新建用 --allow-duplicate。
    """
    if not args.agent_id:
        sys.exit(
            "[ERR] create_session 需要 --agent-id（agent 名称或 UUID；先用 list_agents 查）"
        )
    agent_uuid = _resolve_agent_id(args.agent_id, tok, insecure=args.insecure)
    if agent_uuid != args.agent_id:
        print(f"[INFO] resolved agent '{args.agent_id}' → {agent_uuid}", file=sys.stderr)

    body = {"allow_duplicate": bool(args.allow_duplicate)}
    if args.name:
        body["name"] = args.name

    try:
        resp = requests.post(
            f"{tok['server']}/v1/combo_web/agents/{agent_uuid}/sessions",
            json=body,
            headers={"Authorization": tok["auth_token"]},
            timeout=60,
            verify=not args.insecure,
        )
    except requests.exceptions.RequestException as e:
        sys.exit(f"[ERR] 请求失败: {e}")
    if resp.status_code == 401:
        sys.exit("[ERR] 认证失效，请重新运行: python scripts/login.py")
    try:
        rbody = resp.json()
    except Exception:
        sys.exit(f"[ERR] 非 JSON 响应: HTTP {resp.status_code} {resp.text[:300]}")
    if rbody.get("code") != 0:
        sys.exit(f"[ERR] {rbody.get('message', rbody)}")

    sess = rbody.get("data") or {}
    session_id = sess.get("session_id") or sess.get("id")
    if not session_id:
        sys.exit(f"[ERR] 服务端未返回 session_id: {sess}")

    out = {
        "ok": True,
        "action": "create_session",
        "session_id": session_id,
        "agent_id": agent_uuid,
        "name": sess.get("name") or sess.get("session_name"),
        "hint": (
            "用 dispatch_task --session-id <session_id> --prompt <指令> 驱动执行；"
            "或 get_digest --session-id <session_id> 看进度。"
        ),
    }

    if args.first_prompt:
        payload = _dispatch_to_session(
            session_id, args.first_prompt, tok, insecure=args.insecure
        )
        out["dispatched"] = True
        out["first_prompt"] = args.first_prompt
        out["queued_at_ms"] = payload.get("queued_at_ms")
        out["hint"] = (
            "已建会话并派发首轮。用 get_digest --session-id "
            f"{session_id} 看新一轮概览（get_round 需具体 round 号）。"
        )

    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def do_wire_script_tools(args, tok: dict) -> None:
    """把一个已装的（无 manifest）skill 的脚本接成动态工具（skill-only，零核心改动）。

    原理：**不新增任何后端端点、不改平台核心**。本动作只是把一段"接线"指令通过
    现成的 dispatch_task 派给一个已有 combo 会话，由云端 agent 在会话里用它自带的
    自编程能力（`write_file` 写 `users/<uid>/scripts/<tool>/main.py` + 登记
    `registry.json`，即 assistant 提示词 §SCRIPT TOOL REGISTRATION 的"方式二"）
    把脚本注册成持久工具。下一会话 basic_team 的 `load_all → create_dynamic_tools`
    自动把它们放进工具池。

    所以它**不是第五个写端点**——底层就是 dispatch_task（已放行的写动作），不建/
    删资源。兜底：即使接线失败，skill 仍以纯 markdown 形式可用（agent 读 SKILL.md +
    execute_code 跑脚本），只是没升级成动态工具。

    要等结果用 `get_digest --session-id <target>` 轮询；**工具在下一个会话才生效**。
    """
    if not args.skill_name:
        sys.exit("[ERR] wire_script_tools 需要 --skill-name（已装入个人库的 skill 名）")
    if not args.session_id:
        sys.exit("[ERR] wire_script_tools 需要 --session-id（派发接线任务的目标会话名/UUID）")

    # 接线提示词模板与本脚本同属一个 skill：scripts/call.py → ../references/
    tmpl_path = (
        Path(__file__).resolve().parent.parent / "references" / "wire-script-tools.md"
    )
    try:
        template = tmpl_path.read_text(encoding="utf-8")
    except OSError as e:
        sys.exit(f"[ERR] 读取接线模板失败 {tmpl_path}: {e}")

    prompt = template.replace("{{SKILL_NAME}}", args.skill_name)
    extra = (args.prompt or "").strip()
    if extra:
        prompt += f"\n\n## 额外要求（调用方追加）\n{extra}\n"

    target_uuid = _resolve_session_id(args.session_id, tok, insecure=args.insecure)
    if target_uuid != args.session_id:
        print(f"[INFO] resolved '{args.session_id}' → {target_uuid}", file=sys.stderr)

    payload = _dispatch_to_session(
        target_uuid, prompt, tok, insecure=args.insecure
    )
    out = {
        "ok": True,
        "queued": True,
        "skill_name": args.skill_name,
        "target_session_id": payload.get("target_session_id"),
        "agent_id": payload.get("agent_id"),
        "queued_at_ms": payload.get("queued_at_ms"),
        "hint": (
            "接线任务已派发（底层 = dispatch_task）。用 "
            "get_digest --session-id <target_session_id> 看 agent 接线结果；"
            "注册的工具在【下一个会话】才会被加载进工具池。"
        ),
    }
    indent = None if args.raw else 2
    print(json.dumps(out, ensure_ascii=False, indent=indent))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="graft-comboagent 调用入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "action",
        help="list_sessions | get_digest | get_round | search | "
             "search_by_artifact | read_file | list_files | grep_file | "
             "list_documents | get_doc_profile | list_chunks | download | "
             "download_document | list_doc_chunks | get_chunk | "
             "patch_chunk | create_chunk | delete_chunks | "
             "list_kbs | kb_detail | list_agents | create_session | "
             "dispatch_task | upload | install_skill | wire_script_tools | "
             "memories | record | team_memory | team_curate",
    )
    for field, flags in _ARG_ALIAS.items():
        ap.add_argument(*flags, dest=field, default=None)
    ap.add_argument("--filename", default=None,
                    help="download: HTTP 附件名；默认 path basename")
    ap.add_argument("--out", default=None,
                    help="download / download_document: 本地落盘路径")
    ap.add_argument("--content", default=None,
                    help="patch_chunk / create_chunk: 新正文（与 --content-file 二选一）")
    ap.add_argument("--content-file", dest="content_file", default=None,
                    help="patch_chunk / create_chunk: 从文件读正文")
    # ── upload 专属（不进 _ARG_ALIAS，不会透传给 unified_search）──
    ap.add_argument("--file", action="append", default=None,
                    help="upload: 本地文件路径，可多次（也支持逗号分隔）")
    ap.add_argument("--dir", default=None,
                    help="upload: 本地目录，配合 --glob 批量上传目录下文件")
    ap.add_argument("--glob", default=None,
                    help="upload: --dir 下的匹配模式，默认 '*'（用 '**/*' 递归）")
    ap.add_argument("--parser-id", dest="parser_id", default=None,
                    help="upload: 指定 parser_id 覆盖 KB 默认（白名单，未知会被服务端拒）")
    ap.add_argument("--kb-path", dest="kb_path", default=None,
                    help="upload: KB 内子目录（落到 KB 的文件夹结构里）")
    ap.add_argument("--name", default=None,
                    help="upload: 重命名上传文件（仅单文件）")
    ap.add_argument("--parse", action="store_true",
                    help="upload: 上传后立即触发解析入库（默认只上传不解析）")
    ap.add_argument("--workers", type=int, default=8,
                    help="upload: 并发上传线程数（默认 8；--workers 1 退回顺序）")
    ap.add_argument("--no-manifest", action="store_true",
                    help="upload: 不写本地 content_hash→local_path 映射清单")
    # ── install_skill 专属 ──
    ap.add_argument("--skill-path", dest="skill_path", default=None,
                    help="install_skill: 本地 skill 目录（含 SKILL.md，目录名须等于 skill 名）")
    ap.add_argument("--overwrite", action="store_true",
                    help="install_skill: 同名技能已存在时覆盖（默认拒绝）")
    ap.add_argument("--allow-shadow", dest="allow_shadow", action="store_true",
                    help="install_skill: 允许覆盖 builtin 同名 tool（罕见，谨慎）")
    # ── wire_script_tools 专属 ──
    ap.add_argument("--skill-name", dest="skill_name", default=None,
                    help="wire_script_tools: 已装入个人库、要把脚本接成动态工具的 skill 名")
    # ── list_agents / create_session 专属 ──
    ap.add_argument("--agent-id", dest="agent_id", default=None,
                    help="create_session: 目标 agent 名称或 UUID（先用 list_agents 查）")
    ap.add_argument("--canvas-type", dest="canvas_type", default=None,
                    help="list_agents: 过滤 canvas_type（默认 combo）")
    ap.add_argument("--first-prompt", dest="first_prompt", default=None,
                    help="create_session: 建好会话后立即派发的首条指令（一步建并驱动）")
    ap.add_argument("--allow-duplicate", dest="allow_duplicate", action="store_true",
                    help="create_session: 强制新建（默认复用该 agent 已有 session）")
    ap.add_argument("--op", dest="op", default=None,
                    help="team_memory: teams / share / revoke；"
                         "team_curate: pending / list / approve / reject / demote / merge / rewrite / policy")
    ap.add_argument("--memory", dest="memory", default=None,
                    help="record: 要记住的原话；team_memory / team_curate: 记忆 id 或原话")
    ap.add_argument("--team", dest="team", default=None,
                    help="team_memory share: 团队名或 tenant_id；只在一个团队里可不填")
    ap.add_argument("--into", dest="into", default=None,
                    help="team_curate merge: 保留哪一条（id 或原话）")
    ap.add_argument("--memory-type", dest="memory_type", default=None,
                    help="record / team_memory: fact / preference / program / error_pattern（record 默认 fact）")
    ap.add_argument("--raw", action="store_true",
                    help="JSON 输出不 pretty-print")
    ap.add_argument("--exact", action="store_true",
                    help="search: 精确检索（全文关向量 + 正文子串必含），用于 ID/编号/原文短语")
    ap.add_argument("--insecure", action="store_true",
                    help="忽略 TLS 校验（仅调试）")
    args = ap.parse_args()

    tok = load_token()
    if not tok.get("server") or not tok.get("auth_token"):
        sys.exit(f"[ERR] token 文件字段不完整: {TOKEN_PATH}")

    # ⚠️ 写边界：仅 _WRITE_ACTIONS 里列出的动作可写 KB / session / 技能库。
    # 裸 create/rm/save/update 等仍拒绝（create_session / create_chunk 等
    # 带具体后缀的动作在 _WRITE_ACTIONS 白名单里）。
    _BANNED_ACTIONS = frozenset({
        "rm", "delete", "remove", "save", "create", "update", "patch", "put",
        "copy_kb_document", "register_artifact",
    })
    if args.action in _BANNED_ACTIONS and args.action not in _WRITE_ACTIONS:
        sys.exit(
            f"[ERR] 拒绝执行写操作 '{args.action}'。"
            f"graft 写口: {', '.join(sorted(_WRITE_ACTIONS))}"
        )
    if args.action not in _WRITE_ACTIONS and any(
        args.action.startswith(p) for p in ("rm_", "delete_", "remove_")
    ):
        sys.exit(
            f"[ERR] 拒绝执行写操作 '{args.action}'。"
            f"graft 写口: {', '.join(sorted(_WRITE_ACTIONS))}"
        )

    if args.action == "download":
        do_download(args, tok)
    elif args.action == "download_document":
        do_download_document(args, tok)
    elif args.action == "list_doc_chunks":
        do_list_doc_chunks(args, tok)
    elif args.action == "get_chunk":
        do_get_chunk(args, tok)
    elif args.action == "patch_chunk":
        do_patch_chunk(args, tok)
    elif args.action == "create_chunk":
        do_create_chunk(args, tok)
    elif args.action == "delete_chunks":
        do_delete_chunks(args, tok)
    elif args.action == "list_kbs":
        do_kb_list(args, tok)
    elif args.action == "kb_detail":
        do_kb_detail(args, tok)
    elif args.action == "dispatch_task":
        do_dispatch(args, tok)
    elif args.action in ("upload", "upload_document"):
        do_upload(args, tok)
    elif args.action == "install_skill":
        do_install_skill(args, tok)
    elif args.action == "list_agents":
        do_list_agents(args, tok)
    elif args.action == "create_session":
        do_create_session(args, tok)
    elif args.action == "wire_script_tools":
        do_wire_script_tools(args, tok)
    elif args.action == "memories":
        do_memories(args, tok)
    elif args.action == "record":
        do_record(args, tok)
    elif args.action == "team_memory":
        do_team_memory(args, tok)
    elif args.action == "team_curate":
        do_team_curate(args, tok)
    elif args.action == "list_documents":
        do_list_documents_native(args, tok)
    elif args.action == "search" and _should_use_native_kb_search(args):
        do_search_document_native(args, tok)
    elif args.action == "list_chunks" and _should_use_native_kb_list_chunks(args):
        do_list_chunks_native(args, tok)
    else:
        do_unified(args, tok)


if __name__ == "__main__":
    main()
