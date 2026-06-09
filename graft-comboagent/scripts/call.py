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
"""
import argparse
import hashlib
import io
import json
import mimetypes
import os
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
    "chunk_ids":  ["--chunk-ids"],
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


_DISPATCH_ONLY_FIELDS = frozenset({"prompt"})  # 只在 dispatch_task 里有意义
_KB_ONLY_FIELDS = frozenset({"kb_id", "keywords", "page", "page_size", "orderby"})


def do_unified(args, tok: dict) -> None:
    body: dict = {"action": args.action}
    for field in _ARG_ALIAS:
        # 防止把 dispatch / kb_detail 专属字段误透传到 unified_search
        if field in _DISPATCH_ONLY_FIELDS or field in _KB_ONLY_FIELDS:
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
})


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
    buf = io.BytesIO()
    packed = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
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
                zf.write(fp, arcname=f"{top}/{rel}")
                packed.append(rel)
    if "SKILL.md" not in packed:
        sys.exit("[ERR] 打包后竟无 SKILL.md，请检查目录")
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
        "file_count": data.get("file_count", len(packed)),
        "packed_files": sorted(packed),
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
             "list_kbs | kb_detail | list_agents | create_session | "
             "dispatch_task | upload | install_skill",
    )
    for field, flags in _ARG_ALIAS.items():
        ap.add_argument(*flags, dest=field, default=None)
    ap.add_argument("--filename", default=None,
                    help="download: HTTP 附件名；默认 path basename")
    ap.add_argument("--out", default=None,
                    help="download: 本地落盘路径；默认 .graft/downloads/<basename>")
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
    # ── list_agents / create_session 专属 ──
    ap.add_argument("--agent-id", dest="agent_id", default=None,
                    help="create_session: 目标 agent 名称或 UUID（先用 list_agents 查）")
    ap.add_argument("--canvas-type", dest="canvas_type", default=None,
                    help="list_agents: 过滤 canvas_type（默认 combo）")
    ap.add_argument("--first-prompt", dest="first_prompt", default=None,
                    help="create_session: 建好会话后立即派发的首条指令（一步建并驱动）")
    ap.add_argument("--allow-duplicate", dest="allow_duplicate", action="store_true",
                    help="create_session: 强制新建（默认复用该 agent 已有 session）")
    ap.add_argument("--raw", action="store_true",
                    help="JSON 输出不 pretty-print")
    ap.add_argument("--insecure", action="store_true",
                    help="忽略 TLS 校验（仅调试）")
    args = ap.parse_args()

    tok = load_token()
    if not tok.get("server") or not tok.get("auth_token"):
        sys.exit(f"[ERR] token 文件字段不完整: {TOKEN_PATH}")

    # ⚠️ 显式拒绝任何写/删类动作，即使 token 技术上能调那些端点。
    # 这是 skill 层的产品策略，与服务端白名单无关。
    # 放行的写动作：dispatch_task（向已有 session 排队执行）、upload（灌文件进 KB）、
    # install_skill（装技能进个人库）、create_session（为 agent 新建会话）。
    # 其余 rm/save/update/delete… 一律拒（注意 "create" 仍禁，create_session
    # 是显式放行的具体动作，与裸 "create" 不同）。
    _BANNED_ACTIONS = frozenset({
        "rm", "delete", "remove", "save", "create", "update", "patch", "put",
        "copy_kb_document", "register_artifact",
    })
    if args.action in _BANNED_ACTIONS or any(
        args.action.startswith(p) for p in ("rm_", "delete_", "remove_")
    ):
        sys.exit(
            f"[ERR] 拒绝执行写操作 '{args.action}'。"
            "graft-comboagent 只放行 dispatch_task / upload 两个写动作；"
            "其余写/删请走前端 UI。"
        )

    if args.action == "download":
        do_download(args, tok)
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
    else:
        do_unified(args, tok)


if __name__ == "__main__":
    main()
