---
name: static-analysis
description: >-
  L1 本地静态分析。调用 Checkstyle/PMD/SpotBugs/Detekt/Ruff/Bandit/Semgrep/cppcheck/clang-tidy
  等工具链对代码做客观检测，输出 CodeEvidence JSON。支持 git diff、指定路径、--all 全量扫描三档。
  触发词：静态分析、lint、跑检查工具、scan code、全量扫描、run linter、检查代码规范、安全扫描、跑 semgrep、检查漏洞、从头审、全分支审。
  不触发：当用户说"review this PR"/"review before merge"/"is this safe?"时，走 code-review skill（LLM 主观审查）。
  适用：需要对照需求文档/知识库的深度审核 → 先本地 L1 全量出 CodeEvidence → 上传云端 L2（详见 references/cloud-api-reference.md 的 "全量 + L2 组合"）。
  与 code-review 的关系：code-review = LLM 主观评审（含 diff/全分支三种场景），static-analysis = 工具客观检测（需安装工具）。两者互补，可串联使用。
---

# static-analysis

本地静态分析统一入口（L1）。自动检测语言 → 路由工具 → 合并输出 CodeEvidence JSON → 分级展示 → 辅助修复。

> 历史名称为 `code-review-local`，已重命名为 `static-analysis` 以更准确反映"跑工具检测"的职责，与 LLM 深度审核 skill `code-review` 区分。

## 核心入口

项目内置编排脚本 `scripts/code-review.sh`，它是所有静态分析工具的统一调度器：

```bash
# 审核 git diff 变更文件
bash scripts/code-review.sh

# 审核指定文件或目录
bash scripts/code-review.sh src/main/java/com/example/

# 全量扫描整个项目
bash scripts/code-review.sh --all

# 只审核 Java 代码
bash scripts/code-review.sh --lang java

# 只报告严重以上问题
bash scripts/code-review.sh --severity severe

# 输出 JSON 到文件
bash scripts/code-review.sh --output review_result.json

# 各语言组并行执行（加速大项目）
bash scripts/code-review.sh --all --parallel
```

## 工作流程

### Step 1 — 确定审核范围

按用户意图确定扫描目标，三种模式：

| 用户说 | 模式 | 脚本参数 |
|--------|------|---------|
| "静态分析" / "lint" / "检查代码规范" | **diff** — git diff 变更文件 | 无参数 |
| "扫描 src/ 目录" / "scan this file" | **target** — 指定文件或目录 | `scripts/code-review.sh src/` |
| "全量扫描" / "扫描整个项目" | **full** — 项目下全部源码 | `scripts/code-review.sh --all` |

### Step 2 — 自动检测语言 + 路由工具

脚本按文件后缀自动分组，对每个语言组按顺序执行对应工具链：

| 文件后缀 | 语言 | 工具链 |
|---------|------|--------|
| `.java` | Java | checkstyle → pmd → spotbugs → semgrep |
| `.kt` | Kotlin | detekt → semgrep |
| `.py` | Python | ruff → bandit → semgrep |
| `.c` `.cpp` `.h` | C/C++ | cppcheck → clang-tidy → semgrep |
| 其他 | — | semgrep |

- 工具没装就自动跳过，不报错
- 全没装时用 LLM 自身能力审查
- 可加 `--parallel` 让各语言组并行

### Step 3 — 合并输出 CodeEvidence JSON

所有工具结果自动去重、合并、按严重度排序，输出统一的 CodeEvidence JSON。

格式详见 [references/finding-schema.md](references/finding-schema.md)。

### Step 4 — 分级展示

拿到 JSON 结果后，按严重度分级展示给用户：

| 级别 | 含义 | 处理方式 |
|------|------|---------|
| **致命** | 空指针必现、SQL 注入、资源泄漏 | 必须修复，优先展示 + 代码上下文 |
| **严重** | 并发问题、异常吞没、类型不安全 | 强烈建议修复 |
| **一般** | 命名不规范、复杂度过高 | 列出，用户要求时辅助修复 |
| **提示** | 格式、import 顺序 | 列出即可 |

### Step 5 — 辅助修复

对致命/严重问题：
1. 展示问题代码段（带行号和上下文）
2. 解释原因和风险
3. 给出修复代码
4. 用户确认后应用

### Step 6 — 深度审核（可选）

用户说"深度审核"/"对照需求"时，将 CodeEvidence JSON 上传云端 L2 API。
详见 [references/cloud-api-reference.md](references/cloud-api-reference.md)。

**全量 + L2 组合（"从头审整个新分支"）：**

```bash
# 本地 L1 全量扫，把整分支结果落盘
bash scripts/code-review.sh --all --output /tmp/evidence.json

# 上传给 L2 → L2 用 `code_evidence` 场景接收，跳过远端 diff 拉取
curl -X POST $RAGBASE_API/api/v1/code-review/analyze \
  -H "Content-Type: application/json" \
  -d "{\"trigger\":\"cursor_skill\",\"code_evidence\":$(cat /tmp/evidence.json),
       \"review_config\":{\"review_dimensions\":[
         \"requirement_alignment\",\"design_consistency\",
         \"code_standard\",\"security\",\"performance\"
       ]}}"
```

或者跳过 L1，让 L2 自己从仓库拉整树（场景 C，仅 GitHub/GitLab/Gitee 支持）：

```bash
# Gitee 示例
curl -X POST $RAGBASE_API/api/v1/code-review/analyze \
  -d '{"trigger":"manual",
       "repo_source":{"type":"gitee","owner":"myorg","repo":"myrepo",
                      "branch":"feature/new-module"},
       "review_config":{"review_dimensions":["requirement_alignment", ...]}}'
```

L2 会自动调用 `github_get_tree` / `gitlab_get_tree` / `gitee_get_tree` 拉全分支文件，再按需读单文件。详见 `code-review` Skill `Step 1 场景 C`。

> **Gerrit 不支持全分支审**：core REST 不暴露 git tree。需要从头审 Gerrit 仓库时请改用上面三家平台，或在 sandbox 里 `git clone https://<gerrit-host>/<project>` 后跑 L1 全量。

## 工具安装

一键安装所有静态分析工具：

```bash
bash scripts/install-review-tools.sh --phase 1    # Phase 1: Java + Python + Semgrep
bash scripts/install-review-tools.sh --phase 2    # Phase 2: + Kotlin + 仓库集成
bash scripts/install-review-tools.sh --all         # 全部安装
```

安装后工具位于 `~/.review-tools/`，脚本自动识别。

## 禁止事项

- 不等工具装齐 — 有什么工具就用什么
- 不输出原始 JSON — 用脚本合并后分级展示
- 不自动修复不确定问题 — 展示后等用户确认
- 不替代深度审核 — 需要对照需求/知识库的场景引导用户走 L2

## Examples

### Example 1: Java 项目 diff 静态分析

用户: "跑一下静态分析"

```bash
bash scripts/code-review.sh
```
→ 自动检测 git diff 中 3 个 .java 文件 → 跑 checkstyle + pmd + semgrep → 输出 2 严重 + 5 一般 + 3 提示
→ 展示严重问题 + 修复建议 → 用户确认 → 应用修复

### Example 2: 全量扫描 Python 项目

用户: "全量扫描整个项目的 Python 代码"

```bash
bash scripts/code-review.sh --all --lang python
```
→ 扫描所有 .py 文件 → 跑 ruff + bandit + semgrep → 输出完整 CodeEvidence JSON

### Example 3: 深度审核

用户: "深度审核，对照需求文档"

```bash
bash scripts/code-review.sh --output /tmp/evidence.json
# 然后上传到云端 L2
curl -X POST $RAGBASE_API/api/v1/code-review/analyze \
  -H "Content-Type: application/json" \
  -d "{\"trigger\":\"cursor_skill\",\"code_evidence\":$(cat /tmp/evidence.json)}"
```
