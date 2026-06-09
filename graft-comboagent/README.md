# graft-comboagent

> 本地 agent 的 **ragbase 远程客户端**：直接查云端知识库（语义检索 / 列文档 / 翻 chunk）、嫁接已有 session 的执行成果、向已有 session 派发任务，并能把本地文件回流进 KB、把本地 skill 装进云端个人技能库、从本地新建并驱动 session。

这是一个**本地 Skill 包**。任何支持 skill 机制的本地 Agent 宿主（Cursor / Claude Code / Codex 等）都可以装上它，让 AI 既能把云端 KB 当 RAG 用、基于云端 session 的成果审查/加工本地代码，也能把本地产出回流到云端。

---

## 1. 能力一览

| 用途 | 主要动作 | 写云端？ | 需云端先跑过 session |
|---|---|---|---|
| **A. KB 检索**（核心高频） | `list_kbs` / `kb_detail` / `search --source document` / `list_documents` / `get_doc_profile` / `list_chunks` | 否 | 不需要 |
| **B. Session 嫁接** | `list_sessions` / `get_digest` / `get_round` / `search` / `read_file` / `download` / `list_files` / `search_by_artifact` / `grep_file` | 否 | 需要 |
| **C. 派发任务** | `dispatch_task` | 触发执行（不增删资源） | 需要 |
| **D. 上传到 KB** | `upload`（可选 `--parse`） | **是**（入库） | 不需要 |
| **E. 安装 skill 到云端** | `install_skill` | **是**（写 `skills/users/你/`） | 不需要 |
| **F. 列 agents**（辅助） | `list_agents` | 否 | 不需要 |
| **G. 新建并驱动 session** | `create_session`（可 `--first-prompt`） | **是**（建会话记录） | 不需要 |

> **写边界很窄**：只有 `dispatch_task`、`upload`、`install_skill`、`create_session` 四个写动作，其余全部只读（含只读的 `list_agents`）。删除 / 改写 KB 已有内容请走前端 UI。
> 详细用法、上下文节流规则、按意图分类的决策树见 `SKILL.md`（LLM 读）与 `references/action-decision-tree.md`。

---

## 2. 工作方式（简单说）

- **服务器端**：ragbase 复用一组 user-level HTTP 端点，认证走现有 `itsdangerous` 签名的 access_token（和 web UI 完全一致）：
  - `/v1/graft/memory/unified_search` — 检索 / 列表 / digest / round / read_file
  - `/v1/graft/memory/download` — 原始字节下载
  - `/v1/graft/dispatch_task` — 向已有 session 异步派发一轮（**新端点**）
  - `/v1/document/upload`（+ 可选 `/v1/document/run`）— 上传本地文件进 KB
  - `/v1/skills/install_bundle` — 安装本地 skill 进个人技能库（**新端点**）
  - `/v1/combo_web/agents`(GET) / `/v1/combo_web/agents/<id>/sessions`(POST) — 列 agents / 新建会话
- **客户端**：本 skill 提供 4 个 Python 脚本（login / whoami / logout / call），帮你用 email + password 登录并访问上述端点
- **AI 侧**：`SKILL.md` 指导 LLM「先 Digest、按需 drill down」，大文件走 `download` 直接落地，不塞进上下文

```
┌────────────────────────┐        ┌──────────────────────────────────┐
│ 本地 Skill 宿主          │        │ ragbase (cloud)                   │
│                        │        │                                  │
│ scripts/login.py ──────┼──POST──▶ /v1/user/login                    │
│                        │◀──data─ signed_auth_token                  │
│  ~/.config/graft-comboagent/token.json (0600)                       │
│                        │        │                                  │
│ scripts/call.py <act>  ├─POST──▶ /v1/graft/memory/unified_search    │
│ scripts/call.py download├─GET ──▶ /v1/graft/memory/download (bytes) │
│   ── 写口（4 个）──      │        │                                  │
│ dispatch_task          ├─POST──▶ /v1/graft/dispatch_task            │
│ upload                 ├─POST──▶ /v1/document/upload (+ /run)       │
│ install_skill          ├─POST──▶ /v1/skills/install_bundle          │
│ create_session         ├─POST──▶ /v1/combo_web/agents/<id>/sessions │
│ list_agents (只读)      ├─GET ──▶ /v1/combo_web/agents               │
└────────────────────────┘        └──────────────────────────────────┘
```

---

## 3. 目录结构

```
graft-comboagent/
├── SKILL.md                                 # LLM 读这个：调用方式、节流规则、使用流程
├── README.md                                # 人读这个（本文件）
├── public.pem                               # RSA 公钥（同步自 ragbase conf/public.pem）
├── references/
│   ├── action-decision-tree.md              # 按用户意图分类的 action 决策树（选哪条命令）
│   └── cross-session-retrieval.md           # 跨 session 检索的深度说明
└── scripts/
    ├── login.py                             # 登录：email + password (+ --server) → 保存 token
    ├── whoami.py                            # 显示当前登录身份
    ├── logout.py                            # 删除本地 token
    └── call.py                              # 统一调用入口（所有读 / 写 action + download）
```

---

## 4. 依赖

脚本依赖两个常见库：

```bash
pip install requests pycryptodome
```

（如果 `pycryptodome` 在老环境下叫 `pycrypto`，`login.py` 会自动 fallback）

---

## 5. 安装到本地 Skill 宿主

### Cursor

```bash
cp -r /home/ubuntu/lu.shi/ragbase/skills/graft-comboagent ~/.cursor/skills/
# 或（更新时自动同步）：
ln -s /home/ubuntu/lu.shi/ragbase/skills/graft-comboagent ~/.cursor/skills/graft-comboagent
```

### Claude Code

```bash
cp -r /home/ubuntu/lu.shi/ragbase/skills/graft-comboagent ~/.claude/skills/
```

### Codex

```bash
cp -r /home/ubuntu/lu.shi/ragbase/skills/graft-comboagent ~/.codex/skills/
```

装完后重启宿主即可让 skill 被发现。

---

## 6. 首次使用

```bash
cd ~/.cursor/skills/graft-comboagent   # 或你装到的位置

# 1) 登录（默认公有云 https://xipnex.nox-lumen.com；自部署 / 内网加 --server <URL>）
python scripts/login.py --server https://ragbase.example.com --email me@example.com --password '********'
#   [OK] Logged in as me@example.com (user=ab12cd34…)
#   切 server 一律走 login.py 重登，别手改 token.json 的 server 字段

# 2) 验证
python scripts/whoami.py

# 3) 把 KB 当 RAG 用（不需要任何 session）
python scripts/call.py list_kbs --keywords ASPICE
python scripts/call.py search --source document --query "传感器精度要求" --kb-ids <kb_id> --top-k 3

# 4) 嫁接已有 session
python scripts/call.py list_sessions --query 冷却
python scripts/call.py get_digest --session-id "冷却系统分析"
python scripts/call.py get_round  --session-id "冷却系统分析" --round-id 5
python scripts/call.py download --path "workspace/sessions/<sid>/output/report.docx" --out ./report.docx

# 5) 写口（四个）：派任务 / 上传 KB / 装 skill / 新建会话
python scripts/call.py dispatch_task --session-id "冷却系统分析" --prompt "把结论总结成中文要点"
python scripts/call.py upload --kb-id <kb_id> --file ./缺陷分析.md --parse
python scripts/call.py install_skill --skill-path ./my-skill
python scripts/call.py list_agents --keywords 报价          # 先拿 agent_id（只读）
python scripts/call.py create_session --agent-id <id> --name "新会话" --first-prompt "开始分析"
```

---

## 7. 典型 AI 工作流（AI 不看这段，给人看）

**只读流（嫁接 + 比对）** —— 用户说：

> "从云端 session 'ASPICE 分析' 取出 DFMEA 结论，对照本地 `src/` 下的代码，找出未覆盖的 SRS 需求。"

AI（跟着 SKILL.md 走）会：

1. `call.py list_sessions --query ASPICE` 定位 session
2. `call.py get_digest --session-id <ID>` 看整体脉络、找哪几轮有关键结论
3. `call.py get_round --round-id N --session-id <ID>` 取结论轮
4. 必要时 `call.py download --path ... --out ./artifacts/xxx.docx` 拿原文
5. 本地 Read/Grep 扫 `src/` 做比对
6. 产出分析报告

**写回流（回流 + 驱动）** —— 用户说：

> "把刚跑出来的缺陷分析回流到 ASPICE 知识库，再让对应 bot 新开一个会话复核一遍。"

AI 会：

1. `call.py list_kbs --keywords ASPICE` 找目标 KB
2. `call.py upload --kb-id <kb_id> --file ./findings.md --parse` 回流并入库
3. `call.py list_agents --keywords 复核` 拿 `agent_id`
4. `call.py create_session --agent-id <id> --name "缺陷复核" --first-prompt "复核 findings.md"` 建会话并驱动首轮
5. `call.py get_digest --session-id <新 sid>` 轮询新一轮产出

---

## 8. 环境变量

| 变量 | 用途 | 默认 |
|---|---|---|
| `GRAFT_COMBOAGENT_SERVER` | login 的默认服务器 URL | — |
| `GRAFT_COMBOAGENT_EMAIL`  | login 的默认 email | — |
| `GRAFT_COMBOAGENT_TOKEN`  | token 文件路径 | `~/.config/graft-comboagent/token.json` |
| `GRAFT_COMBOAGENT_DL_DIR` | `download` 默认落盘目录 | `./.graft/downloads/` |

---

## 9. 安全

- `~/.config/graft-comboagent/token.json` 创建时 `chmod 0600`，父目录 `0700`
- 密码**全程不落盘**：命令行优先、其次 `getpass` 从 TTY 读，RSA 加密后只走网络传输
- Token 撤销：在任何其他客户端重新 login 一次，旧 token 因 `user.access_token` 被重置自然失效
- **写边界很窄**：`call.py` 只放行 `dispatch_task` / `upload` / `install_skill` / `create_session` 四个写动作；其余写类 action（`rm` / `delete` / `save` / `update` / 裸 `create` / `copy_kb_document` / `register_artifact` …）在 skill 层 + 服务端双重拒绝
- 四个写动作各自有界：`upload` 只写到**你有权限的** KB（不删/改既有内容）；`install_skill` 只写到**你本人**技能库 `skills/users/<你>/`（走 Layer-8 安全校验）；`create_session` 只建会话记录；`dispatch_task` 只触发一次执行、不增删持久化资源
- 删除 / 改写 KB 已有内容请走前端 UI

---

## 10. 已知限制（当前版本）

- 写动作有限：可 `dispatch_task` / `upload` / `install_skill` / `create_session`，但**不能**改写或删除 KB 既有内容、不能写回已有 session 的 round（要在云端生成新产出请走对应 agent 的执行）
- 后端部署依赖：`dispatch_task`（`/v1/graft/dispatch_task`）与 `install_skill`（`/v1/skills/install_bundle`）是新端点，老 server 未部署会返回 `Not Found`；其余命令（检索 / 嫁接 / upload / create_session）不受影响
- 单 profile：一次只能登录一个 ragbase server；切换走 `login.py --server <URL>` 重登（或设置 `GRAFT_COMBOAGENT_TOKEN` 指向不同文件），**不要**手改 `token.json` 的 `server` 字段
- 浏览器级 SSO 不支持：只支持 email + password（如需 OAuth / SSO 请提需求单）
- 大小上限：单次 `download` ≤ 200 MB、单文件 `upload` ≤ 200 MB（服务端硬上限，超限走前端 KB）

---

## 11. 故障排查

| 症状 | 解决 |
|---|---|
| `[FATAL] public.pem 不存在` | 确认 skill 目录根下有 `public.pem`；从 ragbase `conf/public.pem` 复制 |
| `[FATAL] 服务器没有返回 signed_auth_token` | 服务端没部署 login 响应追加字段的改动，联系管理员升级 |
| `[ERR] 未登录` | 先 `python scripts/login.py` |
| `HTTP 401 / 认证失效` | `access_token` 被别处 login 重置，重新 `login.py`（`whoami` 只读本地不验服务端，别只信它） |
| 所有命令一致 401 / Not Found / DNS 错 | server URL 不对；`whoami.py` 看当前 server，不对就 `login.py --server <真实 server>` 重登 |
| `Access denied` | 目标 session 不在当前 user 的可见范围（自己的 + 共享） |
| `Action ... not allowed via graft` | 误用了被拒的写 action；只放行 dispatch_task / upload / install_skill / create_session 四个写口 |
| `[ERR] Not Found`（dispatch_task / install_skill） | 目标 server 没部署对应新端点；其余命令不受影响 |
| `upload` 返回 ok 但 KB 里搜不到 | 没加 `--parse`，文件只上传未解析；补 `--parse` 重传或前端 KB 页点解析 |
| `install_skill` 报 dir-name invariant | skill 目录名 ≠ SKILL.md 的 `name`；重命名目录后再装 |
| `File too large for graft download` | 超过 200 MB 服务端硬上限；让产出物发布时做分卷或专用下载通道 |

> 更全的写动作故障排查（dispatch 的 episode 模型、upload parser、install_skill 冲突 / `--overwrite` 等）见 `SKILL.md` 的「故障排查」表。

---

## 12. 服务端要求

部署 skill 所需的服务端改动：

1. `api/apps/user_app.py` 的 login 端点在响应 `data` 里追加 `signed_auth_token`
2. `api/apps/graft_app.py`，暴露：
   - `POST /v1/graft/memory/unified_search` — 检索 / 列表 / digest / round / read_file
   - `GET  /v1/graft/memory/download` — 原始字节下载
   - `POST /v1/graft/dispatch_task` — 向已有 session 异步派发一轮（**新增**）
3. 复用平台现成端点（不为本 skill 额外新增）：
   - `POST /v1/document/upload`（+ 可选 `/v1/document/run`）— `upload`
   - `POST /v1/skills/install_bundle` — `install_skill`（**本次新增端点**，服务端走 Layer-8 SkillSafetyValidator）
   - `GET  /v1/combo_web/agents` / `POST /v1/combo_web/agents/<id>/sessions` — `list_agents` / `create_session`（与前端「新建会话」同源的老端点）

graft 自有端点均 `@login_required`，权限校验复用现有 `_verify_graft_access`；复用端点沿用各自原有的 `current_user` 鉴权。服务端实现在 `AgentFlow/src/skills/builtin/graft` 与 `api/apps/graft_app.py` / `api/apps/kb_app.py`。
