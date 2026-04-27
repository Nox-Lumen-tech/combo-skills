# Bug 数据 Schema 规范

本文档定义 Bug 导入时的标准字段、类型约束和校验规则。

## 字段清单

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `bug_id` | string | **是** | 缺陷编号，来源系统的唯一标识（如 `JIRA-1234`、`BUG-5678`） |
| `title` | string | **是** | 缺陷标题，简要描述问题 |
| `severity` | enum | **是** | 严重程度：`critical` / `major` / `minor` / `trivial` |
| `status` | string | 否 | 状态（`open` / `resolved` / `closed` / `rejected`），默认 `open` |
| `module` | string | 否 | 所属模块/组件名（如 `CarSyncShare`、`auth-service`） |
| `affected_files` | string[] | 否 | 涉及的源文件路径（相对路径），例如 `["src/main/java/com/x/HeartbeatChecker.java"]` |
| `language` | string | 否 | 主要编程语言（`java` / `python` / `cpp` / `javascript` / `typescript` / `go` / `kotlin`） |
| `root_cause` | string | 否 | 根因分析描述 |
| `fix_description` | string | 否 | 修复方案描述 |
| `pattern_tags` | string[] | 否 | 模式标签，用于聚合分析（如 `["null_check", "resource_leak", "timeout"]`） |
| `reporter` | string | 否 | 报告人 |
| `assignee` | string | 否 | 处理人 |
| `project` | string | 否 | 项目标识（多项目隔离用） |
| `created_at` | string | 否 | 创建时间，ISO 8601 或 `YYYY-MM-DD` |
| `resolved_at` | string | 否 | 解决时间，ISO 8601 或 `YYYY-MM-DD` |
| `description` | string | 否 | 详细描述（可含复现步骤） |
| `environment` | string | 否 | 环境信息（如 `Android 12 / API 31`） |
| `priority` | string | 否 | 优先级（`P0` / `P1` / `P2` / `P3`），与 severity 含义不同 |
| `labels` | string[] | 否 | 来源系统的原始标签 |
| `url` | string | 否 | 来源系统中该 Bug 的链接 |

## severity 取值映射

不同来源系统的 severity 字段名称不统一，导入时按以下规则映射：

| 标准值 | 等价别名 |
|--------|---------|
| `critical` | `blocker`, `fatal`, `P0`, `紧急`, `致命` |
| `major` | `high`, `P1`, `严重`, `重要` |
| `minor` | `medium`, `normal`, `P2`, `一般`, `中等` |
| `trivial` | `low`, `suggestion`, `P3`, `提示`, `轻微`, `建议` |

## 字段约束

### bug_id
- 不能为空或纯空白
- 同一批次内不可重复（重复时保留最新一条，即数组中靠后的）
- 最大长度：128 字符

### title
- 不能为空
- 最大长度：512 字符

### affected_files
- 每个元素应为相对路径（不以 `/` 开头，不含 `C:\` 等绝对路径前缀）
- 如果检测到绝对路径，自动裁剪到项目根目录之后的部分
- 单条 Bug 最多 50 个文件

### pattern_tags
- 每个 tag 为小写 + 下划线格式（如 `null_check`）
- 如果用户提供驼峰或中文，校验脚本自动转为标准格式
- 单条 Bug 最多 20 个 tag

### 日期字段
- 接受格式：`YYYY-MM-DD`、`YYYY-MM-DDTHH:MM:SSZ`、`YYYY-MM-DD HH:MM:SS`
- 无法解析时置空（不拒绝整条记录）

## JSON 格式示例

```json
{
  "bugs": [
    {
      "bug_id": "JIRA-1234",
      "title": "HeartbeatChecker 未实现断连逻辑",
      "severity": "critical",
      "status": "resolved",
      "module": "CarSyncShare",
      "affected_files": [
        "src/main/java/com/vehicle/sync/HeartbeatChecker.java",
        "src/main/java/com/vehicle/sync/ConnectionManager.java"
      ],
      "language": "java",
      "root_cause": "missCount 达到阈值后未调用 disconnectClient()，导致僵尸连接堆积",
      "fix_description": "在 checkHeartbeat() 中增加 if(missCount >= threshold) disconnectClient(clientId)",
      "pattern_tags": ["timeout", "resource_leak", "missing_disconnect"],
      "reporter": "张三",
      "assignee": "李四",
      "project": "vehicle-connectivity",
      "created_at": "2025-03-15",
      "resolved_at": "2025-03-20",
      "description": "测试环境复现：保持 10 个客户端连接，WiFi 断开后，服务端 30 分钟内未释放连接资源",
      "url": "https://jira.example.com/browse/JIRA-1234"
    }
  ]
}
```

## 数据量限制

| 维度 | 限制 | 超出时处理 |
|------|------|----------|
| 单批次记录数 | 5,000 条 | 截断并警告，建议分批导入 |
| 单文件大小 | 50 MB | 拒绝，提示分批 |
| 单条 description 长度 | 10,000 字符 | 截断并警告 |
| affected_files 数量/条 | 50 | 截断 |
| pattern_tags 数量/条 | 20 | 截断 |
