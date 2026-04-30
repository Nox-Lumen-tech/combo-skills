# CodeEvidence JSON Schema

L1 本地审核的统一输出格式。所有静态分析工具的结果合并到此结构中。

## 完整 Schema

```json
{
  "version": "1.0",
  "timestamp": "2026-04-07T10:30:00Z",
  "repo": {
    "name": "CarSyncShare",
    "branch": "feature/wifi-share",
    "base_branch": "origin/main",
    "head_commit": "abc1234",
    "base_commit": "def5678"
  },
  "diff_summary": {
    "files_changed": 10,
    "insertions": 342,
    "deletions": 87,
    "changed_files": [
      {
        "path": "src/main/java/com/sync/CarSyncShareServiceImpl.java",
        "language": "java",
        "insertions": 45,
        "deletions": 12,
        "changed_functions": ["startShare", "handleTransfer"]
      }
    ]
  },
  "findings": [
    {
      "id": "L1-001",
      "tool": "spotbugs",
      "file": "src/main/java/com/sync/TcpServer.java",
      "line": 127,
      "end_line": 127,
      "category": "logic",
      "severity": "severe",
      "rule_id": "NP_NULL_ON_SOME_PATH",
      "title": "空指针风险",
      "description": "socket.getInputStream() 返回值未做 null 检查，当连接异常断开时可能触发 NPE",
      "suggestion": "添加 null 检查或用 try-with-resources 包裹",
      "confidence": 95
    },
    {
      "id": "L1-002",
      "tool": "semgrep",
      "file": "src/main/java/com/sync/MyWebSocketServer.java",
      "line": 43,
      "category": "security",
      "severity": "severe",
      "rule_id": "java.lang.security.audit.tainted-sql-string",
      "title": "潜在 SQL 注入",
      "description": "用户输入直接拼接到 SQL 查询字符串",
      "suggestion": "使用 PreparedStatement 参数化查询",
      "confidence": 90
    }
  ],
  "summary": {
    "total": 15,
    "by_severity": { "fatal": 0, "severe": 3, "general": 8, "minor": 4 },
    "by_category": { "syntax": 1, "standard": 6, "logic": 3, "security": 2, "performance": 3 },
    "pass": false,
    "gate_reason": "存在 3 个 severe 级别问题"
  }
}
```

## 字段说明

### severity 取值

| 值 | 含义 | 映射规则 |
|----|------|---------|
| `fatal` | 致命 — 空指针必现、SQL 注入、资源泄漏、XSS | SpotBugs error, Semgrep ERROR, Bandit HIGH |
| `severe` | 严重 — 并发问题、异常吞没、类型不安全 | PMD priority 1-2, FindSecBugs, cppcheck error |
| `general` | 一般 — 命名不规范、复杂度过高、代码冗余 | Checkstyle warning, PMD priority 3, Ruff default |
| `minor` | 提示 — 格式问题、import 顺序、注释缺失 | Checkstyle info, Ruff isort/format |

### category 取值

| 值 | 含义 |
|----|------|
| `syntax` | 语法错误 |
| `standard` | 编码规范违反 |
| `logic` | 逻辑漏洞（空指针、资源泄漏、并发） |
| `security` | 安全风险（注入、XSS、密钥泄露） |
| `performance` | 性能问题（循环冗余、低效查询） |

### 各工具 severity 映射

| 工具 | 原始级别 → severity |
|------|-------------------|
| Checkstyle | error → fatal, warning → general, info → minor |
| PMD | priority 1 → fatal, 2 → severe, 3 → general, 4-5 → minor |
| SpotBugs | High+Scary → fatal, High → severe, Normal → general, Low → minor |
| Semgrep | ERROR → fatal, WARNING → severe, INFO → general |
| Ruff | E(error) → general, W(warning) → minor, I(isort) → minor |
| Bandit | HIGH → fatal, MEDIUM → severe, LOW → general |
| cppcheck | error → fatal, warning → severe, style → general, information → minor |
| clang-tidy | error → fatal, warning → severe, note → general |
| Detekt | error → severe, warning → general, info → minor |
