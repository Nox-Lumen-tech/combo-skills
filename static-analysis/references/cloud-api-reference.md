# 云端 L2 深度审核 API

当用户要求"深度审核"/"对照需求"时，将 L1 本地审核的 CodeEvidence 上传到云端 L2 Agent。

## 提交审核

```
POST /api/v1/code-review/analyze
```

### Request

```json
{
  "project_id": "proj_xxx",
  "trigger": "cursor_skill",
  "code_evidence": {
    "// L1 输出的完整 CodeEvidence JSON（见 finding-schema.md）"
  },
  "review_config": {
    "review_dimensions": [
      "requirement_alignment",
      "design_consistency",
      "code_standard",
      "security",
      "performance",
      "bug_fix_validation"
    ],
    "requirement_doc_ids": ["doc_xxx"],
    "bug_ticket_ids": ["BUG-1234"],
    "priority": "normal"
  },
  "callback": {
    "type": "webhook",
    "url": "https://...",
    "auth_token": "xxx"
  }
}
```

`trigger` 取值：`gerrit_webhook` | `gitlab_mr` | `gitee_pr` | `cursor_skill` | `manual`

`code_evidence` 和 `repo_source` 二选一：
- 本地 L1 上传：传 `code_evidence`（已提取好的审核结果，可来自 `--all` 全量）
- CI/CD 触发：传 `repo_source`（Agent 自行从仓库 API 拉代码）

`repo_source` 支持两种审核模式 —— **变更审**（diff）或 **全分支审**（整树通读），由字段决定：

```json
// 变更审：必须含 change_id / mr_iid / pr_number 之一
"repo_source": {
  "type": "gerrit | gitlab | github | gitee",
  "change_id": "12345",                       // Gerrit
  "mr_iid": "78",                             // GitLab
  "pr_number": "99",                          // GitHub / Gitee
  "repo_url": "https://gerrit.internal/project"
}

// 全分支审：仅含 branch，无 change/mr/pr → 走 code-review SKILL Step 1 场景 C
// 仅 GitHub / GitLab / Gitee 支持（Gerrit 的 REST 不暴露 git tree，
// 全分支审请用前三家或 sandbox `git clone`）
"repo_source": {
  "type": "github | gitlab | gitee",
  "owner": "myorg", "repo": "myrepo",         // GitHub / Gitee
  "project": "myorg/myrepo",                  // GitLab project (path 或数字 ID 都可)
  "branch": "feature/new-module",             // 必填
  "repo_url": "https://gitee.com/myorg/myrepo"
}
```

模式判定规则：

| repo_source 含字段 | 模式 | L2 行为 |
|---|---|---|
| `change_id` / `mr_iid` / `pr_number` | 变更审 | 调 `*_get_diff` |
| 仅 `branch`（无变更标识，type ∈ github/gitlab/gitee） | 全分支审 | 调 `*_get_tree` + `*_get_file_contents`，整树通读 |
| 仅 `branch` + type=gerrit | **不支持** | 返回明确错误：建议改用 GitHub/GitLab/Gitee 或 sandbox `git clone` |
| 同时含变更标识 + branch | 变更审 | 变更标识优先，branch 仅用于二级元信息 |

### Response（异步）

```json
{
  "review_id": "rv_xxx",
  "status": "queued",
  "session_id": "sess_xxx",
  "estimated_time_seconds": 180
}
```

## 查询结果

```
GET /api/v1/code-review/{review_id}/result
```

### Response

```json
{
  "review_id": "rv_xxx",
  "status": "completed",
  "report": {
    "summary": {
      "total_findings": 23,
      "l1_findings": 15,
      "l2_findings": 8,
      "by_severity": { "fatal": 1, "severe": 4, "general": 12, "minor": 6 },
      "pass": false
    },
    "findings": [
      {
        "id": "L2-001",
        "source": "agent",
        "dimension": "requirement_alignment",
        "file": "CarSyncShareServiceImpl.java",
        "line": 89,
        "severity": "fatal",
        "category": "需求未实现",
        "title": "心跳超时机制未实现",
        "description": "需求 REQ-3.4.1.4 要求'连续10次心跳未回复则判定断连'，但代码中 HeartbeatChecker 仅记录 missCount 未做断连处理",
        "requirement_source": "WIFI分享交互需求技术规范_v1.4.pdf §3.4.1.4",
        "reasoning": "HeartbeatChecker.onMiss() 方法在 missCount >= 10 时仅打印日志，未调用 disconnectClient()",
        "suggestion": "在 onMiss() 中添加 if (missCount >= 10) { disconnectClient(clientId); }",
        "confidence": 92
      }
    ],
    "requirement_coverage": {
      "total_requirements": 41,
      "covered": 35,
      "partially_covered": 4,
      "not_covered": 2,
      "coverage_rate": "85.4%"
    },
    "artifact_path": "outputs/code_review_report.md"
  }
}
```

## status 取值

| 值 | 含义 |
|----|------|
| `queued` | 已排队，等待 Agent 处理 |
| `running` | Agent 正在执行审核 |
| `completed` | 审核完成 |
| `failed` | 审核失败（查看 error 字段） |

## L2 审核维度

| dimension | 说明 | L1 无法做到的原因 |
|-----------|------|-----------------|
| `requirement_alignment` | 需求文档 vs 代码实现的符合性 | 需要对照 KB 中的需求文档 |
| `design_consistency` | 架构设计 vs 代码结构的一致性 | 需要理解设计文档上下文 |
| `code_standard` | L1 findings 补充 + LLM 深层问题 | L1 已覆盖工具规则，L2 补充语义层 |
| `security` | 业务逻辑层面的安全问题 | 需要理解业务约束 |
| `performance` | 业务场景下的性能瓶颈 | 需要理解使用场景和数据量级 |
| `bug_fix_validation` | Bug 修复是否真正解决了问题单场景 | 需要对照 Bug ticket 原文 |
