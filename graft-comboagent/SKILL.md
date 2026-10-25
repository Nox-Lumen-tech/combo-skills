---
name: graft-comboagent
description: "本地 agent 的 ragbase 远程客户端：查云端 KB、嫁接 session、派发任务，以及 KB chunk 定点修补（Excel 超链接等，无需改 parse）。"
execution_mode: balanced
metadata:
  tags: ["ragbase", "kb-retrieval", "rag", "cross-session", "graft", "memory", "remote", "dispatch"]
  emoji: "🌿"
  reserved: true
---

# Graft-Comboagent — ragbase 远程客户端

本地 agent（Cursor / Claude Code / Codex）通过本 skill 直连云端 ragbase，做这些事：

| 用途 | 说明 | 写入云端？ | 是否需要云端先跑过 session |
|---|---|---|---|
| **A. KB 检索**（核心高频） | 列我有哪些 KB → 在 KB 里做语义检索 → 把命中 chunks 拉回本地给当前 agent 当 RAG 上下文 | 否 | 不需要 |
| **B. Session 嫁接** | 拉某次 comboagent 跑出来的 digest / round / 产出物，对照本地代码做分析 | 否 | 需要 |
| **C. 派发任务** | 把指令派给已存在的某个 session，让云端 agent 排队跑一轮（异步） | 触发执行（不创建/删除资源） | 需要（目标 session 必须已存在） |
| **D. 上传到 KB**（`upload`） | 把本地文件灌进**指定 KB**，可选触发解析；本地的 findings / 缺陷 / 报告回流云端 KB | **是**（入库；仅限你有权限的 KB） | 不需要 |
| **E. 安装 skill**（`install_skill`） | 把本地 skill 目录（SKILL.md + scripts/references）打包装进**你自己**的云端技能库；git 可选 | **是**（写入 skills/users/你/） | 不需要 |
| **F. 列 agents**（`list_agents`，辅助） | 列出你名下的 combo agents（bot），拿 `agent_id` 去建会话 | 否 | 不需要 |
| **G. 创建 session**（`create_session`） | 为指定 agent 新建会话；可 `--first-prompt` 一步建好并派发首轮，与 dispatch_task 形成"本地建会话→驱动执行"闭环 | **是**（建会话记录） | 不需要 |
| **H. 接线脚本工具**（`wire_script_tools`） | 把**已装的、无 `skill.manifest.json`** 的 skill 里的脚本，升级成工具池可点名调用的**动态工具**；底层就是 dispatch_task 派一段"接线"指令给已有会话，由云端 agent 自编程注册（零核心改动） | 触发执行（agent 写 registry.json + wrapper，不建/删资源） | 需要（目标 session 必须已存在） |
| **I. KB chunk 修补**（`download_document` / `patch_chunk` 等） | 云端 parse 缺内容（如 Excel 超链接）时：**下载原文件 → 本地补文字 → 写回 chunk 并 re-embed**；不依赖改容器 parser | **是**（改 ES chunk；`delete_chunks` / `create_chunk` 可选） | 需要（doc 已上传并 parse 过） |
| **J. 记忆**（`record` / `memories` / `team_memory` / `team_curate`） | 用户说记住才写入「我的记忆」；需要时拉个人/团队记忆；人决定把哪条提交到团队候选池；团队所有者在本地就能审候选池 | **`record` 写个人记忆**；**`team_memory --op share/revoke` 写候选池**；**`team_curate --op approve/reject/demote/merge/rewrite/policy` 改团队库（仅所有者）**；`memories` / `--op teams` / `--op pending/list` 只读 | 不需要 |

> 服务端实现在 `AgentFlow/src/skills/builtin/graft` 与 `api/apps/graft_app.py` / `api/apps/kb_app.py` / `api/apps/chunk_app.py` / `api/apps/document_app.py`；`upload` 直接复用 `/v1/document/upload`，chunk 写口复用 `/v1/chunk/set|create|rm|list`，`download_document` 复用 `/v1/document/get/<doc_id>`。
> **写边界**：`dispatch_task` / `upload` / `install_skill` / `create_session` / **`patch_chunk` / `create_chunk` / `delete_chunks`** / **`record`** / **`team_memory`（share / revoke）** / **`team_curate`（approve / reject / demote / merge / rewrite / policy，仅团队所有者）**。`wire_script_tools` 仍复用 dispatch。不要用 `upload --parse` 或前端 re-parse 来「修链接」——会走旧 parser 并**覆盖**已 patch 的 chunk。云端 Agent 的 metadata 重打标（`kb_parse`+`metadata_spec`）同样是 run=1 重解析，也会覆盖 patch——派发打标任务前先看该 doc 有没有未固化的 patch。

> 🌳 **不知道用哪条 action？先查 [`references/action-decision-tree.md`](references/action-decision-tree.md)** —— 按"用户意图"分类的决策树，本地 LLM 1 秒选中。
>
> 🔍 **KB 检索老搞错？先读 [`references/kb-retrieval-logic.md`](references/kb-retrieval-logic.md)** —— `search` vs `offset` vs `chunk-ids` 的语义、大文档边界、agent 反模式（**必读**）。

## 远程调用方式（本地 skill 专属 — 必读）

所有命令都通过 `scripts/call.py` 发起；它会自动从 `~/.config/graft-comboagent/token.json`（或 `GRAFT_COMBOAGENT_TOKEN` 指定路径）读取本地登录态，把 `Authorization` 头带上。

### 0. 配置 server（多租户 / 自部署 — 一次就够）

**默认** `https://xipnex.nox-lumen.com`（公有云）。自部署 / 内网 / 临时 cloudflare tunnel 用 `python scripts/login.py --server <URL>` 或 `GRAFT_COMBOAGENT_SERVER=<URL>` 覆盖一次即可——server 会和 token 一起持久化到 `~/.config/graft-comboagent/token.json`，之后所有 `call.py` 自动指向它。

> ⚠️ **切 server 一律走 `login.py` 重登，绝不要手改 `token.json` 的 `server` 字段**：手改只换了地址、`auth_token` 还是旧 server 登的那个，仅在两端碰巧共用同一数据库时才凑效，否则直接 401，还会留下不一致状态。换环境 = `login.py --server <新URL>` 重登一次即可。

**官方获取入口**：用户在 [`https://xipnex.nox-lumen.com/combospace/user-setting/skills`](https://xipnex.nox-lumen.com/combospace/user-setting/skills) 可以查看/复制属于自己的 combo-agent 访问地址。如果用户没明确说用哪个 server，agent 应先建议他从这里复制。

**用户丢一条完整 signin URL 时，agent 自己拆**：例如
`https://katrina-simpson-welfare-funeral.trycloudflare.com/zh/signin?email=test-syncore%40nox-lumen.com&password=<password>`
应拆成：
- `--server https://katrina-simpson-welfare-funeral.trycloudflare.com`（去掉 `/zh/signin` path 和整个 query）
- `--email test-syncore@nox-lumen.com`（URL-decode：`%40`→`@`、`%20`→空格 等）
- `--password <password>`（从 query 原值取，URL-decode 后用）

然后一行直接登录（无需交互）：

```bash
python scripts/login.py --server <URL> --email <email> --password <pwd>
```

**链接里没带 email/password 时，HIL 问用户，不要瞎猜**：如果用户给的 URL 是 `https://xipnex.nox-lumen.com/combospace/user-setting/skills` 这种**纯页面链接**（没有 query string，或 query 里只有 server 信息），agent 只能拆出 server，**email 和 password 必须停下来问用户索要**——不要拿历史对话、配置文件、环境变量里的别人账号去登。

### A. KB 检索（最常用，先看这里）

| 操作 | 命令 |
|---|---|
| **我有哪些 KB** | `python scripts/call.py list_kbs` |
| 按名字搜 KB | `python scripts/call.py list_kbs --keywords ASPICE` |
| KB 详情 | `python scripts/call.py kb_detail --kb-id <kb_id>` |
| **语义检索**（自然语言、找相关） | `python scripts/call.py search --source document --query "传感器精度要求" --kb-ids <kb_id> --top-k 3` |
| **精确检索**（ID/编号/原文短语，要"必含") | `python scripts/call.py search --source document --query "1023265" --doc-ids <doc_id> --exact` ← 关向量 + 正文子串必含 |
| 列 KB 里的文档 | `python scripts/call.py list_documents --kb-ids <kb_id>` |
| 看文档元信息 | `python scripts/call.py get_doc_profile --doc-ids <doc_id>` |
| **语义检索命中后取全文（默认）** | `python scripts/call.py list_chunks --chunk-ids <16hex> --window 0` ← search 的 `metadata.items[].chunk_id`；**大文档 / 高页 chunk 唯一可靠路径** |
| 取 chunk + 同 doc 邻接上下文（小文档） | `python scripts/call.py list_chunks --chunk-ids <id1>,<id2> --window 1` |
| 从文档**开头**顺序翻 chunk（仅小 doc） | `python scripts/call.py list_chunks --doc-ids <doc_id> --offset 0 --limit 20` ← `offset`=chunk 序号游标，**不是 PDF 页码**；>~10000 chunks 时勿用此路找深页内容 |
| **下载 KB 文档原文件**（xlsx/docx 字节） | `python scripts/call.py download_document --doc-id <doc_id> [--out ./local.xlsx]` |
| **读 chunk 正文（含 content，适合 patch 前）** | `python scripts/call.py list_doc_chunks --doc-id <doc_id> [--page 1 --page-size 30]` |
| **改一条 chunk + 云端 re-embed** | `python scripts/call.py patch_chunk --doc-id <id> --chunk-id <id> --content "补全后的正文"` |
| 单条 chunk 详情 | `python scripts/call.py get_chunk --chunk-id <id>` |

`search --source document` 走的是 ragbase 的混合检索（向量 + 全文 + reranker），等同于前端 KB 测试页的"提问"入口。

**检索 self-awareness（摘要）**：

1. **先判定检索模式**：已知编号/ID/原文短语 → `search --exact`；问题描述/找相关 → 混合 `search`。禁止用混合 `search` 查 ID 后断言「不存在」。
2. **定位用 `search`，全文用 `--chunk-ids --window 0`** — search 只给 snippet；写结论 / 对 step 编号 / 查引用必须第二步取全文。
3. **`offset` 是 chunk 列表游标，不是 PDF 页码** — 不能靠加大 offset「翻到 page 3000+」。
4. **大文档（如 SWTD ~10000+ chunks）禁止 `--doc-ids --offset` 扫库** — 深页内容用 `search` 拿 `chunk_id` 再 `--chunk-ids`。
5. **`--exact` 仍 0 命中** — 不要断言文档无此内容；提示 parse 可能漏索引（见 `kb-retrieval-logic.md` §9）。
6. **`--time-start` / `--speaker` 只对 MemoryOS 链路生效**（`--source round` / `channel_history`）— KB 检索（`--source document`）不走 MemoryOS，这些参数被静默丢弃；记忆层（`--source memory`）也不吃。KB 收敛范围用 `--doc-ids` / `--exact`。见 §F。
7. 详见 → [`references/kb-retrieval-logic.md`](references/kb-retrieval-logic.md)

> **KB 检索走原生 API（无需 tenant_id）**：`list_documents`、`list_chunks`（KB 文档，无 `--session-id`）与 `search`（无 `--session-id`、非 round 源）在 `call.py` 内直接调 `/v1/document/list`、`/v1/chunk/list|get` 和 `/v1/chunk/retrieval_test`，与前端 KB 页同源，**不经过 graft MemoryOS**，team 共享库也能用。`list_doc_chunks` 与 `list_chunks` 底层同为 `/v1/chunk/list`，前者返回扁平 `chunks` 数组（适合 patch），后者返回 graft 兼容的 `metadata`+`content`（适合 RAG 翻页）。用户只需 `list_kbs` 拿 `kb_id`，不必手填 tenant_id。Session 嫁接类 action 仍走 `/v1/graft/memory/unified_search`。

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
- ❌ 本动作自身不创建 session（要新建会话用下面的 `create_session`）；也不做批量派发

⚠️ **依赖后端部署**：`/v1/graft/dispatch_task` 是新加的端点，需要后端跑了带这个改动的版本。如果返回 `[ERR] Not Found`，说明目标 server 还没部署。已部署能力（list_kbs / search / get_digest 等）不受影响。

典型用途：本地 agent 决定"这个 KB 检索结果不够，要让云端某个长跑 session 重新跑一轮带上新指令" → 派任务回去 → 用 `get_digest` 看新一轮产出。

### C+. 创建 session 并驱动（create_session / list_agents）

`dispatch_task` 只能派给**已存在**的 session。要从本地**新建** session 再驱动，用 `create_session`（第四个写口）；选哪个 bot 先用 `list_agents`（只读）拿 `agent_id`。

| 操作 | 命令 |
|---|---|
| **列我的 agents（bot）** | `python scripts/call.py list_agents [--keywords <名字片段>] [--limit 30]` |
| **为某 agent 建会话** | `python scripts/call.py create_session --agent-id <名称或UUID> --name "<会话名>"` |
| **一步建会话并派发首轮** | `python scripts/call.py create_session --agent-id <id> --name "<会话名>" --first-prompt "<首条指令>"` |
| 强制新建（不复用已有） | `... create_session --agent-id <id> --allow-duplicate` |

**关键约定**：
- `--agent-id` 支持 **agent 名称或 UUID**；传名称时本地用 `list_agents` 解析（0 命中报错，多命中要求更精确名称或 UUID）。
- **默认复用**：服务端 `allow_duplicate=False` 时，若该 agent 已有 session，会**返回已存在的那个**（不新建）；要每次都开新会话加 `--allow-duplicate`。
- `--first-prompt` = 建好后立即 `dispatch_task` 派发首轮（异步），返回里带 `dispatched=true` + `queued_at_ms`；之后用 `get_digest --session-id <sid>` 看新一轮概览（服务端 `get_round` 需具体 round 号，不支持 `-1`）。
- 复用前端「新建会话」同一入口（`/v1/combo_web/agents/<id>/sessions`），**是老端点、无需后端新部署**；建的 session 在前端会话列表、`list_sessions` 里都能看到。

**闭环**：`list_agents` → `create_session --first-prompt` → `get_round` 轮询——本地全程不碰前端即可开一个新会话并驱动它跑。

### D. 上传本地文件到 KB（upload — 第二个、也是唯一的"入库"写口）

把本地文件灌进**指定 KB**。典型场景：本地 agent 跑出 findings / 缺陷分析 / 报告，要回流到云端某个 KB，供后续 comboagent / 团队检索。

| 操作 | 命令 |
|---|---|
| 先找目标 KB 的 kb_id | `python scripts/call.py list_kbs [--keywords <名字>]` |
| **上传单个文件**（默认只上传不解析） | `python scripts/call.py upload --kb-id <kb_id> --file ./缺陷分析.md` |
| 上传并立即解析入库 | `python scripts/call.py upload --kb-id <kb_id> --file ./report.docx --parse` |
| 上传多个文件 | `python scripts/call.py upload --kb-id <kb_id> --file a.md --file b.xlsx --parse` |
| 上传整个目录（按模式） | `python scripts/call.py upload --kb-id <kb_id> --dir ./findings --glob "*.md" --parse` |
| 指定 parser / KB 子目录 / 改名 | `... --parser-id naive --kb-path findings/2026 --name 缺陷汇总.md` |
| 看解析进度 | `python scripts/call.py list_documents --kb-ids <kb_id>` 看每条 `run` / `progress` |

**关键约定**：
- **默认只上传不解析**。要让文件真正进检索（chunk + embedding），必须加 `--parse`（或事后在前端 KB 页点解析）。这是刻意的：避免误触发大批量解析占用云端队列。
- **并发上传**（默认 8 路，`--workers N` 调整，`--workers 1` 退回顺序）。每个请求仍是单文件，`doc_id` 与本地文件保持 1:1 对齐。整目录/几十个文件直接 `--dir` 即可；上千文件的大批量仍建议走前端 KB 或云端 Source SKILL。
- 单文件 ≤ 200 MB；超限请走前端 KB。
- 上传后本地会把 `content_hash(sha256) → local_path` 追加到 `.graft/uploads/manifest.jsonl`（可用 `--no-manifest` 关）。这是 M4 架构边界：**云端只拿文件字节，不持有任何指向你本地的路径**；本地自己存映射，便于召回云端 chunk 时跳回本地原文。
- 只能上传到**你有权限的 KB**（服务端 `upload()` 用 `current_user` 校验 KB 归属；kb_id 不存在/无权限会被拒，本地不创建任何东西）。

返回 JSON 关键字段：`uploaded[].doc_id` / `uploaded[].sha256` / `parse_triggered` / `manifest`（本地清单路径）/ `failed[]`（逐文件失败原因）。

⚠️ **依赖后端可达**：`upload` 命中的是 ragbase 主服务的 `/v1/document/upload`，和 `list_kbs` 同一个 server；如果 `list_kbs` 能通，`upload` 就能通。

### E. 安装本地 skill 到云端个人技能库（install_skill — 第三个写口）

把本地一个 skill 目录（含 `SKILL.md`，外加 `scripts/` `references/` `assets/` 等）打包上传到**你自己**的云端技能库。**git 可选**：未配置技能管理仓库也能装（直接进 MinIO `skills/users/<你>/`）；配了仓库则照旧，可事后在仓库做版本管理。

| 操作 | 命令 |
|---|---|
| **安装本地 skill 目录** | `python scripts/call.py install_skill --skill-path ./my-skill` |
| 覆盖同名已装技能 | `python scripts/call.py install_skill --skill-path ./my-skill --overwrite` |
| 允许覆盖 builtin 同名 tool（罕见） | `python scripts/call.py install_skill --skill-path ./my-skill --allow-shadow` |

**关键约定**：
- `--skill-path` 必须是**目录**，目录里直接有 `SKILL.md`；且**目录名 == SKILL.md 的 `name`**（后端 parser 强制 dir-name invariant，不一致会被拒）。
- 子目录（`scripts/` `references/` `assets/`…）会**一并打包**；`.git` / `__pycache__` / `node_modules` / `.venv` 等自动跳过。
- 默认**同名拒绝**，要替换已装技能加 `--overwrite`。
- 服务端走 **Layer-8 SkillSafetyValidator**（和前端「技能上传」、离线 `install_user_skill.py` 同一道闸）：可执行 tool 命名冲突、危险写法会被拦；与 builtin 同名 tool 默认拒绝，确认覆盖才加 `--allow-shadow`。
- 只写进**你本人**的 `skills/users/<你>/`，不碰他人 / builtin。
- 装完即时可用：在 ComboAgent 会话或前端「技能设置」即可见。

返回 JSON 关键字段：`skill_name` / `file_count` / `packed_files`（实际打包的相对路径列表）。

⚠️ **依赖后端部署**：`install_skill` 命中的是 `/v1/skills/install_bundle`（本次新增端点）。若返回 `Not Found`，说明目标 server 还没部署带此端点的版本；其余命令不受影响。

### E+. 把无 manifest 的 skill 脚本接成动态工具（wire_script_tools）

**场景**：从外网下载、用 `install_skill` 装进来的 skill 多半**没有 `skill.manifest.json`**。
没 manifest 的 skill 是"纯 markdown"模式——脚本只能靠 agent 读 `SKILL.md` + `execute_code`
手动跑，不会出现在工具池里。本动作把这些脚本**升级成工具池可点名调用的动态工具**。

| 操作 | 命令 |
|---|---|
| **接线**（把某 skill 的脚本注册成动态工具） | `python scripts/call.py wire_script_tools --skill-name qa --session-id <已有会话名/UUID>` |
| 追加额外要求（只接某几个脚本等） | `... wire_script_tools --skill-name qa --session-id <...> --prompt "只接 run_qa 一个脚本"` |

**原理（务必理解，避免误解为新写端点）**：
- 底层就是 **`dispatch_task`**——把 `references/wire-script-tools.md` 这段"接线"指令派给一个**已存在**的会话。
- 云端 agent 收到后，用它**自带的自编程能力**（`write_file` 写 `users/<你>/scripts/<tool>/main.py` wrapper + 读-合并-写 `users/<你>/scripts/registry.json`，即 assistant 提示词 §SCRIPT TOOL REGISTRATION「方式二」）把脚本注册成持久动态工具。
- **零核心改动**：不新增后端端点、不改平台代码；不建/删资源。

**关键约定**：
- 需要 `--session-id` 指向一个**已存在**的会话（和 `dispatch_task` 一样，目标会话必须先有）。没有就先 `create_session`。
- 是**异步**的：命令返回即排队成功；用 `get_digest --session-id <target>` 轮询 agent 的接线结果。
- 注册的工具**下一个会话才生效**（`basic_team` 启动时 `load_all → create_dynamic_tools` 才会把它们放进工具池；当前会话不刷新）。
- 工具命名约定 `<skill名>_<功能>`，便于标识归属、日后清理。
- **兜底**：即便接线失败/被跳过，skill 仍以纯 markdown 方式可用（读 SKILL.md + `execute_code` 跑脚本），只是没升级成动态工具。

### F. search 高级过滤（**先分清两条链路，再看能不能过滤**）

`search` 有两条完全不同的后端链路，`call.py` 按 `--source` 和有无 `--session-id` 自动选（`_should_use_native_kb_search`）。**过滤器只在第一条链路上存在**：

| 链路 | 触发条件 | 后端 | 有过滤器吗 |
|---|---|---|---|
| **① MemoryOS** | `--source round\|memory\|channel_history`，或任何带 `--session-id` 的检索 | `/v1/graft/memory/unified_search` → `MemoryOS.unified_search` | 有，见下表 |
| **② RAGFlow 原生 KB** | `--source document` 且**不带** `--session-id`（KB 检索的默认路径） | `/v1/chunk/retrieval_test`（与前端 KB 测试页同源） | **完全没有** |

#### ① MemoryOS 链路的过滤器

`--time-start` / `--time-end` / `--speaker` / `--chat-id` 在 `unified_search` 里被收进 `extra_filters` 下发，但**每层记忆的处理不一样**，用错层时静默丢弃（不报错、不警告），返回未过滤结果：

| 过滤器 | `--source round`（温层 episode / workspace_doc） | `--source memory`（记忆层 program / preference / fact / error_pattern / chunk_node） | `--source channel_history` |
|---|---|---|---|
| `--time-start` / `--time-end`（ISO 8601） | ✅ 按 `created_at` range | ❌ 记忆层不吃；只有混在里面的 episode / session_digest 被筛到 | ✅ |
| `--speaker` | ✅ 按 `speaker_kwd` | ❌ 同上 | ✅ 按 `from_name` |
| `--chat-id` | — | — | ✅（不传则用当前 session 关联的群） |

⚠️ **记忆层几乎没有过滤入口**：`memory_os.py` 给记忆层构造的 filter 只有 `sources` + `user_id` 两个键，`extra_filters` 根本没合并进去。所以 `--source memory` 是**半筛状态**——结果里混着"按时间筛过的 episode/session_digest"和"完全没筛的 fact/preference/error_pattern"，看起来像过滤生效了。要严格时间边界就用 `--source round`，或拿回结果后自己按 `created_at` 二次过滤。（唯一的内置记忆过滤是服务端按 `expires_at` 自动丢弃过期 error_pattern，调用方控制不了。）

✅ **从本地 graft 调 `--source round` 时过滤是完整的**：graft 的 MemoryOS 是每请求新建的只读实例、虚拟 session 为 `graft-readonly-<user_id>`，热层 `session_current` 必为空，检索只命中温层 ES，不存在"混进未过滤的热层结果"。

生效的写法示例：

```bash
python scripts/call.py search --source round --query "decision" --session-id "*" \
  --time-start 2026-04-01T00:00:00 --time-end 2026-04-15T23:59:59
python scripts/call.py search --source channel_history --chat-id oc_xxx --query "升级" --speaker "张三"
```

#### ② KB 检索链路：这里没有"memory 过滤"这回事

`--source document` **不经过 MemoryOS**，它是 RAGFlow 原生 KB 检索。`call.py` 拼的请求体只有 `kb_id / question / top_k / doc_ids / 阈值`——`--time-start` / `--speaker` 在本地就被丢掉，压根没发出去。即使绕道 unified_search，服务端对 document source 的过滤器白名单也只有 parser 类字段（`tag_kwd` / `outline_path_str` / `chunk_type` / `parser_id_kwd` / `language_kwd`），本 skill 目前**没有对应 flag**，同样过不去。

**KB 要缩范围就用这些**（都有效，按收敛力度排序）：`--doc-ids` > `--exact` > `--kb-ids` > `--top-k`。要"只看最近上传的文档"，先 `list_documents --kb-ids <id>` 按 `create_date` 自己挑出 doc_id，再 `--doc-ids` 限定——**不要指望 `--time-start` 能筛 KB**。

### I. KB chunk 修补（Excel 超链接等 — 不改 parse）

当云端 parse **不会**把 Excel 超链接写进 chunk，用本流程**定点补文字**；embedding 在云端 `patch_chunk` 时自动重算。

| 操作 | 命令 |
|---|---|
| 下载 KB 原 xlsx | `download_document --doc-id <id> [--out ./.graft/tmp/x.xlsx]` |
| 读现有 chunk 正文 | `list_doc_chunks --doc-id <id>` 或 `get_chunk --chunk-id <id>` |
| 本地抽单元格链接 | `python scripts/excel_link.py --file <xlsx> --sheet Sheet1 --cell B5` |
| 本地合并 URL 进正文 | `python scripts/enrich_chunk.py --text "点击查看" --url "https://..."` |
| **写回 + re-embed** | `patch_chunk --doc-id <id> --chunk-id <id> --content "..."` |
| 整 doc 重建（少用） | `delete_chunks --doc-id <id> --chunk-ids id1,id2` → 多次 `create_chunk` |
| 验证 | `search --source document --query "https://..." --doc-ids <id>` |

**标准流程（用户指一处）**：

```
list_documents / search           → doc_id
list_doc_chunks --doc-id <id>     → chunk_id + 现有 content_with_weight
download_document --doc-id <id>   → 本地 xlsx
excel_link.py --cell B5           → url
enrich_chunk.py --text <chunk> --url <url>  → 补全正文
patch_chunk --doc-id ... --chunk-id ... --content "..."
search 验证 URL 可命中
```

**禁止**：对同一 doc 再跑 `upload --parse` 或前端「重新解析」——会删掉 patch。若必须 re-parse，patch 后要重做本流程。
⚠️ 云端 Agent 的 **metadata 重打标**（`kb_parse` + `metadata_spec`，用户在云端说"提取要素/打标签"就会触发）走的**同样是 run=1 重解析**，一样会清掉已 patch 的 chunk。派发这类任务（`dispatch_task`）前先确认该 doc 没有未固化的 patch；打标完成后按本流程重做 patch。

**`list_chunks` vs `list_doc_chunks`**：
- `list_chunks`（KB 文档）：`call.py` 内走 `/v1/chunk/list|get`，输出 graft 兼容的 `metadata`+`content`，**team 共享库可用**
- `list_doc_chunks`（`/v1/chunk/list`）：返回扁平 `chunks` + `content_with_weight`，**patch 前读正文用这个**

### J. 我的记忆 / 团队记忆

云端「我的记忆」和「团队记忆」在 ES，不在本地 `CLAUDE.md`。**按事件写：用户说记住才 `record`，不扫本地文件、不按天抽取。**

| 操作 | 命令 |
|---|---|
| **记住一句话**（写入「我的记忆」） | `python scripts/call.py record --memory "部署前必须跑 lint"` |
| 指定类型 | `... record --memory "..." --memory-type fact\|preference\|program\|error_pattern` |
| **扫记忆**（个人 + 能读的团队约定，guardian 格式） | `python scripts/call.py memories` |
| 按当前问题再扫一遍 | `python scripts/call.py memories --query "部署前检查"` |
| 我能提交到哪些团队 | `python scripts/call.py team_memory --op teams` |
| **把一条个人记忆提交到团队候选池** | `python scripts/call.py team_memory --op share --memory "部署前必须跑 lint"` |
| 多个团队时指定团队 | `... team_memory --op share --memory "..." --team "A 团队"` |
| 撤回我提交过的那条 | `python scripts/call.py team_memory --op revoke --memory "部署前必须跑 lint"` |
| **（所有者）看候选池** | `python scripts/call.py team_curate --op pending` |
| （所有者）看已生效的团队记忆 | `python scripts/call.py team_curate --op list` |
| **（所有者）批准 / 拒绝一条候选** | `python scripts/call.py team_curate --op approve --memory "发版前先跑 lint"`；`--op reject` 同 |
| （所有者）下架一条已生效的 | `python scripts/call.py team_curate --op demote --memory "..."` |
| （所有者）把两条合并 | `python scripts/call.py team_curate --op merge --memory "<并掉哪条>" --into "<保留哪条>"` |
| （所有者）改写措辞 | `python scripts/call.py team_curate --op rewrite --memory "..." --content "新措辞"` |
| （所有者）看 / 改团队共享策略 | `python scripts/call.py team_curate --op policy`（不带 `--content` 只读；带则整段覆盖） |

规则：
- **只有用户决定记住什么、哪条进哪个团队。** 没说记住就不 `record`；没说共享就不 `share`。
- **`team_curate` 只有团队所有者能用**（服务端只认"团队 tenant_id == 当前用户"，成员调会被拒；被拒了直接说明，不要重试）。批准 / 拒绝 / 下架 / 合并都是替团队做决定：先 `--op pending` 把候选念给用户，逐条确认再动，不要一次批光。`pending` 里带 `conflicts_with` 的是和某条已生效的互相矛盾，两条原文一起念给用户选。
- 不要扫描、上传或解析本地 `CLAUDE.md` / `AGENTS.md` / 项目 memory。
- 多个团队且没带 `--team` → 返回 `need_team`，把列表念给用户再带 `--team` 重调。
- `share` 进的是**候选池**，团队所有者批准后才对全团队可见。别说「已共享」。
- `share` 只能提交用户自己的、启用中的个人记忆。本地刚说的先 `record` 再 `share`。

### 严格只读边界与写口清单

`call.py` 拒绝裸 `rm` / `delete` / `save` / `update` / `patch` / 裸 `create` 等；下列**具名写动作**放行：

- `dispatch_task` — 向已有 session 排队执行
- `upload` — 上传文件进 KB（可选 `--parse`）
- `install_skill` — 装个人技能库
- `create_session` — 新建会话
- **`patch_chunk`** — 改一条 KB chunk 正文（服务端 re-embed）
- **`create_chunk`** — 新增一条 KB chunk
- **`delete_chunks`** — 删除指定 chunk（整 doc 重建前用）
- **`record`** — 用户决定记住的一句话写入「我的记忆」
- **`team_memory`** — `--op share` 进团队候选池；`--op revoke` 撤回；`--op teams` 只读
- **`team_curate`** — 团队所有者策展：`approve` / `reject` / `demote` / `merge` / `rewrite` / `policy` 写团队库；`pending` / `list` 只读

> 不要用 `upload --parse` 代替 `patch_chunk` 来修链接。`copy_kb_document` / `register_artifact` 仍拒绝。

**`read_file` vs `download` vs `download_document`**：
- `read_file`：session workspace 文件 → markdown 文本
- `download`：session workspace 文件 → **原始字节**
- `download_document`：KB 文档（MinIO 原文件）→ **原始字节**（patch Excel 前必用）

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
| `continuation_hint` | "续读 offset=N"的 unified_search 写法提示 | 仅 **小 doc + `--doc-ids` 顺序翻页** 时参考；找深页内容用 `search`→`--chunk-ids` |

最常见错误：把 `content` 当成 wrapper、跳过它去看 metadata，结果丢掉真正的数据。

## 上下文节流规则（必读）

1. **默认只调 `get_digest`**，获取目录型概览（5–20K tokens）。
2. **按需 drill down**：digest 指明 Round N 有关键结论，才去调 `get_round --round-id N`。
3. **`search --source document` 控顶**：本地 RAG 用法 `--top-k 3-5`（不要默认 10），单 chunk 几百字 × top-k = 上下文炸。
4. **大文件落地**：`read_file` 返回的 docx/xlsx 转文本若 > 20K tokens，写入 `.graft/<slug>/artifacts/<name>`，由后续 Read 工具按需读取，**不要全文进当前上下文**。
5. **原始文件只 `download`，不读回 AI 上下文**：下载后把路径给用户/后续流程用，字节流绝不塞进 prompt。
6. **不做全量拖库**：禁止循环拉所有 round / 所有 artifact。
7. **KB 顺序翻页 vs 检索**：`list_chunks --doc-ids --offset` 仅用于**小文档从开头顺序读**；找特定段落一律 `search` → `--chunk-ids`。`read_file` 翻页用 `--offset`/`--line-start`；**不要把 KB 的 offset 当 PDF 页码**。
8. **不要无脑扫整库**：禁止对大 doc 循环 offset；禁止用 snippet 代替 `--chunk-ids` 全文。

## 使用流程

### 流程 A：把云端 KB 当 RAG 用（不需要任何 session）

```
1. list_kbs / list_documents                           → kb_id、doc_id
2. 判定：编号/ID/原文短语? → search --exact … ; 否则 → search … --top-k 3-5
3. list_chunks --chunk-ids <16hex> --window 0           → 完整正文（必做）
4. 本地 agent 拿全文做推理 / 答复用户
```

**不要做的事**：混合 `search` 查 ID 并下「不存在」结论；用 `--doc-ids --offset` 扫大 PDF；search 命中后不调 `--chunk-ids` 就写结论。

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
- 除 `dispatch_task` / `upload` / `install_skill` / `record` / `team_memory`（share/revoke）/ `team_curate`（所有者策展）外其余命令**只读**，不会修改云端任何数据；其余写操作在 skill 层 + 服务端双重拦截
- `upload` 默认**只上传不解析**，要进检索得显式 `--parse`；只上传到你有权限的 KB，不删/改 KB 既有内容
- `install_skill` 只装进**你本人**技能库（`skills/users/<你>/`）；目录名须等于 skill 名；走 Layer-8 安全校验，git 可选
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
| `list_chunks --doc-ids --offset` 永远读不到文档后半 / page 3000+ | **不是 KB 缺数据**；`offset` 是 chunk 游标且工具有 ~10000 chunk 加载上限 | 改 `search` 拿 `chunk_id` → `list_chunks --chunk-ids <id> --window 0`；见 `references/kb-retrieval-logic.md` |
| 加了 `--time-start` / `--speaker` 但结果和不加时一模一样 | 该链路没有这些过滤器，参数被**静默丢弃**：`--source document` 走 RAGFlow 原生 KB（不经 MemoryOS）完全无效；`--source memory` 的记忆层也不吃，只筛到混在里面的 episode | 见 §F；KB 改用 `--doc-ids` / `--exact` 收敛，严格时间边界改 `--source round` |
| search 有命中但正文不完整 / 缺 step | 只用了 search snippet，未 `--chunk-ids` 取全文 | `list_chunks --chunk-ids <metadata.items[].chunk_id> --window 0` |
| `[ERR] dispatch_task 需要 --session-id` | 漏传目标 session | 加 `--session-id <sid>`；不能用 `*` |
| `[ERR] permission denied for session ...` | 派发的 session 不在你的可见范围 | 检查 owner / 共享关系；先 `list_sessions` 确认 |
| `[ERR] target session not found` | session id 写错或已被删 | `list_sessions --query` 找正确 id |
| `[ERR] Not Found`（dispatch_task 调用） | 后端没部署 `/v1/graft/dispatch_task` 端点 | 确认目标 server 跑的是带新端点的版本；其他命令不受影响 |
| `[ERR] Not Found`（`memories` / `record` / `team_memory` / `team_curate`） | 后端没部署 `/v1/graft/memory/prologue`、`/record`、`/team_memory` 或 `/team_curate` | 目标 server 需要带这些端点的版本；其余命令不受影响。老版本没有 `/team_curate`：审批改到网页对话里做 |
| `team_memory` 返回 `没找到这条记忆` | 云端「我的记忆」里没有这条（或已 private） | 先 `record --memory "..."` 再 share；只能提交自己的 active 个人记忆 |
| `team_curate` 返回 `团队库里没找到「…」对应的条目` / `打不开团队记忆库` | 原话没匹配上，或当前用户不是团队所有者 | 先 `--op pending` / `--op list` 拿到条目 id 再按 id 操作；成员没有策展权，让所有者来 |
| `prompt too long: ... > 32768` | dispatch 的 prompt 超过 32 KB 上限 | 缩减 prompt 或拆成多次 dispatch |
| `upload` 返回 `Can't find this knowledgebase!` | kb_id 写错 / 不在你可见范围 | 先 `list_kbs` 拿正确 kb_id；确认 KB 归属或共享 |
| `upload` 全部 `failed`，error 含 `Connection refused` / `Max retries` | 后端 server 不可达（与 `list_kbs` 同一个 server） | 先 `list_kbs` 验证连通；不通就查 server URL / 重新 `login.py` |
| `upload` 返回 ok 但 KB 里搜不到内容 | 没加 `--parse`，文件只上传未解析（无 chunks） | 加 `--parse` 重传，或前端 KB 页点解析；`list_documents --kb-ids <id>` 看 run/progress |
| `upload --parser-id` 报 `Unknown parser_id` | parser_id 不在 KB 白名单 | 去掉 `--parser-id` 用 KB 默认；或查 `GET /v1/parser/discover` |
| `upload` 报 `文件过大 ... > ...` | 单文件 > 200 MB | 大文件走前端 KB 上传，不走本 skill |
| `install_skill` 报 `--skill-path 不是目录` / `找不到 SKILL.md` | 路径不对，或指到了单个文件 | `--skill-path` 要指向**目录**，且目录里有 `SKILL.md` |
| `install_skill` 报 dir-name invariant / `name` 不匹配 | skill 目录名 ≠ SKILL.md 里的 `name` | 重命名目录使其等于 `name`，再装 |
| `install_skill` 报 `与 builtin 工具同名冲突` | skill 的 tool 名撞 builtin | 改 tool 名；确需覆盖加 `--allow-shadow`（罕见） |
| `install_skill` 报 `already exists` | 同名技能已装 | 确认要替换加 `--overwrite` |
| `install_skill` 返回 `Not Found` | 后端没部署 `/v1/skills/install_bundle` | 确认目标 server 跑的是带此端点的版本；其他命令不受影响 |
