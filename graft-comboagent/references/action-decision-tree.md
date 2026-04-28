# Action 决策树 — 看场景挑 action

> 本地 agent 拿到任务后**先在这里查 1 秒**：你想做什么 → 该用哪个 action。
>
> 不要先看 SKILL.md A/B/C/D 表挨个对照——那些表是按"功能分类"组织的，回答的是"这条命令是什么"；这里是按"用户意图"组织的，回答"我现在该用哪条"。

源头：云端 unified_search 工具 docstring 里的 9 分支（`AgentFlow/src/memory/memory_os.py::create_tool` 第 6842 行附近），本文做了本地化适配。

---

## A. 我要查云端知识库（KB）

| 意图 | 用 |
|---|---|
| 不知道有哪些 KB | `list_kbs` |
| 想看某个 KB 的元信息（大小、parser、embedding 模型） | `kb_detail --kb-id <id>` |
| **在 KB 里语义检索**（最高频） | `search --source document --query "..." --kb-ids <id> --top-k 3` |
| 只在某文档内搜（精准片段，不占满上下文） | `search --source document --query "..." --doc-ids <id>` |
| 列 KB 里所有文档 | `list_documents --kb-ids <id>` |
| 看文档结构概要（章节 / Sheet / chunk 数） | `get_doc_profile --doc-ids <id>` |
| **读文档全文**（需翻页） | `list_chunks --doc-ids <id> --offset 0 --limit 20`，下一页 `--offset 20` |
| **search 命中后看前后上下文** | `list_chunks --chunk-ids <hit_id> --window 2` ← 返回目标 chunk + 前后各 2 个同文档 chunk |

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
