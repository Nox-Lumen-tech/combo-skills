---
name: graft-comboagent
description: "本地 agent 的 ragbase 远程客户端：直接查云端知识库（语义检索 / 列文档 / 翻 chunk）、嫁接已有 session 的执行成果，以及向已有 session 派发任务（dispatch）。"
execution_mode: balanced
metadata:
  tags: ["ragbase", "kb-retrieval", "rag", "cross-session", "graft", "memory", "remote", "dispatch"]
  emoji: "🌿"
  reserved: true
---

# Graft-Comboagent — ragbase 远程客户端

本地 agent（Cursor / Claude Code / Codex）通过本 skill 直连云端 ragbase，做三件事：

| 用途 | 说明 | 写入云端？ | 是否需要云端先跑过 session |
|---|---|---|---|
| **A. KB 检索**（核心高频） | 列我有哪些 KB → 在 KB 里做语义检索 → 把命中 chunks 拉回本地给当前 agent 当 RAG 上下文 | 否 | 不需要 |
| **B. Session 嫁接** | 拉某次 comboagent 跑出来的 digest / round / 产出物，对照本地代码做分析 | 否 | 需要 |
| **C. 派发任务** | 把指令派给已存在的某个 session，让云端 agent 排队跑一轮（异步） | 触发执行（不创建/删除资源） | 需要（目标 session 必须已存在） |

> 服务端实现在 `AgentFlow/src/skills/builtin/graft` 与 `api/apps/graft_app.py` / `api/apps/kb_app.py`。
> 本 skill 是这些 HTTP 端点的本地包装。**写边界很窄**：除 `dispatch_task` 外，所有命令均为只读。

> 🌳 **不知道用哪条 action？先查 [`references/action-decision-tree.md`](references/action-decision-tree.md)** —— 按"用户意图"分类的 9 分支决策树，本地 LLM 1 秒选中。

## 远程调用方式（本地 skill 专属 — 必读）

所有命令都通过 `scripts/call.py` 发起；它会自动从 `~/.config/graft-comboagent/token.json`（或 `GRAFT_COMBOAGENT_TOKEN` 指定路径）读取本地登录态，把 `Authorization` 头带上。

### 0. 配置 server（多租户 / 自部署 — 一次就够）

**默认** `https://xipnex.nox-lumen.com`（公有云）。自部署 / 内网 / 临时 cloudflare tunnel 用 `python scripts/login.py --server <URL>` 或 `GRAFT_COMBOAGENT_SERVER=<URL>` 覆盖一次即可——server 会和 token 一起持久化到 `~/.config/graft-comboagent/token.json`，之后所有 `call.py` 自动指向它。

**用户丢一条完整 signin URL 时，agent 自己拆**：例如
`https://katrina-simpson-welfare-funeral.trycloudflare.com/zh/signin?email=test-syncore%40nox-lumen.com&password=syncore`
应拆成：
- `--server https://katrina-simpson-welfare-funeral.trycloudflare.com`（去掉 `/zh/signin` path 和整个 query）
- `--email test-syncore@nox-lumen.com`（URL-decode：`%40`→`@`、`%20`→空格 等）
- `--password syncore`

然后一行直接登录（无需交互）：

```bash
python scripts/login.py --server <URL> --email <email> --password <pwd>
```

### A. KB 检索（最常用，先看这里）

| 操作 | 命令 |
|---|---|
| **我有哪些 KB** | `python scripts/call.py list_kbs` |
| 按名字搜 KB | `python scripts/call.py list_kbs --keywords ASPICE` |
| KB 详情 | `python scripts/call.py kb_detail --kb-id <kb_id>` |
| **在 KB 里语义检索**（核心 RAG 入口） | `python scripts/call.py search --source document --query "传感器精度要求" --kb-ids <kb_id> --top-k 3` |
| 列 KB 里的文档 | `python scripts/call.py list_documents --kb-ids <kb_id>` |
| 看文档元信息 | `python scripts/call.py get_doc_profile --doc-ids <doc_id>` |
| 翻文档 chunks（顺序） | `python scripts/call.py list_chunks --doc-ids <doc_id> --offset 0 --limit 20` |
| **取某些 chunks（精确 + 上下文窗口）** | `python scripts/call.py list_chunks --chunk-ids <id1>,<id2> --window 1` ← 返回目标 chunk + 前后各 1 个同文档 chunk，`is_target=true` 标命中 |

`search --source document` 走的是 ragbase 的混合检索（向量 + 全文 + reranker），等同于前端 KB 测试页的"提问"入口。

### B. Session 嫁接

| 操作 | 命令 |
|---|---|
| 首次登录 | `python scripts/login.py`（命令行输 email + password） |
| 查看身份 | `python scripts/whoami.py` |
| 退出 | `python scripts/logout.py` |
| 发现 session | `python scripts/call.py list_sessions --query <关键词>` |
| 看 digest | `python scripts/call.py get_digest --session-id <id或名称>` |
| 取某轮 | `python scripts/call.py get_round --session-id <x> --round-id 5` |
| 跨 session 搜 | `python scripts/call.py search --query <kw> --session-id "*" --source round` |
| 读产出物（文本，整页） | `python scripts/call.py read_file --path workspace/sessions/<sid>/<path>` |
| 读产出物（指定行范围） | `python scripts/call.py read_file --path <p> --line-start 100 --line-end 200` |
| 读产出物（围绕某行取 ±N 行） | `python scripts/call.py read_file --path <p> --center-line 500 --context-lines 50` |
| **文件内搜索定位**（精确） | `python scripts/call.py read_file --path <p> --find "关键词" --find-context 5 --max-find-matches 3` ← 比 grep_file 准；返回每处命中 + 前后 N 行上下文 |
| **下载产出物（原始字节）** | `python scripts/call.py download --path workspace/sessions/<sid>/<path> [--out <本地路径>]` |
| 列文件 | `python scripts/call.py list_files --query "workspace/sessions/<sid>/output/"` |
| 按产出物找 | `python scripts/call.py search_by_artifact --query <产出物名> --session-id <sid>` |
| 文件名模糊搜 | `python scripts/call.py grep_file --query <文件名关键词>` |

### C. 派发任务（dispatch_task）

向**已存在**的某个 session 派一条新指令，云端会异步跑一轮，HTTP 立即返回。

| 操作 | 命令 |
|---|---|
| 派发任务（异步） | `python scripts/call.py dispatch_task --session-id <名称或UUID> --prompt "请把附件总结成中文要点"` |
| 轮询执行进度（轻量） | `python scripts/call.py list_sessions --query <名字片段>` 看 `updated_at` 是否前进 |
| 看新一轮内容（重量） | `python scripts/call.py get_digest --session-id <sid>` 看 digest 是否多出新 round |
| 找新轮号 | `python scripts/call.py search --source round --query <派发 prompt 关键词> --session-id <sid>` 命中里的 `round` 字段就是 round_id |
| 取某轮完整内容 | `python scripts/call.py get_round --session-id <sid> --round-id <N>` （多 epoch session 加 `--epoch <E>`） |

**节奏建议**：
- 重 agent（ASPICE / 多步 plan）单轮 1–5 分钟很正常，**轮询间隔 30s ~ 1min**，不要每秒一次
- `updated_at` 前进 ≠ 新 round 已写入：agent 在某一轮中间也会前进 `updated_at`；要等 round finalize 入库才能 `get_round` 到

**dispatch 与"创建 session"不同**：

- ✅ 只能派发到**已存在**的 session（owner 或共享给你的）
- ✅ 不创建任何新 session、文件、记录
- ✅ 服务端复用既有的 `_DISPATCH_SEMAPHORE` 做并发控制
- ❌ HTTP 派发**不支持 wait=True**（本地没有 source session 可挂起）；要等结果就用 `get_digest` / `get_round` 轮询
- ❌ 不能用来批量派发 / 创建 session（那是产品功能，不是 skill 能做的）

⚠️ **依赖后端部署**：`/v1/graft/dispatch_task` 是新加的端点，需要后端跑了带这个改动的版本。如果返回 `[ERR] Not Found`，说明目标 server 还没部署。已部署能力（list_kbs / search / get_digest 等）不受影响。

典型用途：本地 agent 决定"这个 KB 检索结果不够，要让云端某个长跑 session 重新跑一轮带上新指令" → 派任务回去 → 用 `get_digest` 看新一轮产出。

### D. search 高级过滤（小众但 unified_search 支持）

`search` action 除了 `--query / --kb-ids / --doc-ids / --top-k / --source`，还透传：

| 参数 | 用途 | 示例 |
|---|---|---|
| `--time-start` / `--time-end` | 时间范围（ISO 8601） | `search --source round --query "decision" --time-start 2026-04-01T00:00:00 --time-end 2026-04-15T23:59:59` |
| `--speaker` | 按发言人过滤 | `search --source round --speaker "Assistant"` |
| `--chat-id` | 渠道群聊 ID（仅 `--source channel_history` 用） | `search --source channel_history --chat-id oc_xxx --query "升级"` |

> 这些参数和上面 A/B 节里的命令可以**任意组合**——本 skill 把所有非 dispatch / 非 KB-only 字段透传给 unified_search，用法对齐云端 agent 工具签名（详见 `AgentFlow/src/memory/memory_os.py::create_tool`）。

### 严格只读边界（除 dispatch_task 外）

`call.py` 在分发前会拒绝任何 `rm` / `delete` / `remove` / `save` / `create` / `update` / `patch` / `put` 类 action，以及服务端禁用的 `copy_kb_document` / `register_artifact`。即便你的 token 在技术上能调那些端点，本 skill 也不给入口。**写/删请走前端 UI**。

`dispatch_task` 是**唯一**的写类入口：它仅向已有 session 排队一次执行，不修改 / 创建 / 删除任何持久化资源。

**`read_file` vs `download`**：
- `read_file`：服务端 `markitdown` 把 docx/xlsx/pdf 转成 **markdown 文本** → 适合 AI 直接阅读、截取片段
- `download`：服务端 **原始字节流** → 适合用 Office 打开、用 pandas/openpyxl 读 xlsx、用户拿"原文件"

## 响应结构（必读 — 别看错了字段）

ragbase 后端把"给 LLM 看的内容"和"给前端调度看的元数据"放在不同字段。本 skill 透传，所以解析时记住：

| 字段 | 含义 | 谁该读 |
|---|---|---|
| `content` | 真正给 AI 看的正文（chunks/markdown/JSON 字符串） | **AI / 你**：这是核心数据 |
| `metadata.items` | 结构化元信息列表（session 表、文档表、文件表、search 命中表） | **AI / 你**：取 ID / score / 路径 |
| `metadata.usage_hint` | 服务端给的"下一步建议"（带样例 unified_search 调用） | **AI / 你**：可以参考但别盲从 |
| `metadata.budget_remaining` / `budget_used` | 本次返回消耗的 token 预算 | 跳过即可 |
| `compressible` / `flush_group` | autogen 的 ToolCallSummaryMessage 调度字段 | **不是数据**，跳过 |
| `batch_hint` | "先写后读"提示，**面向云端 agent**（要它 write_file 持久化） | **本地调用直接忽略** |
| `continuation_hint` | "续读 offset=N"的 unified_search 写法提示 | 翻页时参考 |

最常见错误：把 `content` 当成 wrapper、跳过它去看 metadata，结果丢掉真正的数据。

## 上下文节流规则（必读）

1. **默认只调 `get_digest`**，获取目录型概览（5–20K tokens）。
2. **按需 drill down**：digest 指明 Round N 有关键结论，才去调 `get_round --round-id N`。
3. **`search --source document` 控顶**：本地 RAG 用法 `--top-k 3-5`（不要默认 10），单 chunk 几百字 × top-k = 上下文炸。
4. **大文件落地**：`read_file` 返回的 docx/xlsx 转文本若 > 20K tokens，写入 `.graft/<slug>/artifacts/<name>`，由后续 Read 工具按需读取，**不要全文进当前上下文**。
5. **原始文件只 `download`，不读回 AI 上下文**：下载后把路径给用户/后续流程用，字节流绝不塞进 prompt。
6. **不做全量拖库**：禁止循环拉所有 round / 所有 artifact。
7. **翻页要明确**：`list_chunks` / `read_file` 默认每次几 KB，必须传 `--offset` 才能继续；不要无限翻完整本书塞进上下文。

## 使用流程

### 流程 A：把云端 KB 当 RAG 用（不需要任何 session）

```
1. list_kbs                                              → 我能看到哪些 KB
2. (可选) kb_detail --kb-id <id>                         → 看 KB 大小、embedding 模型、parser 配置
3. search --source document --query "..." --kb-ids <id> --top-k 3-5
                                                         → 语义检索，命中 chunks 直接返回
4. (按需) list_chunks --doc-ids <doc_id> --offset 0      → 拿同一份文档的更多上下文（翻页）
5. 本地 agent 拿 chunks 做推理 / 写代码 / 答复用户
```

**不要做的事**：拿到一个 doc_id 后无脑 `list_chunks` 翻完整本书—— `read_file` 同一份文档可能更省 token，且不要超过 `--limit` 默认。

### 流程 B：嫁接已有 session 成果做对照分析

```
1. list_sessions [--query <关键词>]   → 定位 session（看 metadata.items）
2. get_digest --session-id <id|name>  → 看全貌（13 轮做了什么、产出了哪些文件、最终结论在第几轮）
3. 按需取回：
     get_round --round-id N           → 某一轮完整输出（多 epoch session 加 --epoch E）
     get_round --round-id 1 --end-round 10 --session-id X   → 多轮概要
     search_by_artifact --query <产出物名>   → 找产出物内容
     search --source round --query <kw> --session-id X       → 关键词搜索本 session
     read_file --path workspace/sessions/<sid>/...           → 读产出物文本（markdown 化）
     download --path workspace/sessions/<sid>/...            → 取原始字节文件（docx/xlsx 等）
4. 本地 Read/Grep 扫 src/ → 对照 session 结论做分析 / 比对
```

**Digest 是目录，不是数据**：digest 表里 R7 显示 `工具: execute_code×12`，不要由此推断"R7 跑了 12 个工具实例必须看每一个"。要看实际 reasoning 才 `get_round`。

**不确定 session 名 → 用 `*` 广搜**：

```
python scripts/call.py search --source round --query "F1 score 结论" --session-id "*"
```

→ 跨所有可见 session 搜，命中里带 `session_name`，再切到具体 session 走 digest。

详见 → `references/cross-session-retrieval.md`

### 流程 C：派发新任务给已有 session（dispatch）

```
1. list_sessions --query <session 名>          → 看 session 是否存在
2. (推荐) get_digest --session-id <id|name>    → 看当前状态、原 episode 最大 round
3. dispatch_task --session-id <名称或UUID> --prompt "..."
                                               → 异步排队，HTTP 立即返回
                                               → 注意 INFO 里会打印名称→UUID 的解析结果
4. 等 30s ~ 数分钟（重 agent 单轮可能 3–5 分钟；ping 类轻 prompt 30–90s）
5. 轮询找新 episode（**关键**：用 search，不要用 get_round 直接试 N+1）：
     search --source round --query <prompt 关键词> --session-id <sid> --top-k 5
                                               → 顶部命中带新 episode_id 前缀
                                               → episode_id 看 chunk id：ep_<sid>_<EPISODE>_e<E>_r<R>
6. (可选) get_round --session-id <sid> --round-id <R> --epoch <E>
                                               → 取整轮原文（注意：跨 episode 的 round 编号会重置）
```

**dispatch 不是"创建会话再聊天"**——目标 session 必须已存在；不能用 `*` 广派；prompt ≤ 32 KB。

**最关键的一条 — episode 模型（容易踩坑）**：

dispatch 在已有 session 里**起一个新 episode**（独立的执行任务），新 episode 从 **R1 开始**，**不是**在原 episode 上续 R14。所以：

- ❌ 错：dispatch 后用 `get_round R<原最大+1>` 找新内容
- ✅ 对：dispatch 后用 `search --source round --query <prompt 关键词>`，命中的 `id` 字段形如 `ep_<sid>_<EPISODE>_e<epoch>_r<round>`，新 episode 的 hash 跟原 episode 不同

**`updated_at` 前进 ≠ round 已写入**：agent 在某一轮中间会前进 `updated_at`，但 round 必须 finalize 才能 search/get_round 到。

**round_id 边界**：
- 服务端**不识别 `--round-id -1` 表示"最新轮"**（会被当成 `None`，报"需要 round_id 参数"）
- 拿不到具体 round_id 时，用 `search --source round` 命中里的 `round` 字段

## 通用规则

- 用户说了 KB / session 名称 → 直接传名称（自动解析为 ID）
- 不确定有什么 → 先 `list_kbs` / `list_sessions` 发现，再用名称或 ID 操作
- session 不确定是哪个 → `--session-id "*"` 广搜（仅 search action 支持）
- **先 Digest 后 drill down** — 不要盲搜，先看全貌再定点取回
- 名称匹配多个 KB / session 时向用户确认，不要自行选择
- 可见范围包括自己的资源 + 团队共享的资源（list 接口已自动合并）
- 除 `dispatch_task` 外其余命令**只读**，不会修改云端任何数据；写操作在服务端白名单拦截
- 原始字节文件只走 `download`，不读进 AI 上下文
- **不要把 `dispatch_task` 当成 fire-and-forget 的批量分发**：每次调用都消耗云端 agent 资源（CPU + LLM token）

## 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| `[ERR] 未登录` | token 文件不存在 | `python scripts/login.py` |
| `HTTP 401 / 认证失效` | access_token 被重置（别处 login 过 / 长期未用过期） | 重新 `python scripts/login.py` |
| 所有命令一致 401 / Not Found / DNS / 连接错误 | server URL 不对（默认指向公有云，但你账号在自部署）；或 cloudflare tunnel 已换地址 | `python scripts/whoami.py` 看当前 server；不对就 `logout.py && login.py --server <你的真实 server>` |
| `whoami 显示有 token，但任何 call.py 都 401` | whoami **只读本地文件不验证服务端**，token 实际已失效 | 重新 `login.py`，不要信 whoami |
| `Access denied` | 目标 session 不在你的可见范围 | 确认 owner / 共享关系；换 `session_id` |
| `File not found: ...` | path 拼错或文件不存在 | 先 `list_files` 或 `grep_file` 确认路径 |
| `Action ... not allowed via graft` | 误用了写 action（copy_kb_document / register_artifact） | graft 只读，换 action |
| `Round N, Epoch 1 未找到` | 多 epoch session 时 round 编号跨 epoch；或 round 还没 finalize 入库 | 加 `--epoch <E>`；或先 `get_digest` / `search --source round` 确认 (epoch, round) |
| `get_round 需要 round_id 参数`（传了 `--round-id -1`） | 服务端**不支持** `-1` 表示"最新轮"；它把 `-1` 当 `None` | 用 `search --source round` 找命中里的 `round` 字段；或 `get_digest` 看最大 round 后再传具体值 |
| `dispatch_task` 返回 ok 但 `get_round R<原最大+1>` 始终未找到 | **dispatch 起新 episode，R 从 1 重新开始**（不在原 episode 续号） | 改用 `search --source round --query <prompt 关键词>`，看命中的 `round` 和 episode prefix |
| `dispatch_task` 返回 ok 但 `get_round R<N>` 一段时间内仍未找到 | round 还在跑（pre-investigation/reasoning 未 finalize） | 等 30s ~ 数分钟；用 `search --source round` 比 `get_round` 更早能看到内容 |
| dispatch 调用 `[ERR] target session not found: <name>`（call.py 报错） | 名称未命中或解析多义 | 本地 skill 已自动做 `list_sessions(query=name)` 解析；0 命中 → 名字打错；多命中 → 改用 UUID |
| `list_kbs` 返回 `create_date / update_date` 全是 null | 后端 `/v1/kb/list` 不投影时间 | 要看时间走 `kb_detail`（返回 `create_time` / `update_time` 毫秒戳） |
| `batch_hint` 提示"先写后读" | 面向**云端 agent** 的 hint，本地不适用 | 直接忽略 |
| `[ERR] dispatch_task 需要 --session-id` | 漏传目标 session | 加 `--session-id <sid>`；不能用 `*` |
| `[ERR] permission denied for session ...` | 派发的 session 不在你的可见范围 | 检查 owner / 共享关系；先 `list_sessions` 确认 |
| `[ERR] target session not found` | session id 写错或已被删 | `list_sessions --query` 找正确 id |
| `[ERR] Not Found`（dispatch_task 调用） | 后端没部署 `/v1/graft/dispatch_task` 端点 | 确认目标 server 跑的是带新端点的版本；其他命令不受影响 |
| `prompt too long: ... > 32768` | dispatch 的 prompt 超过 32 KB 上限 | 缩减 prompt 或拆成多次 dispatch |
