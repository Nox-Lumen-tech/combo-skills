---
name: graft-comboagent
description: "跨 Session 嫁接（远程版）：从本地 Skill 宿主通过 HTTP 访问云端 comboagent session 的执行成果。"
execution_mode: balanced
metadata:
  tags: ["cross-session", "graft", "memory", "remote"]
  emoji: "🌿"
  reserved: true
---

# Graft-Comboagent — 跨 Session 嫁接（本地版）

> 这是服务器端 `AgentFlow/src/skills/builtin/graft` 的本地镜像。
> 所有 action 行为与服务器端完全一致；区别仅在于你通过 `scripts/call.py` 走 HTTPS 调用远程 ragbase，而不是直接调用本进程的 FunctionTool。

## 远程调用方式（本地 skill 专属 — 必读）

所有命令都通过 `scripts/call.py` 发起；它会自动从 `~/.config/graft-comboagent/token.json`（或 `GRAFT_COMBOAGENT_TOKEN` 指定路径）读取本地登录态，并把 `Authorization` 头带上。

| 操作 | 命令 |
|---|---|
| 首次登录 | `python scripts/login.py`（命令行输 email + password） |
| 查看身份 | `python scripts/whoami.py` |
| 退出 | `python scripts/logout.py` |
| 发现 session | `python scripts/call.py list_sessions --query <关键词>` |
| 看 digest | `python scripts/call.py get_digest --session-id <id或名称>` |
| 取某轮 | `python scripts/call.py get_round --session-id <x> --round-id 5` |
| 跨 session 搜 | `python scripts/call.py search --query <kw> --session-id "*" --source round` |
| 读产出物（文本） | `python scripts/call.py read_file --path workspace/sessions/<sid>/<path>` |
| **下载产出物（原始字节）** | `python scripts/call.py download --path workspace/sessions/<sid>/<path> [--out <本地路径>]` |
| 列文件 | `python scripts/call.py list_files --query "workspace/sessions/<sid>/output/"` |
| 按产出物找 | `python scripts/call.py search_by_artifact --query <产出物名> --session-id <sid>` |
| 文件内全文搜 | `python scripts/call.py grep_file --query <关键词>` |

**`read_file` vs `download`**：
- `read_file`：服务端 `markitdown` 把 docx/xlsx/pdf 转成 **markdown 文本** → 适合 AI 直接阅读、截取片段
- `download`：服务端 **原始字节流** → 适合用 Office 打开、用 pandas/openpyxl 读 xlsx、用户拿"原文件"

## 上下文节流规则（必读）

1. **默认只调 `get_digest`**，获取目录型概览（5–20K tokens）。
2. **按需 drill down**：digest 指明 Round N 有关键结论，才去调 `get_round --round-id N`。
3. **大文件落地**：`read_file` 返回的 docx/xlsx 转文本若 > 20K tokens，写入 `.graft/<slug>/artifacts/<name>`，由后续 Read 工具按需读取，**不要全文进当前上下文**。
4. **原始文件只 `download`，不读回 AI 上下文**：下载后把路径给用户/后续流程用，字节流绝不塞进 prompt。
5. **不做全量拖库**：禁止循环拉所有 round / 所有 artifact。

## 核心能力

三个操作点，完全对齐 kb_ids/doc_ids 的已有模式：

**① 发现：`list_sessions` action**（对应 `list_documents`）
```
python scripts/call.py list_sessions --query 冷却
```
→ 返回可见 session 列表（自己的 + 共享的），支持名称关键词过滤

**② 全貌：`get_digest` action**（先看目录再取数据）
```
python scripts/call.py get_digest --session-id 冷却系统分析
```
→ 返回该 session 的完整执行摘要表（每轮做了什么、产出了什么、状态如何）

**③ 使用：`session_id` 参数**（对应 `kb_ids`/`doc_ids`，支持 ID 和名称）
```
python scripts/call.py get_round --session-id 冷却系统分析 --round-id 5
```
→ 名称自动解析为 ID（同 `_resolve_kb_ids` 模式）

## 使用流程

### Step 0（可选）: 不确定有哪些 session → 列表发现

```
python scripts/call.py list_sessions --query 冷却
```
→ 返回匹配的 session 列表（session_id + 名称 + Agent 名 + 最近更新时间）

如果用户已经说了 session 名称，可以跳过此步直接传名称。

### Step 1: 获取 Digest — 看全貌

```
python scripts/call.py get_digest --session-id 冷却系统分析
```
→ 返回该 session 的完整执行摘要，从中了解：做了几轮、每轮做了什么、产出了哪些文件、最终结论在哪一轮。

**Digest 是目录，不是数据。** 需要精确内容时，用 Digest 中的线索（round_id、artifact 名称）去取回原始记录。

### Step 2: 根据 Digest 精确取回

根据 Digest 中的线索选择检索方式：

| 需要什么 | 用什么 |
|---------|--------|
| 某轮的完整输出 | `call.py get_round --round-id N --session-id X` |
| 某几轮的概要 | `call.py get_round --round-id 1 --end-round 10 --session-id X` |
| 某个产出物内容（文本） | `call.py search_by_artifact --query <产出物名> --session-id X` |
| 某个产出物文件（文本） | `call.py read_file --path <文件路径> --session-id X` |
| 某个产出物文件（**原始字节**） | `call.py download --path <文件路径> --session-id X --out ./file.docx` |
| 按关键词搜索 | `call.py search --source round --query <关键词> --session-id X` |

**不确定名称，用 "*" 广搜**：
```
python scripts/call.py search --source round --query "冷却系统测试结论" --session-id "*"
```
→ 跨全部可见 session 搜索，结果附带 session_name

跨 session 拿到的内容在本地分析上下文中使用；**产出物不要通过本 skill 写回云端**（graft 只读，写回请走对应 session 自己的 agent）。

详见 → `references/cross-session-retrieval.md`

## 与本地代码结合（典型场景）

> "对照云端 session 'ASPICE 分析' 的结论，审查本地 `src/` 下的代码，找出未覆盖的 SRS 需求。"

推荐执行路径：
```
1. list_sessions --query ASPICE     → 定位 session
2. get_digest --session-id <ID>     → 看全貌、哪几轮有结论
3. (按需) get_round --round-id N    → 拿某轮精确输出
4. (按需) download --path ...       → 如果用户要原始 docx，下载到 .graft/downloads/
5. 本地 Read/Grep 扫 src/           → 对照结论做 gap 分析
6. 产出比对报告到本地文件
```

**不要**把 session 的 10+ 轮全部 `get_round` 下来塞进上下文 —— 用 Digest 指路，按需取回。

## 规则

- 用户说了 session 名称 → 直接传名称（自动解析）
- 不确定有什么 → 先 list_sessions 发现，再用名称或 ID 操作
- 不确定是哪个 session → `--session-id "*"` 广搜
- **先 Digest 后 drill down** — 不要盲搜，先看全貌再定点取回
- 名称匹配多个 session 时向用户确认，不要自行选择
- 可见范围包括自己的 session 和团队共享 Agent 的 session
- Graft **只读**，不会修改目标 session 的任何数据；写操作在服务端被白名单拦截
- 原始字节文件只走 `download`，不读进 AI 上下文

## 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| `[ERR] 未登录` | token 文件不存在 | `python scripts/login.py` |
| `HTTP 401 / 认证失效` | access_token 被重置（别处 login 过） | 重新 `python scripts/login.py` |
| `Access denied` | 目标 session 不在你的可见范围 | 确认 owner / 共享关系；换 `session_id` |
| `File not found: ...` | path 拼错或文件不存在 | 先 `list_files` 或 `grep_file` 确认路径 |
| `Action ... not allowed via graft` | 误用了写 action（copy_kb_document / register_artifact） | graft 只读，换 action |
