# graft-comboagent

> 把云端 comboagent（ragbase）的 session 成果，graft 到本地 Skill 宿主里用。

这是一个**本地 Skill 包**。任何支持 skill 机制的本地 Agent 宿主（Cursor / Claude Code / Codex 等）都可以装上它，让 AI 基于云端 session 的分析结果审查/加工本地代码。

---

## 1. 工作方式（简单说）

- **服务器端**：ragbase 暴露两个 user-level 的 HTTP 端点（`/v1/graft/memory/unified_search` + `/v1/graft/memory/download`），认证走现有 `itsdangerous` 签名的 access_token（和 web UI 完全一致）
- **客户端**：本 skill 提供 4 个 Python 脚本（login / whoami / logout / call），帮你用 email + password 登录并访问上述端点
- **AI 侧**：`SKILL.md` 指导 LLM「先 Digest、按需 drill down」，大文件走 `download` 直接落地，不塞进上下文

```
┌────────────────────────┐        ┌────────────────────────┐
│ 本地 Skill 宿主          │        │ ragbase (cloud)         │
│                        │        │                        │
│ scripts/login.py ──────┼──POST──▶ /v1/user/login          │
│                        │◀──data─ signed_auth_token        │
│  ~/.config/graft-comboagent/token.json (0600)              │
│                        │        │                        │
│ scripts/call.py <act>  ├─POST──▶ /v1/graft/memory/unified_search
│ scripts/call.py download├─GET ──▶ /v1/graft/memory/download (bytes)
│                        │        │                        │
│ AI: 按 SKILL.md 指导选   │        │ MemoryOS.unified_search│
│ 用 digest → round → ... │        │ + _verify_graft_access │
└────────────────────────┘        └────────────────────────┘
```

---

## 2. 目录结构

```
graft-comboagent/
├── SKILL.md                                 # LLM 读这个：调用方式、节流规则、使用流程
├── README.md                                # 人读这个（本文件）
├── public.pem                               # RSA 公钥（同步自 ragbase conf/public.pem）
├── references/
│   └── cross-session-retrieval.md           # 跨 session 检索的深度说明
└── scripts/
    ├── login.py                             # 登录：email + password → 保存 auth token
    ├── whoami.py                            # 显示当前登录身份
    ├── logout.py                            # 删除本地 token
    └── call.py                              # 统一调用入口（所有 action + download）
```

---

## 3. 依赖

脚本依赖两个常见库：

```bash
pip install requests pycryptodome
```

（如果 `pycryptodome` 在老环境下叫 `pycrypto`，`login.py` 会自动 fallback）

---

## 4. 安装到本地 Skill 宿主

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

## 5. 首次使用

```bash
cd ~/.cursor/skills/graft-comboagent   # 或你装到的位置

# 1) 登录（服务器 URL、email、password）
python scripts/login.py
#   ragbase server URL: https://ragbase.example.com
#   email: me@example.com
#   password: ********
#   [OK] Logged in as me@example.com (user=ab12cd34…)

# 2) 验证
python scripts/whoami.py

# 3) 试一下
python scripts/call.py list_sessions --query 冷却
python scripts/call.py get_digest --session-id "冷却系统分析"
python scripts/call.py get_round  --session-id "冷却系统分析" --round-id 5

# 4) 拿原始 docx
python scripts/call.py download --path "workspace/sessions/<sid>/output/report.docx" \
                                --out ./report.docx
file ./report.docx   # → Microsoft Word 2007+
```

---

## 6. 典型 AI 工作流（AI 不看这段，给人看）

用户在本地 IDE 里跟 AI 说：

> "从云端 session 'ASPICE 分析' 取出 DFMEA 结论，对照本地 `src/` 下的代码，找出未覆盖的 SRS 需求。"

AI（跟着 SKILL.md 走）会：

1. `call.py list_sessions --query ASPICE` 定位 session
2. `call.py get_digest --session-id <ID>` 看整体脉络、找哪几轮有关键结论
3. `call.py get_round --round-id N --session-id <ID>` 取结论轮
4. 必要时 `call.py download --path ... --out ./artifacts/xxx.docx` 拿原文
5. 本地 Read/Grep 扫 `src/` 做比对
6. 产出分析报告

---

## 7. 环境变量

| 变量 | 用途 | 默认 |
|---|---|---|
| `GRAFT_COMBOAGENT_SERVER` | login 的默认服务器 URL | — |
| `GRAFT_COMBOAGENT_EMAIL`  | login 的默认 email | — |
| `GRAFT_COMBOAGENT_TOKEN`  | token 文件路径 | `~/.config/graft-comboagent/token.json` |
| `GRAFT_COMBOAGENT_DL_DIR` | `download` 默认落盘目录 | `./.graft/downloads/` |

---

## 8. 安全

- `~/.config/graft-comboagent/token.json` 创建时 `chmod 0600`，父目录 `0700`
- 密码**全程不落盘**：命令行优先、其次 `getpass` 从 TTY 读，RSA 加密后只走网络传输
- Token 撤销：在任何其他客户端重新 login 一次，旧 token 因 `user.access_token` 被重置自然失效
- 写操作（`copy_kb_document` / `register_artifact`）在服务端被白名单拒绝

---

## 9. 已知限制（当前版本）

- 只读：graft 不能写回云端 session；产出物要在云端生成请走对应 agent
- 单 profile：一次只能登录一个 ragbase server；要切换需 `logout.py` 后重 `login.py`（或设置 `GRAFT_COMBOAGENT_TOKEN` 指向不同文件）
- 浏览器级 SSO 不支持：只支持 email + password（如需 OAuth / SSO 请提需求单）
- 单次下载 ≤ 200 MB（服务端硬上限，防止误操作拖爆带宽）

---

## 10. 故障排查

| 症状 | 解决 |
|---|---|
| `[FATAL] public.pem 不存在` | 确认 skill 目录根下有 `public.pem`；从 ragbase `conf/public.pem` 复制 |
| `[FATAL] 服务器没有返回 signed_auth_token` | 服务端没部署 login 响应追加字段的改动，联系管理员升级 |
| `[ERR] 未登录` | 先 `python scripts/login.py` |
| `HTTP 401 / 认证失效` | `access_token` 被别处 login 重置，重新 login |
| `Access denied` | 目标 session 不在当前 user 的可见范围（自己的 + 共享） |
| `Action ... not allowed via graft` | 误用了写 action；graft 只读，切换到正确 action |
| `File too large for graft download` | 超过 200 MB 服务端硬上限；让产出物发布时做分卷或专用下载通道 |

---

## 11. 服务端要求

部署 skill 所需的服务端改动：

1. `api/apps/user_app.py` 的 login 端点在响应 `data` 里追加 `signed_auth_token`
2. 新增 `api/apps/graft_app.py`，暴露
   - `POST /v1/graft/memory/unified_search`
   - `GET  /v1/graft/memory/download`

两者均 `@login_required`，权限校验完全复用现有 `_verify_graft_access`。
