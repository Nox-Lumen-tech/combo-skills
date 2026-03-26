# 步骤四：差异分析与高亮（详细规则）

## 1. 强约束

1. 差异分析必须按 chunk_list 提取整块需求内容，不要重新退化成标题 search
2. `步骤4_差异清单.md` 只能补充差异字段，不能改映射主键
3. 如果差异分析发现「当前真值映射实际不成立」，必须返回步骤三修正真值映射
4. 最终 `{XLSX_OUT}` 的需求细节对比 sheet 中，一条真值映射只能占一行
5. 一对多必须仍是一行，GAC 编号/列表写完整列表，禁止拆多行
6. 高亮定位必须先在 source_chunk_list / target_chunk_list_map 对应范围内找锚点；只有锚点失败时才允许 fallback 到更宽文档搜索
7. 任意 fallback 都必须记入校验文件，不能静默降级
8. EEA 侧高亮必须限定在对应 EEA 输出文档、对应编号的需求范围内
9. GAC 侧高亮必须限定在对应 FUNC 所在表格范围内，禁止全局高亮所有表格
10. 映射说明与差异说明都应同步写入 Word 注释（comment），这是保留「映射关系 + 区别说明」的推荐载体
11. 注释可以承载完整目标列表，例如：`[映射] 目标: FUNC_0098, FUNC_0051；[部分差异] 信号: ...；状态: ...；触发: ...；HMI: ...`
12. 但注释不能替代可点击超链接；comment 负责「说明」，hyperlink 负责「跳转」
13. 注释锚点必须挂在原需求标题或原需求正文范围内，不要挂在后续追加的链接载体上
14. 对匹配类型 != 无对应 的记录，注释中必须显式包含完整目标编号列表；对无对应的记录，注释中必须显式写明无对应原因

## 2. 执行顺序（7 步）

1. 读取 `步骤2_需求索引.md`
2. 读取 `步骤3_真值映射.md`
3. 按 chunk_list 提取 EEA 与 GAC 的整块内容，逐项对比
4. 生成 `步骤4_差异清单.md`
5. 对所有记录，在对应 EEA 输出文档 / GAC 输出文档的需求范围内写入映射/差异注释：已匹配写入完整目标列表 + 简短差异摘要，无匹配写入无对应原因
6. 在所有 EEA 输出文档与 GAC 输出文档上做差异高亮
7. 生成 `{XLSX_OUT}` 的需求细节对比 sheet

## 3. 需求细节对比 sheet 必填字段（9 列）

| 序号 | 字段名 | 说明 |
|------|--------|------|
| 1 | EEA来源文档 | eea_source_doc |
| 2 | EEA输出文档 | eea_output_doc |
| 3 | EEA编号 | eea_id |
| 4 | EEA功能名称 | eea_name |
| 5 | GAC编号/列表 | gac_id_list（一对多时写完整列表） |
| 6 | GAC功能名称/列表 | gac_name_list |
| 7 | 匹配类型 | match_type |
| 8 | 差异描述 | 差异清单中的差异摘要 |
| 9 | 结论 | 一致 / 部分差异 / 差异较大 / 无对应 |

## 4. 注释执行要求

- 注释（comment）插入是步骤四的**必要执行项**，不是可选项
- 步骤四的 execute_code 必须先完成差异分析和高亮，然后在同一步或紧接的 execute_code 中完成注释批量插入
- **不允许**在差异分析和高亮完成后就宣布步骤四完成而跳过注释插入
- 注释插入后，校验时必须验证注释内容包含当前 session 生成的映射信息（如目标编号列表），不能仅凭「注释数量 > 0」通过校验
- 如果源文档已有旧注释，校验时必须区分旧注释和新插入的注释；只有新插入的注释数量满足要求才算通过

## 5. 步骤4_差异与高亮校验.md 完整字段结构

```json
{
  "truth_row_count": "int — 步骤3真值映射记录数",
  "detail_sheet_rows": "int — 需求细节对比 sheet 行数",
  "matched_rows": "int",
  "no_match_rows": "int",
  "docs": {
    "<doc_key>": {
      "matched_count": "int",
      "highlight_runs": "int — 高亮执行次数",
      "highlight_sample_ids": ["eea_id 样本"],
      "zero_highlight_ids": ["eea_id — 高亮为 0 的记录"],
      "anchor_fallbacks": ["记录 — 使用了 fallback 的条目"],
      "diff_comment_count": "int — 插入的注释数量",
      "comment_mapping_mirror_missing": ["eea_id — 注释缺少映射信息的记录"],
      "pass": "bool"
    }
  },
  "gac_highlight_runs": "int",
  "gac_anchor_fallbacks": ["记录 — GAC 侧 fallback"],
  "gac_diff_comment_count": "int — GAC 侧注释数量",
  "gac_comment_mapping_mirror_missing": ["gac_id — GAC 注释缺少映射信息"],
  "pass": "bool",
  "blocking_issues": ["string"]
}
```

> `docs` 中的 `<doc_key>` 是动态键，对应用户输入的各 EEA 文档标识。不硬编码固定文档名。

## 6. 校验规则（8 条）

1. `detail_sheet_rows` 必须等于 `步骤3_真值映射.md` 的真值记录数 + unmatched_gac_funcs 的行数
2. 任何已匹配文档若 `highlight_runs = 0`，校验失败
3. 如果 `步骤4_差异清单.md` 中仍出现「映射错误」结论，校验失败，必须回退步骤三修正
4. 若某条一对多在需求细节对比被拆成多行，校验失败
5. 若存在未记录的锚点 fallback，校验失败
6. 结论 != 一致的记录大面积缺少差异注释，校验失败
7. 任意文档 `comment_mapping_mirror_missing` 非空，或 `gac_comment_mapping_mirror_missing` 非空，校验失败
8. 任意文档 `diff_comment_count = 0` 或 `gac_diff_comment_count = 0`（说明注释插入步骤被跳过），校验失败

## 7. 交付门禁

- 只有当 `步骤4_差异与高亮校验.md` 的 `pass = true` 时，才允许进入步骤五
