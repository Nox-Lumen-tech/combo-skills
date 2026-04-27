# LTM 模式提炼规则

本文档定义从 KB 中 `type=bug_record` 文档提炼 LTM `fact` 的详细逻辑。

## 提炼时机

- **触发方式**：LTM cron 定时任务（非实时）
- **频率**：跟随平台 LTM cron 周期（默认每 6 小时一次）
- **增量逻辑**：仅处理上次提炼后新增/更新的 Bug 记录
- **标记**：已处理的 Bug 记录在 metadata 中打上 `ltm_extracted_at` 时间戳

## 聚合维度

### 维度 1：模块热点（module_hotspot）

**条件**：同一 `module` 下累计 ≥3 条 Bug 记录

**输出 fact**：
```
{module} 模块历史上累计 {count} 个缺陷，
主要集中在 {top_pattern_tags}，
严重级别分布：{severity_distribution}。
审核此模块代码变更时需重点检查 {top_pattern_tags} 相关逻辑。
```

**confidence 计算**：
- base = 0.6
- Bug 数量 ≥5：+0.1
- Bug 数量 ≥10：+0.1（与上条叠加）
- 有 critical Bug：+0.1
- 最大 0.95

**tags**：`["bug_pattern", "module:{module}", "pattern:{top_tag1}", "pattern:{top_tag2}"]`

---

### 维度 2：跨模块系统性问题（cross_module_pattern）

**条件**：同一 `pattern_tag` 在 ≥2 个不同 `module` 中出现

**输出 fact**：
```
{pattern_tag} 类问题在 {module_list} 等 {module_count} 个模块中均有出现，
累计 {total_count} 个相关缺陷，属于项目级系统性风险。
审核任何模块时若涉及 {pattern_tag} 相关逻辑均需加强检查。
```

**confidence 计算**：
- base = 0.65
- 涉及模块 ≥3：+0.1
- 总 Bug 数 ≥5：+0.1
- 最大 0.95

**tags**：`["bug_pattern", "cross_module", "pattern:{pattern_tag}"]`

---

### 维度 3：高频缺陷文件（file_hotspot）

**条件**：同一 `affected_files` 元素在 ≥2 条 Bug 中出现

**输出 fact**：
```
{file_path} 是高频缺陷文件，历史上关联 {count} 个 Bug，
涉及问题类型：{pattern_tags}。
当此文件有变更时需格外仔细审核。
```

**confidence 计算**：
- base = 0.7
- Bug 数量 ≥3：+0.1
- 有 critical Bug：+0.1
- 最大 0.95

**tags**：`["bug_pattern", "file_hotspot", "file:{file_path}"]`

---

### 维度 4：反复出现的根因模式（recurring_root_cause）

**条件**：
1. 对所有 Bug 的 `root_cause` 字段提取关键词
2. 同一关键词组合在 ≥3 条 Bug 中重复出现
3. 关键词判断用简单的 TF-IDF 或共现分析（由 LLM 在 cron 中执行）

**输出 fact**：
```
项目中反复出现 "{root_cause_summary}" 类根因问题，
涉及 {bug_id_list} 等 {count} 个缺陷。
建议在审核中针对此类问题设立专项检查点。
```

**confidence 计算**：
- base = 0.6
- 关键词精确匹配（而非模糊）：+0.15
- 涉及 Bug ≥5：+0.1
- 最大 0.95

**tags**：`["bug_pattern", "recurring_root_cause", "cause:{keyword}"]`

---

## fact 去重与更新

| 场景 | 处理 |
|------|------|
| 新 Bug 导入后，某 module 的 Bug 数从 2 → 3 | 新增 module_hotspot fact |
| 新 Bug 导入后，某 module 已有 fact，Bug 数从 5 → 8 | 更新 fact 内容和 confidence |
| Bug 被标记为 `rejected`/误报 | 下次 cron 时重算，必要时降低 confidence 或删除 fact |
| 同一模式的 fact 已存在 | 用 `metadata.source_bug_ids` 比对，更新而非新增 |

## 输出格式

每条提炼出的 fact 写入 LTM 时的完整结构：

```json
{
  "type": "fact",
  "content": "<人类可读的模式描述>",
  "confidence": 0.85,
  "tags": ["bug_pattern", "module:xxx", "pattern:yyy"],
  "metadata": {
    "source_bug_ids": ["BUG-1", "BUG-2", "BUG-3"],
    "extraction_type": "<module_hotspot|cross_module_pattern|file_hotspot|recurring_root_cause>",
    "extraction_dimension": "<维度名>",
    "project": "<项目标识>",
    "ltm_extracted_at": "2025-04-07T12:00:00Z",
    "bug_count": 3,
    "severity_distribution": {"critical": 1, "major": 1, "minor": 1}
  }
}
```

## 容量保护

| 维度 | 上限 | 超出处理 |
|------|------|---------|
| 单次提炼产出的 fact 数 | 100 条 | 按 confidence 降序取前 100 |
| 单条 fact content 长度 | 1,000 字符 | 截断 |
| source_bug_ids 数量 | 50 | 取最近的 50 条 |
