# CSV 列名映射规则

当用户提供 CSV 格式的 Bug 数据时，校验脚本自动将非标准列名映射到标准 schema 字段。

## 映射表

| 标准字段 | 可接受的 CSV 列名（不区分大小写） |
|----------|-------------------------------|
| `bug_id` | `id`, `bug_id`, `issue_id`, `issue_key`, `key`, `defect_id`, `编号`, `缺陷编号`, `ID` |
| `title` | `title`, `summary`, `name`, `bug_title`, `issue_title`, `标题`, `摘要`, `缺陷标题` |
| `severity` | `severity`, `sev`, `level`, `bug_level`, `严重程度`, `严重级别`, `等级` |
| `status` | `status`, `state`, `bug_status`, `状态` |
| `module` | `module`, `component`, `subsystem`, `模块`, `组件`, `子系统` |
| `affected_files` | `affected_files`, `files`, `file_path`, `related_files`, `涉及文件`, `相关文件` |
| `language` | `language`, `lang`, `编程语言`, `语言` |
| `root_cause` | `root_cause`, `cause`, `root_cause_analysis`, `根因`, `根因分析`, `原因` |
| `fix_description` | `fix_description`, `fix`, `solution`, `resolution`, `修复方案`, `解决方案`, `修复` |
| `pattern_tags` | `pattern_tags`, `tags`, `labels`, `categories`, `标签`, `分类` |
| `reporter` | `reporter`, `reported_by`, `creator`, `author`, `报告人`, `创建人` |
| `assignee` | `assignee`, `assigned_to`, `owner`, `handler`, `处理人`, `负责人` |
| `project` | `project`, `project_name`, `project_key`, `项目`, `项目名` |
| `created_at` | `created_at`, `created`, `create_date`, `create_time`, `创建时间`, `创建日期` |
| `resolved_at` | `resolved_at`, `resolved`, `resolve_date`, `closed_at`, `closed_date`, `解决时间`, `关闭时间` |
| `description` | `description`, `desc`, `detail`, `details`, `描述`, `详细描述`, `详情` |
| `priority` | `priority`, `pri`, `优先级` |
| `url` | `url`, `link`, `issue_url`, `链接` |

## CSV 特殊字段处理

### 列表字段（affected_files, pattern_tags, labels）

CSV 中列表字段用以下分隔符之一分割：

- 分号 `;`（优先）
- 竖线 `|`
- 逗号 `,`（仅当字段被引号包裹时）

示例：
```csv
affected_files
"src/A.java;src/B.java;src/C.java"
"src/D.java|src/E.java"
```

### severity 映射

CSV 中 severity 列的值按 [bug-schema.md](bug-schema.md) 中的 severity 取值映射表转换。

### 编码

- 优先尝试 UTF-8
- 回退到 GBK/GB2312（处理中文系统导出的 CSV）
- 检测 BOM 标记并自动跳过

### 表头行

- 自动检测第一行是否为表头（通过匹配已知列名）
- 如果第一行全为数据，提示用户手动指定列名映射
