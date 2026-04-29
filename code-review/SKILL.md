---
name: code-review
description: >
  企业级代码审核核心。对照需求文档/设计文档/编码规范/Bug 历史做 L2 理解性审核。
  不做静态检查（那是各语言 Skill D1-D10 的事），只做需要 LLM + 知识库才能做到的深度审核。
error_categories:
  - { name: requirement_not_implemented, severity: fatal }
  - { name: requirement_deviation, severity: severe }
  - { name: design_inconsistency, severity: severe }
  - { name: standard_violation, severity: general }
  - { name: security_risk, severity: severe }
  - { name: performance_issue, severity: general }
  - { name: bug_pattern_match, severity: severe }
  - { name: design_compliance_violation, severity: general }
---

<!-- AGENT_CONTEXT_START -->
# code-review — L2 云端深度审核

你正在执行 **L2 云端深度审核**。严格按以下六步流程执行，不可跳步。

## 职责边界

| 本 Skill 做 | 本 Skill **不做** |
|---|---|
| 需求 vs 代码的符合性审核 | 静态检查（Checkstyle/PMD/Ruff 等 → 各语言 Skill） |
| 架构设计 vs 代码结构一致性 | 代码仓库交互（→ gerrit/gitlab/gitee/github-integration） |
| Bug 修复验证 | 规范配置生成（→ standards-converter） |
| LTM 历史模式匹配 | |
| 生成结构化审核报告 | |

## 输入获取

审核任务通过 `task_params` 传入，包含：
- `repo_source`（CI/CD 触发）或 `code_evidence`（L1 上传），二选一
- `review_config.review_dimensions`：审核维度列表
- `review_config.requirement_doc_ids`：需求文档 ID（可选）
- `review_config.bug_ticket_ids`：问题单 ID（可选）
- `kb_ids`：关联知识库列表

## 六步审核流程

### Step 1: 代码获取（diff 或全量）

根据输入来源选择获取方式。**三种场景**，输入字段决定走哪条路：

| 场景 | 触发条件 | 模式 |
|---|---|---|
| A | `repo_source` 含 `change_id`/`mr_iid`/`pr_number` | **变更审**（diff） |
| B | `task_params.code_evidence` 非空 | **变更审**（L1 上传） |
| C | `repo_source` 仅含 `branch`（无 change/mr/pr 标识） | **全分支审**（整树通读） |

**场景 A — CI/CD 触发的变更审（repo_source.change_id 等）：**
使用仓库集成 Skill 的 tool 拉取 diff：
- Gerrit（默认主力）：`gerrit_get_diff(change_id="…")` — `change_id` 用会话里 `scm_tool_context.change_id`（triplet 或数字），勿手写错
- GitHub: `github_get_pr_diff(owner="...", repo="...", pull_number=123)`
- GitLab: `gitlab_get_mr_diff(mr_iid="78")`
- Gitee: `gitee_get_pr_diff(owner="...", repo="...", pr_number="99")`

**场景 B — L1 上传（code_evidence）：**
直接从 `task_params.code_evidence` 中读取 L1 输出的 CodeEvidence JSON。
- L1 默认 `git diff` 模式产物 → 走变更审
- L1 `--all` 全量产物（CodeEvidence 含全仓 finding） → 走全量审，跳过 Step 1 远端拉取

**场景 C — 全分支审（repo_source.branch，无 change/mr/pr）：**

适用：客户给定一个新分支要求"从头全面审"，没有 PR/MR/change，例如新人交付分支的入会评审。

按平台用对应"列树 + 读文件"的工具对替代 diff：

| 平台 | 列文件树 | 读单文件 | 备注 |
|---|---|---|---|
| GitHub | `github_get_tree(owner, repo, ref=branch, recursive=True)` | `github_get_file_contents(owner, repo, path, ref=branch)` | git/trees API |
| GitLab | `gitlab_get_tree(project_id, ref=branch, recursive=True)` | `gitlab_get_file_contents(project_id, path, ref=branch)` | repository/tree API |
| Gitee | `gitee_get_tree(owner, repo, ref=branch, recursive=True)` | `gitee_get_file_contents(owner, repo, path, ref=branch)` | git/trees API（GitHub 兼容；ref 留空自动解析 default_branch） |
| **Gerrit** | ❌ **不支持** | — | core REST 不暴露 git tree（已在 v3.14 文档及 gerrithub.io / googlesource / opendev 三家公网验证）。需要全分支审请改用上面三家，或在 sandbox 里 `git clone https://<gerrit-host>/<project>` 后走文件系统路径。 |

执行规则：
1. 先 `_get_tree` 拉全分支文件清单。若返回 `truncated=true`，按子目录用 `path` 参数分批降级。
2. 按文件类型/扩展名/规模分组，**优先读源码主目录**（如 `src/`、`app/`），跳过 `node_modules`、`vendor`、`dist`、二进制资源。
3. 对每个被选中的文件用 `_get_file_contents` 读全文落入工作上下文。
4. **建议先跑 L1 全量**：本地有同分支 checkout 时，让用户/上游先跑 `bash scripts/code-review.sh --all --output evidence.json` 把工具客观检测产物作为 `code_evidence` 一起注入，避免 L2 重复发现 L1 覆盖的规则类问题。

拿到代码后（场景 A/B 是 diff + 上下文，场景 C 是整树文件全文），识别文件列表、语言分布、关键模块/函数。后续 Step 2~6 共用同一流程；只在 Step 3 维度审核里做差异化（场景 C 不做"diff vs 需求"对比，改为"代码实现 vs 需求"通查）。

### Step 2: 需求基线检索

使用 `unified_search` 从知识库检索相关需求文档：

```
unified_search(action="search", query="<根据变更文件推断的需求关键词>", kb_ids=[...])
```

处理规则：
- 如果 `requirement_doc_ids` 非空，优先检索指定文档
- 提取结构化需求条目：`[{id, title, description, acceptance_criteria}, ...]`
- 建立需求-文件初步映射（根据关键词匹配）

### Step 2.5: 代码上下文补全

对 diff 涉及的文件做深度理解：

```
code_search(mode="text", pattern="<函数名/类名>", context_lines=5)
code_search(mode="ast", pattern="class $NAME extends <BaseClass>", language="java")
```

规则：
- 读取 diff 涉及的完整文件（理解函数上下文）
- 用 code_search 追踪调用链（"谁调了这个函数"）
- 代码用文件操作访问，不做向量化

### Step 3: 逐维度审核

对 `review_config.review_dimensions` 中的每个维度，逐一对比代码与 KB 知识。**diff 模式 vs 全量模式（场景 C）走法不同**：

| 维度 | diff 模式（场景 A/B） | 全量模式（场景 C） |
|---|---|---|
| `requirement_alignment` | KB 需求文档 vs 代码 diff | KB 需求文档 vs **整分支代码实现**；按需求条目反向定位代码（覆盖率统计才有意义） |
| `design_consistency` | 改动是否破坏架构 | 整分支结构是否符合架构设计 |
| `code_standard` | L1 findings 已覆盖，补充 diff 范围内深层逻辑问题 | L1 `--all` findings 已覆盖，补充全仓深层逻辑问题 |
| `security` | 业务逻辑层面：鉴权遗漏、敏感数据暴露、权限绕过（diff 范围） | 同上，扩展到全分支 |
| `performance` | diff 引入的 N+1、大循环 IO、并发问题 | 整分支热点路径排查 |
| `bug_fix_validation` | 仅 diff 模式有效（`unified_search(query="BUG-1234")` vs 代码修复） | 跳过（全分支审无修复目标） |

每个 L2 Finding 必须包含：

```json
{
  "id": "L2-001",
  "source": "agent",
  "dimension": "requirement_alignment",
  "file": "CarSyncShareServiceImpl.java",
  "line": 89,
  "severity": "fatal | severe | general | minor",
  "category": "需求未实现",
  "title": "心跳超时机制未实现",
  "description": "需求 REQ-3.4.1.4 要求'连续10次心跳未回复则判定断连'...",
  "requirement_source": "WIFI分享交互需求技术规范_v1.4.pdf §3.4.1.4",
  "reasoning": "HeartbeatChecker.onMiss() 在 missCount >= 10 时仅打印日志...",
  "suggestion": "在 onMiss() 中添加 if (missCount >= 10) { disconnectClient(clientId); }",
  "confidence": 92
}
```

### Step 4: LTM 交叉验证

**两路并查**——bug 模式和误报标记走不同存储池：

```
# ① Bug 模式池（与 bug-import 加工器同池，干净不含系统/工具运行时错误）
unified_search(action="search", sources=["fact"], tags_include=["bug_pattern"], query="<当前变更相关模式>")

# ② 误报/漏报反馈池（沿用 error_pattern；同时也会捞到平台/工具反馈，由 query 文本和 tags 区分）
unified_search(action="search", memory_type="error_pattern", query="<当前变更相关模式>")
```

- 通路 ① 命中历史 Bug 模式 → 提升置信度（这是项目级长期统计 + 实时学习的合并视角）
- 通路 ② 命中历史误报反馈 → 降低置信度或过滤
- **不要**直接用 `memory_type="error_pattern"` 检索"代码 Bug 模式"——那会把平台运行时错误一并捞回

### Step 5: 生成报告

合并 L1 findings + L2 findings，输出两份产物：

#### 5a. 结构化 JSON（机器消费）

```
write_file(
  path="outputs/code_review_report.json",
  content=<JSON>,
  artifact_type="deliverable"
)
```

JSON 结构：

```json
{
  "summary": {
    "total_findings": 23,
    "l1_findings": 15,
    "l2_findings": 8,
    "by_severity": {"fatal": 1, "severe": 4, "general": 12, "minor": 6},
    "pass": false
  },
  "findings": [...],
  "requirement_coverage": {
    "total_requirements": 41,
    "covered": 35,
    "partially_covered": 4,
    "not_covered": 2,
    "coverage_rate": "85.4%"
  }
}
```

#### 5b. HTML 可视化报告（人看）

按照 `html-report` Skill 的模板，生成自包含 HTML 文件（ECharts CDN 图表）：

```
write_file(
  path="outputs/code_review_visual_report.html",
  content=<完整 HTML>,
  artifact_type="deliverable"
)
```

HTML 报告必须包含：
- **摘要卡片**：致命 / 严重 / 一般 / 提示 的数量
- **饼图**：severity 分布
- **柱状图**：按工具或按规则类型分布
- **明细表格**：每条 finding 的文件、行号、severity、描述

参考 `html-report` Skill 的模板结构和配色规范（高危红 `#e74c3c`、中等橙 `#f39c12`、低危绿 `#27ae60`、提示蓝 `#3498db`）。

> **注意**：不需要用户额外触发"生成报告"——这是审核流程的自然输出。

### Step 6: 知识沉淀（**两路写入，互不污染**）

#### 6a. 新发现的 Bug 模式 → `fact` + `tags=["bug_pattern", ...]`

与 [`bug-import`](../bug-import/SKILL.md) 加工器**同池**，不进 `error_pattern` 池（避免与系统/工具运行时错误混杂）：

```
record_knowledge(
    knowledge_units='[{
        "knowledge_unit": "<Bug 模式描述，例如：心跳超时必须触发断连>",
        "tags": ["bug_pattern", "module:<模块名>", "pattern:<模式关键词>", "source:agent_realtime"],
        "key": "bug_pattern:<模块>:<模式键>",
        "confidence": 0.7
    }]',
    memory_type="fact"
)
```

要点：
- `tags` 必须包含 `"bug_pattern"` —— 这是与 `bug-import` 共享的检索 anchor
- `tags` 建议加 `"source:agent_realtime"` 与 bug-import 加工器（`extraction_type=*_hotspot`）区分来源
- `key` 建议拼为 `bug_pattern:<模块>:<模式键>`，同 user 同 key 自动覆盖更新

#### 6b. 误报 / 漏报反馈 → 仍走 `error_pattern`

误报/漏报本质是"审核反馈"，与 `memory-sdk` 的工具失败反馈语义一致，继续用 `error_pattern`：

```
record_knowledge(
    knowledge_units='[{
        "knowledge_unit": "<反馈说明，例如：WebSocketServer.onClose 中的空 catch 是故意吞异常，不是 Bug>",
        "tags": ["false_positive", "<module>", "<context>"]
    }]',
    memory_type="error_pattern"
)
```

`tags` 用 `"false_positive"`（误报）或 `"missed_issue"`（漏报）标记反馈类型。

#### 为什么这样分流

| 写入 | memory_type | tags anchor | 同池伙伴 |
|---|---|---|---|
| Bug 模式（命中型）| `fact` | `bug_pattern` | `bug-import` Phase 3 加工出的项目级 fact |
| 误报/漏报反馈 | `error_pattern` | `false_positive` / `missed_issue` | `memory-sdk` 工具失败反馈 |

Step 4 检索时**两池都查**，分别用 `sources=["fact"], tags_include=["bug_pattern"]` 和 `memory_type="error_pattern"` —— 互不污染。

---

如果 `callback` 配置了仓库回写，通知用户需要手动调用仓库集成 Skill 回写评论。

## 严重程度映射

| severity | 含义 | 阻断构建 |
|---|---|---|
| `fatal` | 需求未实现、核心逻辑错误 | 是 |
| `severe` | 需求偏差、安全风险、Bug 模式命中 | 是 |
| `general` | 规范违反、设计不一致、性能问题 | 否 |
| `minor` | 风格建议、注释缺失 | 否 |

<!-- AGENT_CONTEXT_END -->

<!-- COMPACTION_CONSTRAINTS_START -->
- 必须严格按六步流程执行（Step 1→6），不可跳步
- 本 Skill 不做静态检查，L1 findings 由各语言 Skill 提供
- 每个 L2 Finding 必须包含 reasoning 和 confidence 字段
- requirement_coverage 统计必须出现在最终报告中
- 报告必须同时输出 JSON 和 Markdown 两种格式
<!-- COMPACTION_CONSTRAINTS_END -->
