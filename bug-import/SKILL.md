---
name: bug-import
description: 被测代码的历史缺陷数据导入与模式积累。从 Jira/Redmine/TAPD 或手动 JSON/CSV 导入 Bug 记录到知识库（KB），并通过定时 LTM 提取积累跨 Bug 的模式洞察，辅助 L2 代码审核。触发："导入 Bug 数据"、"上传缺陷记录"、"导入 Jira bug"、"历史 bug 分析"、"缺陷模式提取"。不适用于平台自身运行错误（那是 error_pattern），也不适用于代码审核执行本身。
license: MIT
metadata:
  author: ragbase-team
  version: "1.0.0"
  source: Nox-Lumen-tech/combo-skills/bug-import
  tags: [bug, defect, import, kb, ltm, code-review, quality]
execution_mode: sandbox
---

# Bug 数据导入与模式积累

将被测代码的历史缺陷记录导入 KB，定时从中提炼长期模式写入 LTM，在 L2 审核时提供两层命中：KB 搜到具体 Bug，LTM 提供积累的规律洞察。

## 重要区分

| 概念 | 本 Skill 处理的 | 不处理的 |
|------|----------------|---------|
| Bug 数据 | **被测代码**的历史缺陷（来自 Jira/Redmine/TAPD） | 平台执行报错 |
| LTM 类型 | 提炼为 `fact`（领域知识） | `error_pattern`（平台运行错误） |
| 数据节奏 | 定时批量积累 | 实时提取 |

## 前置条件

1. 用户准备 Bug 数据（JSON 或 CSV 格式），符合 [references/bug-schema.md](references/bug-schema.md) 中的字段规范
2. 可参考 [assets/bug-template.json](assets/bug-template.json) 或 [assets/bug-template.csv](assets/bug-template.csv) 模板

## 工作流

```
用户提供 Bug 数据文件（JSON/CSV）
        │
        ▼
Phase 1: 校验 — 确保数据符合 Schema
        │
        ▼
Phase 2: 导入 — 写入 KB 并建立索引
        │
        ▼
Phase 3: 定时提炼 — LTM cron 从 KB Bug 数据中积累模式
        │
        ▼
L2 审核时: KB 直接命中具体 Bug + LTM fact 命中积累模式
```

---

## Phase 1: 数据校验

用 `execute_code` 在 sandbox 中运行校验脚本：

```bash
python3 /workspace/builtin-skills/bug-import/scripts/validate_bugs.py \
  --input bugs.json \
  --max-records 5000 \
  --timeout 60 \
  --output validated_bugs.json
```

校验脚本位于 [scripts/validate_bugs.py](scripts/validate_bugs.py)，执行以下确定性检查：

| 检查项 | 规则 | 失败处理 |
|--------|------|---------|
| 必填字段 | `bug_id`, `title`, `severity` 不能为空 | 跳过该条并报告 |
| severity 取值 | 必须为 `critical / major / minor / trivial` | 拒绝该条 |
| bug_id 唯一性 | 同一批次内不能重复 | 去重保留最新 |
| 日期格式 | `created_at`, `resolved_at` 需为 ISO 8601 或 `YYYY-MM-DD` | 尝试解析，失败则置空 |
| 文件路径格式 | `affected_files` 元素不含绝对路径前缀 | 自动裁剪 |
| 单批次上限 | 最多 5000 条 | 超出截断并警告 |
| 总大小 | 单文件不超过 50MB | 拒绝并提示分批 |

校验通过后输出清洗后的标准 JSON，包含统计摘要：

```json
{
  "total_input": 1234,
  "valid": 1200,
  "skipped": 34,
  "skipped_reasons": {"missing_bug_id": 12, "invalid_severity": 8, "duplicate": 14},
  "records": [...]
}
```

如果用户提供的是 CSV，校验脚本自动检测并转换（列名映射规则见 [references/csv-mapping.md](references/csv-mapping.md)）。

---

## Phase 2: 导入 KB

将校验通过的 Bug 记录存入 MemoryOS KB 层。

每条 Bug 作为一个独立的 KB document，索引字段：

| 字段 | 用途 | 检索方式 |
|------|------|---------|
| `title` + `root_cause` + `fix_description` | 全文内容 | BM25 + 向量 |
| `module` | 模块定位 | 精确过滤 |
| `affected_files` | 文件定位 | keyword 过滤 |
| `pattern_tags` | 模式分类 | keyword 过滤 |
| `severity` | 严重级别 | keyword 过滤 |
| `language` | 语言 | keyword 过滤 |
| `project` | 项目隔离 | keyword 过滤 |

调用平台 API 导入：

> **`/v1/document/upload`（multipart）** — 上传文件并触发解析 + ES 索引，内容可被 `unified_search` 检索到。`/v1/document/create` 只建空元数据（不存内容），**不适用于 Bug 导入**。

```python
import httpx, json, os, io

API_BASE = os.environ.get("RAGBASE_API_BASE", "http://localhost:9381")
TOKEN = os.environ.get("RAGBASE_TOKEN", "")
KB_ID = os.environ.get("RAGBASE_KB_ID", "")

with open("validated_bugs.json") as f:
    data = json.load(f)

imported = 0
for bug in data["records"]:
    doc_content = (
        f"# Bug: {bug['title']}\n\n"
        f"- Bug ID: {bug['bug_id']}\n"
        f"- Module: {bug.get('module', 'N/A')}\n"
        f"- Severity: {bug['severity']}\n"
        f"- Root Cause: {bug.get('root_cause', 'N/A')}\n"
        f"- Fix: {bug.get('fix_description', 'N/A')}\n"
        f"- Affected Files: {', '.join(bug.get('affected_files', []))}\n"
        f"- Tags: {', '.join(bug.get('pattern_tags', []))}\n"
    )

    filename = f"bug-{bug['bug_id']}.md"
    resp = httpx.post(
        f"{API_BASE}/v1/document/upload",
        data={"kb_id": KB_ID},
        files={"file": (filename, io.BytesIO(doc_content.encode("utf-8")), "text/markdown")},
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=30,
    )
    if resp.status_code == 200:
        imported += 1
    else:
        print(f"WARNING: {bug['bug_id']} 导入失败: {resp.status_code} {resp.text[:200]}")

print(f"导入完成: {imported}/{len(data['records'])} 条 Bug 记录")
```

> 每条 Bug 作为独立 Markdown 文件上传到 KB，平台自动解析并建立 ES 索引，可通过 `unified_search` 按 module/file/tag 检索到。

---

## Phase 3: 定时 LTM 模式提炼

**不是实时的，是定时积累的。**

LTM cron 周期运行时，如果检测到 `bug-import` skill 已安装，执行以下提炼逻辑：

### 提炼规则

从 KB 中检索所有 `type=bug_record` 的文档，按 `module` + `pattern_tags` 聚合：

| 条件 | 产出 |
|------|------|
| 同一 module 出现 ≥3 条 Bug | 提炼一条 `fact`："[module] 模块历史缺陷集中，审核时需重点关注" |
| 同一 pattern_tag 跨 ≥2 个 module | 提炼一条 `fact`："[tag] 类问题在多个模块出现，属于项目级系统性风险" |
| 同一 affected_file 出现 ≥2 条 Bug | 提炼一条 `fact`："[file] 是高频缺陷文件，审核变更时需格外仔细" |
| 同一 root_cause 关键词反复出现 | 提炼一条 `fact`：描述具体的反复出现的根因模式 |

### LTM fact 输出格式

```json
{
  "type": "fact",
  "content": "CarSyncShare 模块的心跳相关代码历史上多次出现超时未断连问题（BUG-1234, BUG-1567, BUG-1890），审核此模块时重点检查 disconnect/timeout/resource release 逻辑",
  "confidence": 0.85,
  "tags": ["bug_pattern", "module:CarSyncShare", "pattern:resource_leak", "pattern:timeout"],
  "metadata": {
    "source_bug_ids": ["BUG-1234", "BUG-1567", "BUG-1890"],
    "extraction_type": "bug_pattern_accumulation",
    "project": "vehicle-connectivity"
  }
}
```

### 提炼节奏

- 首次导入后的下一个 LTM cron 周期执行首次提炼
- 后续每次有新 Bug 导入，下一个 cron 周期增量提炼
- 已提炼的 fact 如果源 Bug 数据更新，fact 内容同步刷新

详细提炼规则见 [references/ltm-extraction-rules.md](references/ltm-extraction-rules.md)。

---

## L2 审核时的使用方式

Agent 在 L2 审核中通过 `unified_search` 获得两层命中：

**第一层：KB 直接命中**（具体 Bug 记录）
```
unified_search(query="HeartbeatChecker null check", memory_type="document", filters={"module": "CarSyncShare"})
→ "BUG-1234: HeartbeatChecker 未实现断连逻辑，missCount >= 10 时应调用 disconnectClient()"
```

**第二层：LTM fact 命中**（积累的模式洞察）
```
unified_search(query="CarSyncShare 心跳", memory_type="fact")
→ "CarSyncShare 模块心跳相关代码历史上多次出现超时未断连问题，审核时重点检查 disconnect/timeout 逻辑"
```

Agent 结合两层信息，在审核报告中引用具体 Bug 编号和模式描述。

---

## Examples

### Example 1: 导入 Jira Bug JSON

用户说：「把这份 Jira 导出的 Bug 数据导入系统」并上传 `jira-export.json`

1. 校验：`validate_bugs.py --input jira-export.json` → 1200/1234 条通过
2. 导入：逐条写入 KB，打标 `type=bug_record`
3. 反馈：「已导入 1200 条 Bug 记录，跳过 34 条（12 条缺 bug_id，8 条 severity 无效，14 条重复）」
4. 下一个 LTM cron 周期自动提炼模式

### Example 2: 导入 CSV 格式

用户说：「我有一份 CSV 的缺陷表，帮我导入」并上传 `bugs.csv`

1. 检测 CSV 格式，按 [references/csv-mapping.md](references/csv-mapping.md) 映射列名
2. 转换为标准 JSON 后走同样的校验 + 导入流程

### Example 3: 审核时命中历史 Bug

Agent 在审核 `HeartbeatChecker.java` 的变更时：
1. `unified_search` 命中 KB 中 BUG-1234（该文件历史 Bug）
2. `unified_search` 命中 LTM fact（心跳模块反复出现超时问题）
3. Agent 在审核报告中标注："此文件历史上有资源泄漏问题（BUG-1234），建议重点检查本次变更是否引入类似风险"

---

## Troubleshooting

### 导入报 "missing required field"

原因：JSON 中某条 Bug 缺少 `bug_id`、`title` 或 `severity`
解决：检查并补全必填字段，或让校验脚本自动跳过不合格记录

### CSV 列名无法识别

原因：CSV 列名与标准 schema 不匹配
解决：参见 [references/csv-mapping.md](references/csv-mapping.md) 中的别名映射表，或手动指定列名映射

### 导入后 unified_search 搜不到

原因：KB 索引尚未刷新（ES 有短暂延迟）
解决：等待 5-10 秒后重试，或确认导入 API 返回 200

### LTM 提炼未触发

原因：LTM cron 尚未到下一个执行周期
解决：这是定时任务，不是实时的。等下一个 cron 周期即可，通常间隔数小时
