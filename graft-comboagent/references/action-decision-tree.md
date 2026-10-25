# Action 决策树 — 看场景挑 action

> 本地 agent 拿到任务后**先在这里查 1 秒**：你想做什么 → 该用哪个 action。
>
> 不要先看 SKILL.md A~E 表挨个对照——那些表是按"功能分类"组织的，回答的是"这条命令是什么"；这里是按"用户意图"组织的，回答"我现在该用哪条"。

源头：云端 unified_search 工具 docstring 里的 9 分支（`AgentFlow/src/memory/memory_os.py::create_tool` 第 6842 行附近），本文做了本地化适配。

---

## A. 我要查云端知识库（KB）

**检索判定（先看这行）**：用户给的是**已知字符串**（Test Case ID、REQ 编号、信号名、版本号、原文短语）→ `--exact`；给的是**问题描述/找相关内容**→ 默认混合 `search`。

| 意图 | 用 |
|---|---|
| 不知道有哪些 KB | `list_kbs` |
| 想看某个 KB 的元信息（大小、parser、embedding 模型） | `kb_detail --kb-id <id>` |
| **精确检索**（ID/编号/原文短语，正文必含） | `search --source document --query "1023265" --doc-ids <doc> --exact` |
| **语义检索**（自然语言、找相关） | `search --source document --query "..." --kb-ids <id> --top-k 3` |
| 只在某文档内语义搜（不占满上下文） | `search --source document --query "..." --doc-ids <id>` |
| **search 命中后取完整正文**（默认下一步） | `list_chunks --chunk-ids <chunk_id> --window 0` ← id 来自 `metadata.items[].chunk_id` |
| 列 KB 里所有文档 | `list_documents --kb-ids <id>` |
| 看文档结构概要（章节 / Sheet / chunk 数） | `get_doc_profile --doc-ids <id>` |
| 从文档**开头**顺序读 chunk（**仅小 doc，<~10k chunks**） | `list_chunks --doc-ids <id> --offset 0 --limit 20`；`offset` 是 chunk 游标，**不是 PDF 页码** |
| search 命中后要邻接上下文（小 doc） | `list_chunks --chunk-ids <hit_id> --window 1` |
| **下载 KB 原文件**（patch Excel 前） | `download_document --doc-id <id> [--out ./local.xlsx]` |
| **读 chunk 正文（patch 前）** | `list_doc_chunks --doc-id <id>` ← 含 `content_with_weight` |
| **用户说 KB 某处内容错了 / Excel 链接丢了** | 见下方 **§I** |

## I. KB chunk 定点修补（不改 parse）

| 意图 | 用 |
|---|---|
| 下载 KB 里的原 xlsx/docx | `download_document --doc-id <id>` |
| 看某 doc 所有 chunk 正文 | `list_doc_chunks --doc-id <id> [--page N]` |
| 看单条 chunk | `get_chunk --chunk-id <id>` |
| 本地抽 Excel 单元格 URL | `python scripts/excel_link.py --file <xlsx> --sheet S1 --cell B5` |
| 把 URL 并进 chunk 文字 | `python scripts/enrich_chunk.py --text "..." --url "https://..."` |
| **写回 + 云端 re-embed** | `patch_chunk --doc-id <id> --chunk-id <id> --content "..."` |
| 整 doc 清空后重建（少用） | `delete_chunks` → 多次 `create_chunk` |
| 验证 patch 生效 | `search --source document --query "<URL>" --doc-ids <id>` |

> ⚠️ **不要**对同一 doc 用 `upload --parse` 或前端 re-parse —— 会覆盖 patch。修链接走 `patch_chunk`，不走 parse。

> 🔍 **检索逻辑 self-awareness**：大文档 / 标准库 / SWTD 等 **禁止** 用 `--doc-ids --offset` 找深页内容；必须 `search` → `--chunk-ids --window 0`。详见 [`kb-retrieval-logic.md`](kb-retrieval-logic.md)。

## B. 我要嫁接已有 session 的成果

| 意图 | 用 |
|---|---|
| 不知道有哪些 session | `list_sessions [--query <kw>]` |
| **看 session 全貌**（先做这步，不要跳过） | `get_digest --session-id <id或名称>` |
| 已知 round 号，要那一轮原文 | `get_round --session-id X --round-id N`（多 epoch 加 `--epoch E`） |
| 已知产出物名 | `search_by_artifact --query "<产出物名>" --session-id X` |
| 不确定在哪一轮 | `search --source round --query "<kw>" --session-id X` |
| 不确定在哪个 session | `search --source round --query "<kw>" --session-id "*"` |
| 知道文件路径，要文本 | `read_file --path workspace/sessions/<sid>/<path>` |
| 知道文件路径，要原始字节（docx/xlsx/pdf） | `download --path workspace/sessions/<sid>/<path>` |
| 文件大，定位某行附近 | `read_file --path <p> --center-line 500 --context-lines 50` |
| 文件大，按行范围读 | `read_file --path <p> --line-start 100 --line-end 200` |
| 文件大，**找关键词** | `read_file --path <p> --find "<kw>" --find-context 5 --max-find-matches 3` ← 返回每处命中 + 行号 + 上下文 |
| 不确定文件路径 | `grep_file --query "<文件名关键词>"` → 拿到 path 后再 `read_file` |
| 列某目录下所有文件 | `list_files --query "workspace/sessions/<sid>/output/"` |

## C. 我要让云端某个 agent 跑一轮

| 意图 | 用 |
|---|---|
| 派任务给已有 session（异步） | `dispatch_task --session-id <名称或UUID> --prompt "..."` |
| 等结果（轻量） | `list_sessions --query <名> ` 看 `updated_at` |
| 等结果（重量） | `get_digest --session-id <id>` 看是否多出新 round |
| 找 dispatch 跑出的新 round_id | `search --source round --query "<prompt 关键词>" --session-id <id>` ← 命中 chunk id 形如 `ep_<sid>_<EPISODE>_e<E>_r<R>`，**新 episode hash ≠ 原 episode** |

## D. 我要把本地文件灌进云端 KB（回流 findings / 缺陷 / 报告）

| 意图 | 用 |
|---|---|
| 不知道往哪个 KB 传 | 先 `list_kbs [--keywords <名字>]` 拿 kb_id |
| 上传一个文件（先不解析） | `upload --kb-id <id> --file ./x.md` |
| 上传并立即解析入库 | `upload --kb-id <id> --file ./x.md --parse` |
| 一次传多个 / 整个目录 | `upload --kb-id <id> --file a.md --file b.md --parse` 或 `upload --kb-id <id> --dir ./out --glob "*.md" --parse` |
| 落到 KB 子目录 / 指定 parser | `upload --kb-id <id> --file x.md --kb-path findings/2026 --parser-id naive --parse` |
| 看上传后解析进度 | `list_documents --kb-ids <id>` 看每条 `run` / `progress` |

> ⚠️ 默认**只上传不解析**，要进检索必须加 `--parse`。只能传到你有权限的 KB；不删/不改 KB 既有内容。大批量（几百文件）走前端 KB，不要用本 skill 刷。

## J. 我要记 / 扫 / 提交云端记忆

| 意图 | 用 |
|---|---|
| 用户说「记住这个」 | `record --memory "<原话>"`（可选 `--memory-type`） |
| 把「我的记忆」+ 团队约定拉进当前上下文 | `memories`；有具体问题加 `--query "..."` |
| 这条个人记忆团队都该知道 | 没有云端原条就先 `record`，再 `team_memory --op share --memory "<原话或 id>"` |
| 不知道能提交到哪个团队 | `team_memory --op teams`；多个团队先问用户再带 `--team` |
| 撤回我提交过的 | `team_memory --op revoke --memory "<原话或 id>"` |

用户没说记住就不要 `record`。没说共享就不要 `share`。不要扫本地 `CLAUDE.md`。提交进的是候选池，不是已生效。

## 跨场景的高频过滤参数

任何 `search` action 都可加：

| 参数 | 用途 |
|---|---|
| `--top-k N` | 限返回条目数（默认 5，本地 RAG 建议 3–5） |
| `--max-tokens N` | 限返回 token 总量（0=按预算） |
| `--time-start` / `--time-end` | ISO 8601 时间范围（仅 round / channel_history 有意义） |
| `--speaker` | 按发言人过滤（round / channel_history） |
| `--chat-id` | 群聊 id（仅 `--source channel_history`） |

## 与云端 agent 决策树的差异

云端版本（`memory_os.py` 第 6842 行）多了两条本地不适用的约束：

1. **"每页处理后 flush 再续读"**——云端 agent round 内上下文易失，必须 `write_file` 落地；**本地 agent 自己能 Read 翻页或者全部塞进 context window，没这个约束**
2. **"压缩后 chunk_id"**——云端有 `ToolCallSummaryMessage` 压缩层，需要从压缩后 metadata 取 chunk_id；**本地透传整个返回，直接用 search 命中的 `id` 字段**

本地的核心原则反而更简单：**分块 / 分页参数全部由本地 agent 自决**——skill 只透传，不偷加默认。
