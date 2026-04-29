# graft-comboagent

> 本地 agent（Cursor / Claude Code / Codex）的 ragbase 远程客户端：在本地装一个 skill，就能直接查云端知识库、嫁接已有 session 的执行成果、向已有 session 派发任务。

这是一个**本地 Skill 包**。任何支持 skill 机制的本地 Agent 宿主（Cursor / Claude Code / Codex / Trae 等）都可以装上它，让 AI 端的能力直接延伸到云端 ragbase 的数据和算力。

---

## 1. 三种用途（先看这张表）

| 用途 | 说明 | 写入云端？ | 是否需要云端先跑过 session |
|---|---|---|---|
| **A. KB 检索**（核心高频） | 列我有哪些知识库 → 在 KB 里做语义检索 → 把命中 chunks 拉回本地给当前 agent 当 RAG 上下文 | 否 | 不需要 |
| **B. Session 嫁接** | 拉某次 comboagent 跑出来的 digest / round / 产出物，对照本地代码做分析 | 否 | 需要 |
| **C. 派发任务**（dispatch） | 把指令派给已存在的某个 session，让云端 agent 排队跑一轮（异步） | 触发执行（不创建/删除资源） | 需要（目标 session 必须已存在） |

> AI 怎么选？详见 `SKILL.md`（LLM 主读文档），或 `references/action-decision-tree.md`。

---

## 2. 工作方式（简单说）

- **服务器端**：ragbase 暴露若干 user-level 的 HTTP 端点，认证全部走现有 `itsdangerous` 签名的 access_token（和 web UI 完全一致）：
  - `POST /v1/graft/memory/unified_search` — 跨 session 检索 / digest / round / read_file / list_kbs 之外的所有 unified 操作
  - `GET  /v1/graft/memory/download` — 产出物原始字节流
  - `POST /v1/graft/dispatch_task` — 派发任务到已有 session（**唯一写入口**，不创建/删除资源）
  - `POST /v1/kb/list` / `GET /v1/kb/detail` — 知识库列表 / 详情
- **客户端**：本 skill 提供 4 个 Python 脚本（login / whoami / logout / call），帮你登录并访问上述端点
- **AI 侧**：`SKILL.md` 指导 LLM「先 Digest、按需 drill down」、KB 检索 `--top-k 3-5` 控顶、大文件走 `download` 落地不塞上下文

```
┌────────────────────────┐        ┌────────────────────────────┐
│ 本地 Skill 宿主          │        │ ragbase (cloud)             │
│                        │        │                            │
│ scripts/login.py ──────┼──POST──▶ /v1/user/login              │
│                        │◀──data─ signed_auth_token            │
│  ~/.config/graft-comboagent/token.json (0600)                  │
│                        │        │                            │
│ call.py <unified-act>  ├─POST──▶ /v1/graft/memory/unified_search
│ call.py download       ├─GET ──▶ /v1/graft/memory/download (bytes)
│ call.py list_kbs       ├─POST──▶ /v1/kb/list                  │
│ call.py kb_detail      ├─GET ──▶ /v1/kb/detail                │
│ call.py dispatch_task  ├─POST──▶ /v1/graft/dispatch_task       │
│                        │        │                            │
│ AI: 按 SKILL.md 选 action │        │ MemoryOS.unified_search    │
│   + KB 接口 + dispatch   │        │ + _verify_graft_access     │
└────────────────────────┘        └────────────────────────────┘
```

---

## 3. 目录结构

```
graft-comboagent/
├── SKILL.md                                 # LLM 读这个：调用方式、节流规则、使用流程
├── README.md                                # 人读这个（本文件）
├── public.pem                               # RSA 公钥（同步自 ragbase conf/public.pem）
├── references/
│   ├── action-decision-tree.md              # 9 分支决策树：用户意图 → 选哪条 action
│   └── cross-session-retrieval.md           # 跨 session 检索的深度说明
└── scripts/
    ├── login.py                             # 登录：email + password → 保存 auth token
    ├── whoami.py                            # 显示当前登录身份
    ├── logout.py                            # 删除本地 token
    └── call.py                              # 统一调用入口（KB / 嫁接 / dispatch / download）
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

先把 combo-skills 仓库 clone 下来（任意目录，例如 `~/src/`）：

```bash
git clone https://github.com/Nox-Lumen-tech/combo-skills.git ~/src/combo-skills
```

然后装到对应宿主的 skill 目录：

| 宿主 | 命令 | 官方 Skills 文档 |
| --- | --- | --- |
| **Cursor** | `cp -r ~/src/combo-skills/graft-comboagent ~/.cursor/skills/`<br/>或软链：`ln -s ~/src/combo-skills/graft-comboagent ~/.cursor/skills/graft-comboagent` | [cursor.com/docs/skills](https://cursor.com/docs/skills) |
| **Claude Code** | `cp -r ~/src/combo-skills/graft-comboagent ~/.claude/skills/` | [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills.md) |
| **Trae** | `cp -r ~/src/combo-skills/graft-comboagent ~/.trae/skills/` | [docs.trae.ai/ide/skills](https://docs.trae.ai/ide/skills) |
| **Codex** | `cp -r ~/src/combo-skills/graft-comboagent ~/.codex/skills/` | （随仓库内 SKILL.md 标准） |

> Cursor 同时也会扫描 `~/.claude/skills/`、`~/.codex/skills/`，所以软链一份在 `~/.cursor/skills/` 后，也可以在 Cursor / Claude Code / Codex 通用。

装完后重启宿主即可让 skill 被发现。Claude Code 在已开会话里**实时检测**新增/修改（不必重启），但**新建顶层目录**仍要重启。

> 想让 skill 跟着仓库更新？用软链替代 `cp -r`，再加一条 cron：`cd ~/src/combo-skills && git pull`。

---

## 6. 首次使用

```bash
cd ~/.cursor/skills/graft-comboagent   # 或你装到的位置

# 1) 登录（服务器 URL、email、password）
python scripts/login.py
#   ragbase server URL: https://xipnex.nox-lumen.com
#   email: me@example.com
#   password: ********
#   [OK] Logged in as me@example.com (user=ab12cd34…)

# 2) 验证
python scripts/whoami.py
```

试一下三种用途各一条：

```bash
# A. KB 检索（不需要任何 session）
python scripts/call.py list_kbs                                    # 我有哪些知识库
python scripts/call.py search --source document --query "传感器精度要求" \
                              --kb-ids <kb_id> --top-k 3            # 在 KB 里语义检索

# B. Session 嫁接
python scripts/call.py list_sessions --query 冷却
python scripts/call.py get_digest --session-id "冷却系统分析"
python scripts/call.py download --path "workspace/sessions/<sid>/output/report.docx" \
                                --out ./report.docx

# C. 派发任务到已有 session（异步，立即返回）
python scripts/call.py dispatch_task --session-id "冷却系统分析" \
                                     --prompt "请把附件文档总结成中文要点"
# ↑ 立即返回 queued=true；用 search --source round 看新一轮内容
```

---

## 7. 典型 AI 工作流（AI 不看这段，给人看）

### 工作流 A：把云端 KB 当 RAG 用（不需要 session）

用户在本地 IDE 里跟 AI 说：

> "在 ASPICE 知识库里搜'传感器精度要求'，告诉我相关章节怎么写。"

AI（跟着 SKILL.md 走）会：

1. `call.py list_kbs --keywords ASPICE` 找到目标 KB
2. `call.py search --source document --query "传感器精度要求" --kb-ids <id> --top-k 3` 拉命中 chunks
3. （按需）`call.py list_chunks --doc-ids <doc_id> --window 1` 取上下文
4. 直接基于 chunks 给用户回答 / 拼接到当前 prompt

### 工作流 B：嫁接已有 session 成果做对照分析

> "从云端 session 'ASPICE 分析' 取出 DFMEA 结论，对照本地 `src/` 下的代码，找出未覆盖的 SRS 需求。"

AI 会：

1. `call.py list_sessions --query ASPICE` 定位 session
2. `call.py get_digest --session-id <ID>` 看整体脉络、找哪几轮有关键结论
3. `call.py get_round --round-id N --session-id <ID>` 取结论轮
4. 必要时 `call.py download --path ... --out ./artifacts/xxx.docx` 拿原文
5. 本地 Read/Grep 扫 `src/` 做比对，产出分析报告

### 工作流 C：派发任务给已有 session 跑新一轮

> "让 'ASPICE 分析' session 重新跑一轮，这次重点对照新版 SRS。"

AI 会：

1. `call.py list_sessions --query ASPICE` 确认目标 session 存在
2. `call.py dispatch_task --session-id <名称或UUID> --prompt "..."` 异步派发
3. 等 30s ~ 数分钟（重 agent 单轮 1–5 分钟）
4. `call.py search --source round --query <prompt 关键词> --session-id <sid>` 找新 round
5. `call.py get_round --session-id <sid> --round-id <R> --epoch <E>` 取新一轮原文

> ⚠️ **dispatch 在已有 session 里起的是新 episode，round 从 R1 开始**——别用 `get_round R<原最大+1>` 找新内容，用 `search --source round` 命中里的 `round` 字段。详见 SKILL.md。

---

## 8. 环境变量

| 变量 | 用途 | 默认 |
|---|---|---|
| `GRAFT_COMBOAGENT_SERVER` | login 的默认服务器 URL | `https://xipnex.nox-lumen.com` |
| `GRAFT_COMBOAGENT_EMAIL`  | login 的默认 email | — |
| `GRAFT_COMBOAGENT_TOKEN`  | token 文件路径 | `~/.config/graft-comboagent/token.json` |
| `GRAFT_COMBOAGENT_DL_DIR` | `download` 默认落盘目录 | `./.graft/downloads/` |

---

## 9. 安全

- `~/.config/graft-comboagent/token.json` 创建时 `chmod 0600`，父目录 `0700`
- 密码**全程不落盘**：命令行优先、其次 `getpass` 从 TTY 读，RSA 加密后只走网络传输
- Token 撤销：在任何其他客户端重新 login 一次，旧 token 因 `user.access_token` 被重置自然失效
- **写边界很窄**：除 `dispatch_task` 外所有命令均为只读；`call.py` 在分发前会拒绝任何 `rm` / `delete` / `remove` / `save` / `create` / `update` / `patch` / `put` / `copy_kb_document` / `register_artifact` 类 action；写/删请走前端 UI
- `dispatch_task` 仅向已存在的 session 排队执行，**不创建 / 不修改 / 不删除任何持久化资源**

---

## 10. 已知限制（当前版本）

- **几乎只读**：除 `dispatch_task` 受控写入口外，graft 不能写回云端 session；要新建 session / 上传文档请走云端前端 UI
- **dispatch 不能创建 session**：必须派发到**已存在**的 session，目标 session 不在你的可见范围（owner 或共享）会拒绝
- **dispatch 不支持 wait=True**：HTTP 端点立即返回 queued=true；要等结果用 `search --source round` 或 `get_round` 轮询
- **dispatch prompt ≤ 32 KB**：超出会拒绝；拆成多次 dispatch 即可
- **单 profile**：一次只能登录一个 ragbase server；要切换需 `logout.py` 后重 `login.py`（或设置 `GRAFT_COMBOAGENT_TOKEN` 指向不同文件）
- **浏览器级 SSO 不支持**：只支持 email + password
- **单次下载 ≤ 200 MB**（服务端硬上限，防止误操作拖爆带宽）

---

## 11. 故障排查

| 症状 | 解决 |
|---|---|
| `[FATAL] public.pem 不存在` | 确认 skill 目录根下有 `public.pem`；从 ragbase `conf/public.pem` 复制 |
| `[FATAL] 服务器没有返回 signed_auth_token` | 服务端没部署 login 响应追加字段的改动，联系管理员升级 |
| `[ERR] 未登录` | 先 `python scripts/login.py` |
| `HTTP 401 / 认证失效` | `access_token` 被别处 login 重置，重新 login |
| 所有命令一致 401 / Not Found / DNS 失败 | server URL 不对（默认指向公有云，但你账号在自部署）；或临时 cloudflare tunnel 地址变了。`whoami.py` 看当前 server，不对就 `logout && login --server <真实 server>` |
| `Access denied` | 目标 session 不在当前 user 的可见范围（自己的 + 共享） |
| `Action ... not allowed via graft` | 误用了写 action；graft 几乎只读，切换到正确 action |
| `File too large for graft download` | 超过 200 MB 服务端硬上限；让产出物发布时做分卷或专用下载通道 |
| `[ERR] Not Found`（dispatch_task 调用） | 后端没部署 `/v1/graft/dispatch_task`；其他命令不受影响 |
| `[ERR] target session not found: <name>` | 名称没命中；`list_sessions --query <部分名>` 找正确 session 后用 UUID |
| `dispatch_task` 返回 ok 但 `get_round R<原最大+1>` 找不到 | dispatch 起的是**新 episode**，R 从 1 重新开始；用 `search --source round --query <prompt 关键词>` 找新 round |
| `prompt too long: ... > 32768` | dispatch 的 prompt 超过 32 KB；缩减或拆成多次 |
| `list_kbs` 返回 `create_date / update_date` 全是 null | `/v1/kb/list` 不投影时间；要看时间走 `kb_detail` |

更细的故障排查（episode 模型、`--round-id -1` 边界、`updated_at` 前进 ≠ round finalize 等）见 `SKILL.md` 的故障排查表。

---

## 12. 服务端要求

部署 skill 所需的服务端改动（已在主仓库 ragbase 落地）：

1. `api/apps/user_app.py` 的 login 端点在响应 `data` 里追加 `signed_auth_token`
2. 新增 `api/apps/graft_app.py`，暴露
   - `POST /v1/graft/memory/unified_search`
   - `GET  /v1/graft/memory/download`
   - `POST /v1/graft/dispatch_task`（受控写入口；服务端复用 `_DISPATCH_SEMAPHORE` 做并发控制）
3. 复用现有 `api/apps/kb_app.py`：
   - `POST /v1/kb/list`
   - `GET  /v1/kb/detail?kb_id=<id>`

以上端点均 `@login_required`，权限校验完全复用现有 `_verify_graft_access`（unified / download / dispatch）和 KB 现有 ACL（list / detail）。
