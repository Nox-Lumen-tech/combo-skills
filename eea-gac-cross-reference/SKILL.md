---
name: eea-gac-cross-reference
description: >-
  EEA与GAC需求文档对比与交叉引用（v9-lite 真值映射版）。
  对多份 EEA 需求文档与 GAC 需求文档进行编号、映射、差异高亮、双向超链接和 Excel 汇总输出。
  EEA 文档数量不固定，GAC 文档数量不固定。
  流程：步骤一编号 → 步骤二需求索引 → 步骤三真值映射 → 步骤四差异/高亮/注释 → 步骤五超链接/Excel。
  依赖技能：/document-editing（工作流编排）、/docx（DOCX技术实现）。
license: MIT
allowed-tools: execute_code
---

# EEA 与 GAC 需求文档对比与交叉引用（v9-lite 真值映射版）

## 概述

对多份 EEA 需求文档与 GAC 需求文档进行：
- 唯一编号标注
- 基于内容索引的语义匹配
- 真值映射冻结
- 差异分析与高亮
- Word 批注（注释）
- 双向跨文档超链接
- Excel 汇总表

EEA 文档数量不固定（通常 2~5 份），GAC 文档数量不固定（通常 1 份，但也可能多份）。

## 依赖技能

| 技能 | 职责 |
|------|------|
| `/document-editing` | 工作流编排：ES 检索定位 → execute_code 编辑 → snapshot_and_index |
| `/docx` | DOCX 技术实现：ragbase_skills.docx 中的工具函数（docx_utils / docx_link_engine / keyword_locator） |

## 运行时文件名推导规则（Agent 必须在任务开始时执行）

平台技能没有 YAML frontmatter 的 inputs 字段，也没有 `{占位符}` 模板机制。Agent 必须在任务开始时根据用户输入的文档列表，自行推导所有文件名常量。

### 推导步骤

1. **识别文档类型**：从用户输入中识别所有文档，分为 EEA 文档列表和 GAC 文档列表
2. **生成 doc_key**：为每份文档生成唯一标识
   - 从文件名中提取域标识（去掉版本号、日期、人员名、括号后缀等）
   - 例：`EEA3.0组合仪表车身域系统功能需求表V2.7-20230720（0804_郭娇娇）.docx` → doc_key = `BODY`（或文件名核心标识）
   - 如果文件名无法提取有意义的域标识，使用 `EEA_1`、`EEA_2` 等序号
   - GAC 文档类似处理（如 `GAC_告警指示灯` 或 `GAC_1`）
3. **输出文件名推导**：
   - EEA_OUT / GAC_OUT = 源文件名（去掉 `.docx` 后缀）+ `_对比版.docx`
   - 例：`{src_basename}.docx` → `{src_basename}_对比版.docx`
4. **XLSX_OUT** = `需求对比与映射表.xlsx`

### 推导结果记录

Agent 必须在任务开始时将推导结果以注释或变量形式记录，并在后续所有 `execute_code` 中用变量引用，**禁止硬编码文件名字符串**。

示例（伪代码，实际在 execute_code 中实现）：

```
# 用户输入
eea_docs = [用户提供的 EEA 文档列表]
gac_docs = [用户提供的 GAC 文档列表]

# 推导 doc_key
doc_keys = {eea_docs[0]: "BODY", eea_docs[1]: "CHASSIS", ...}
gac_keys = {gac_docs[0]: "GAC_告警指示灯", ...}

# 推导输出文件名
eea_out = {src: src.replace(".docx", "_对比版.docx") for src in eea_docs}
gac_out = {src: src.replace(".docx", "_对比版.docx") for src in gac_docs}
xlsx_out = "需求对比与映射表.xlsx"
```

**⚠️ 超链接目标文件名、输出文件名必须严格使用推导出的名称。**
Agent 不要自己拼文件名、不要缩写、不要加多余后缀。

## 输入文档

- **EEA 文档**：由用户在任务开始时提供，数量不固定（≥1 份）
- **GAC 文档**：由用户在任务开始时提供，数量不固定（≥1 份）

## 最终输出

- 所有 EEA_OUT（每份 EEA 源文档对应一份 `_对比版.docx`）
- 所有 GAC_OUT（每份 GAC 源文档对应一份 `_对比版.docx`）
- `需求对比与映射表.xlsx`（包含 `需求细节对比` 和 `需求映射` 两个 sheet）

## 通用约束

- 执行过程中如果现有技能方法不能满足需求（如文档结构特殊、内容定位不准、格式效果不符合预期等），请自行编写补充代码解决，不要跳过或降级处理。
- DOCX 二进制操作必须优先使用 `ragbase_skills.docx` 中已有的工具函数，不要自己从头重写底层 XML 逻辑。
- 每步 `execute_code` 产出文档后，必须按 `/document-editing` skill 执行 `snapshot_and_index`。
- 任何步骤只要校验未通过，就不能宣称"完成"；必须输出 `TASK_PARTIAL`，并明确 blocking issue。
- 不允许只用"书签数量 / 超链接数量 / ZIP 结构正确"代替"业务覆盖率正确"。
- 一对多 / 多对一关系在中间文件中必须保留为数组，不允许在中间步骤被压成单个主匹配。
- 高亮、书签、超链接只允许消费最终通过校验的真值映射结果；禁止直接消费 partial 摘要、草稿结论或重复 append 后的临时结果。

## 核心原则（v9-lite）

### 1. 准源分层，不能混用
- `步骤2_需求索引.json` 是内容边界、chunk 归属、上下逻辑关联、锚点定位的唯一准源。
- `步骤3_真值映射.json` 是映射关系的唯一准源。
- 后续步骤不能跳过索引层重新定义需求边界，也不能跳过真值映射重新定义对应关系。
- 任何其他中间文件都不能新增、删除或改写映射关系。

### 2. 索引文件和真值文件都只允许整文件覆写，禁止 append
- `步骤2_需求索引.json` 和 `步骤3_真值映射.json` 每次更新时，必须先 `read_file` 读取旧版本，在内存中合并、去重、排序，再一次性 `write_file(mode="write")` 全量覆写。
- 不允许对索引文件或真值文件做 `append`。
- 如果上下文不够，可以把进度写到 `步骤2_索引进度.md` 或 `步骤3_搜索进度.md`，但不能直接把 partial 摘要当索引或真值。

### 3. 索引卡必须保留"整块需求内容"，不能只保留摘要
- 每条索引卡都必须生成 `content_card_text`：
  - 必须由该需求 `chunk_list` 对应的正文 / 表格 / 备注 / 删除标记内容按原始顺序拼接归一化得到
  - 后续匹配必须先比较 `content_card_text`，再用 `signal_list / state_value_list / hmi_list / trigger_list` 做辅助收敛
  - 不能只根据 `content_summary`、标题或命名关键词判定匹配

### 4. 一对多必须先做"二次穷举"再定稿
- 对任意 EEA 编号，只要确认了第 1 个 GAC FUNC 命中，不能立刻落成一对一。
- 必须继续做 3 类二次穷举：
  1. 按已确认信号名 / 状态名 / HMI 对象再次搜索 GAC
  2. 对已确认 FUNC 所在 chunk 或相邻 FUNC 做邻域扫描，找同语义 sibling FUNC
  3. 以已确认 FUNC 的功能标题为关键词，再次搜索 GAC 文档，确认是否还有同一语义簇的其他 FUNC
- 只有二次穷举完成后，才能最终确定 `gac_id_list`。

### 5. 差异阶段不能容忍"带错映射继续往下走"
- 如果步骤四发现某条映射的 FUNC 标题、信号、触发条件与真值映射不一致：
  - 不能只在差异描述里写"映射错误"然后继续
  - 必须回到 `步骤3_真值映射.json` 修正
  - 修正完成并重新校验后，才能继续差异、高亮、导表、超链接

### 6. 一条 EEA 需求只允许一条最终真值记录
- 同一 (`eea_source_doc`, `eea_id`) 在真值映射中只能出现 1 条记录。
- 一对多时，必须收敛到同一条记录的 `gac_id_list`。
- 禁止把同一 EEA 编号拆成多条一对一结果。

### 7. GAC 反向补扫是步骤三的一部分，不是可选项
- 步骤三必须先做 EEA → GAC 的正向匹配，再做 GAC → EEA 的反向补扫。
- 如果反向补扫发现某个未覆盖 GAC 实际属于已有 EEA 语义簇，必须并回原来的 `gac_id_list`，不能另起新行。

### 8. chunk 级覆盖率必须按文档闭合
- 步骤二全量扫描到的 chunk，必须满足二选一：
  - 被归入某条需求索引卡的 `chunk_list`
  - 被写入 `excluded_chunks_with_reason`
- 各 EEA 文档必须分别统计覆盖率，不能只看总量。
## 单文件累积原则

每份文档从头到尾只维护一个输出文件，每步在上面叠加修改：
- 每份 EEA 文档：`{eea_src}` → copy → `{eea_out}`（步骤一加编号 → 步骤四加高亮 → 步骤五加链接）
- 每份 GAC 文档：`{gac_src}` → copy → `{gac_out}`（步骤四加高亮 → 步骤五加链接）

**禁止产出 `_numbered.docx`、`_highlighted.docx`、`_linked.docx` 等中间文件名。**

每步 `execute_code` 都必须下载当前所有 EEA_OUT 和 GAC_OUT，修改后写回同一文件名。

## 中间文件（允许产生，但不作为最终交付物）

- `EEA_编号总表.md`
- `步骤1_编号校验.json`
- `步骤2_需求索引.json`
- `步骤2_索引进度.md`
- `步骤2_索引校验.json`
- `步骤3_真值映射.json`
- `步骤3_映射校验.json`
- `步骤4_差异清单.json`
- `步骤4_差异与高亮校验.json`
- `步骤5_链接校验.json`
- `步骤3_搜索进度.md`

---

## 步骤一：EEA 编号

### 目标
为所有 EEA 文档的 X.X 级正文子需求添加唯一编号，并产出总表。

### 编号规则
- 格式: `GAC_{一级功能名称}_{序号}`
- 编号打在**功能子模块标题**上（由阶段 A 结构探测确定哪一层是功能子模块）
- 不编号 TOC、顶层域标题、模块内部结构子节、详细说明段落、附录、配置表、按键信号定义等非目标章节
- 每份文档独立计数，每个一级功能下从 `01` 重新开始
- 编号写入各自 EEA_OUT，后续所有步骤只能引用 EEA_OUT 中真实存在的编号文本
- `{一级功能名称}` 必须是纯功能名，去掉章节编号前缀（"3.1  挡位" → "挡位"）

### 编号识别方法（强制遍历，禁止依赖样式或 ilvl）

不同 EEA 文档的 Word 样式、`numPr.ilvl`、`outlineLvl` 等 XML 属性互不一致且不可可靠。必须通过以下两阶段完成编号：

#### ⚠️ 编号粒度判断（最重要的规则，违反即判定步骤一失败）

汽车需求文档中，一个需求 = 一个功能子模块。功能子模块内部通常包含一组**固定结构子节**（概述、显示方案、交互信号定义、功能定义、功能安全需求等），这些子节**绝对不编号**。**编号只打在拥有这些结构子节的父标题上。**

模块内部结构标识词（遇到以下标题，说明该层级属于模块内部，不应编号）：
`概述`、`概要`、`显示方案`、`交互信号定义`、`信号（I/O）`、`功能定义`、`功能安全需求`、`AVNT消息中心`

#### 阶段 A — 结构探测（每份文档各执行一次）

目的：确定哪一层是"域/章"（chapter），哪一层是"功能子模块"（编号目标），哪一层是"模块内部"（不编号）。

1. 用 `docx_utils.get_body_paragraphs(doc)` 获取全部正文段落（已跳过 TOC）
2. 遍历每个段落，用正则（如 `^\d+(\.\d+)*`）提取段落文本开头的章节编号
3. 按章节编号的 `.` 分隔段数确定深度（depth 1 / 2 / 3 / ...），统计各深度段落数
4. **从最浅层逐层下探**，用"结构标识词扫描"判断编号目标层级：
   - 对深度 D 的标题集合，检查其**子标题**（深度 D+1）是否大量包含上述结构标识词
   - 如果深度 D+1 的标题中 ≥50% 匹配结构标识词 → **深度 D 就是功能子模块级 → 编号深度 D，不编号 D+1 及更深**
   - 如果深度 D+1 的标题中绝大多数不匹配结构标识词 → D+1 可能才是功能子模块 → 继续下探
5. 输出结构摘要：`chapter_depth`、`module_depth`（编号目标）、`internal_depth`（不编号）、各深度段落数、一级功能列表
6. 对于没有标准章节编号的文档，按段落文本内容和段落间的层级包含关系判断

**⚠️ 阶段 A 的输出必须明确声明 `module_depth = ?`，后续阶段 B 严格按此编号。**

#### 阶段 B — 遍历编号

基于阶段 A 确定的 `chapter_depth` 和 `module_depth` 执行编号：

1. 顺序遍历正文段落，维护 `current_chapter`（当前一级功能名称）和 `seq`（子需求序号）
2. 遇到 `chapter_depth` 层段落 → 提取纯功能名（去掉编号前缀），更新 `current_chapter`，`seq` 重置为 0
3. 遇到 `module_depth` 层段落 → `seq += 1`，用 `docx_utils.safe_append_text(para, f" (GAC_{current_chapter}_{seq:02d})")` 追加编号
4. 遇到 `module_depth` 以下的更深层段落 → **跳过，不编号**
5. 跳过附录、备注、配置表、非需求正文章节

**⚠️ 禁止**：
- 依赖 `para.style.name` 做编号判断
- 依赖 `numPr.ilvl` 或 `outlineLvl` 做编号判断
- 硬编码某份文档的一级功能名称或子需求数量

以上属性只能作为辅助参考，主判断必须基于段落文本中的章节编号模式和遍历上下文。

#### chapter 名称提取规则

`current_chapter` 必须是**纯功能名称**，不得包含章节编号前缀。
提取时用正则 `re.sub(r'^\d+(\.\d+)*\s*', '', para_text).strip()` 去掉编号前缀。

### 编号后验证（使用 keyword_locator）

编号写入后，必须用 `keyword_locator.batch_locate()` 对每个编号标签做一次定位验证：
- 确认编号确实出现在正文段落中（`found: true`，`in_table: false`）
- 确认编号没有意外写入 TOC 或表格内
- 如果任何编号定位失败，必须排查原因并修正

### 步骤一必要产物
1. 更新所有 EEA_OUT
2. 写出 `EEA_编号总表.md`
3. 写出 `步骤1_编号校验.json`

### 步骤一校验要求
- `EEA_编号总表.md` 必须按各 doc_key 分组列出全部编号
- `步骤1_编号校验.json` 必须包含：
  - `docs`（必须包含所有 EEA 文档的 doc_key）
  - `total_expected`、`total_actual`、`pass`、`blocking_issues`
  - 每个文档键下至少包含：`expected_count`、`actual_count`、`duplicate_ids`、`missing_ids`、`first_id`、`last_id`、`pass`、`structure_summary`
- 完成后必须 snapshot_and_index，并分别抽样验证每份文档的第一个和最后一个编号
- 若任意文档 `expected_count != actual_count`，或存在重复编号、缺号、缺文档统计，则步骤一失败---

## 步骤二：建立需求索引（恢复内容匹配层）

### 目标
先为所有 EEA 与 GAC 各自建立"需求索引卡"，再做后续映射。核心不是匹配，而是先稳定地定义每条需求到底由哪些 chunk 构成。

### 步骤二开始前
先快速浏览所有 EEA 文档与 GAC 文档前几页，了解整体结构和上下文（车型平台、硬件架构、章节组织方式）。注意：GAC 文档是表格结构，每个 FUNC 需求通常对应一个独立表格，FUNC 编号在表格首行。

### 执行顺序
1. 全量扫描所有 EEA_OUT，按编号切分需求边界
2. 全量扫描所有 GAC 文档，按 FUNC 切分需求边界
3. 为每条需求生成索引卡
4. 写出 `步骤2_需求索引.json`
5. 写出 `步骤2_索引校验.json`

### 索引建立规则
- 先全量扫描，不要先 search 再拼需求
- 每条需求必须明确记录自己覆盖的全部 `chunk_list`
- 不允许只记录命中的一个 chunk
- 如果一条需求跨多个 chunk，必须完整保留其全部 chunk
- 后续任何一步如果需要提取这条需求内容，必须按 `chunk_list` 读取，不允许重新退化成"标题 search + window 展开"
- `chunk_list` 必须保存真实 chunk ID，且按文档原始顺序排列
- 每个被扫描到的 chunk 必须被"归属到某条需求"或"写入排除清单并说明原因"，不允许悬空

### 全量扫描与补充召回的工具使用过程
- 建立索引时，必须按文档顺序全量扫描所有 EEA 与 GAC 的全部需求边界，不能只依赖 search 命中的局部片段
- 如果需要补充召回候选，可以先用 `unified_search(action="search", query="需求名称+功能描述", doc_ids="目标文档ID", top_k=5)` 缩小范围
- 对任何 search 命中的候选 chunk，必须再用 `unified_search(action="list_chunks", chunk_ids="命中的chunk_id", window=5)` 展开上下文
- 不允许直接用 search 返回的单个 chunk 或标题片段建立索引卡、下匹配结论或写差异描述
- 通过 search / list_chunks 找到的新内容，必须先补回 `步骤2_需求索引.json`，再进入步骤三

### 多文档索引要求
- 各 EEA 文档必须分别建立索引，不能混成一个扁平列表再丢失文档边界
- `doc_key` 必须从输入文档推导，各文档独立区分
- 同一个标题文本如果来自不同 EEA 文档，也必须保留为不同索引卡

### 需求边界确定规则（必须执行）
- EEA 侧：每份文档都要从当前 `EEA编号` 对应标题开始，到本文件下一个同级 `EEA编号` 标题之前结束
- GAC 侧：从当前 `FUNC` 对应标题 / 条目开始，到下一个同级 FUNC 或同级功能边界之前结束
- 边界内必须包含正文段落、表格、备注、删除标记 `<del>`、附属说明，不能只截标题和首段
- 若边界内某个 chunk 被判定为"仅背景 / 仅目录 / 仅分页残片"而排除，必须写入 `exclusion_notes`
- `chunk_list` 必须连续覆盖该需求边界内的有效 chunk，不能跳读

### 每条索引卡至少包含

```
doc_key, source_doc, output_doc, requirement_id, title,
outline_path, parent_heading_path, prev_requirement_id, next_requirement_id,
boundary_start_chunk, boundary_end_chunk, chunk_list, chunk_count,
content_card_text, locate_context, content_summary,
signal_list, state_value_list, hmi_list, trigger_list, scope_list,
exclusion_notes
```

### 索引提取要求
- `content_card_text` 必须由 `chunk_list` 对应内容按原顺序拼接得到，只允许做轻量归一化（去多余空白、统一标点、保留语义）
- `content_card_text` 必须保留需求整块内容中的正文、表格关键单元、备注、删除信息，不能退化成摘要
- `locate_context` 必须从 `content_card_text` 中截取 `requirement_id` 前后各 10-15 字拼成的子串，用于步骤五精确定位
- `content_summary` 必须总结该需求整块内容，不是只摘标题
- `signal_list` 必须提取信号名 / 状态名 / 关键变量
- `state_value_list` 必须提取取值、状态、颜色、模式等
- `hmi_list` 必须提取图标、文字、区域、界面表现
- `trigger_list` 必须提取触发 / 解除 / 前置条件
- `scope_list` 必须提取适用车型、版本、平台、架构说明

### `步骤2_需求索引.json` 结构要求

```json
{
  "eea_docs": {
    "<doc_key_1>": [...],
    "<doc_key_2>": [...]
  },
  "gac_index": [...],
  "metadata": {
    "index_revision": "..."
  }
}
```

> `eea_docs` 中必须包含所有 EEA 文档的 doc_key 作为键，每个键下是该文档自己的索引卡列表。

### `步骤2_索引校验.json` 必须包含

```
docs（必须包含所有 EEA 文档的 doc_key，各含 expected_count, indexed_count, total_chunks_scanned,
      assigned_chunks, orphan_chunks, excluded_chunks_with_reason, missing_chunk_list,
      empty_content_card_ids, pass）
eea_total, eea_indexed, gac_total, gac_indexed,
gac_total_chunks_scanned, gac_assigned_chunks, gac_orphan_chunks,
gac_excluded_chunks_with_reason, eea_missing_chunk_list, gac_missing_chunk_list,
empty_content_card_ids, boundary_errors, empty_summary_ids, pass, blocking_issues
```

### 步骤二交叉校验规则
- 每条索引卡的 `requirement_id` 必须在 `EEA_编号总表.md` 对应文档分组中存在
- 每条索引卡的 `title` 必须与 `EEA_编号总表.md` 中同一编号对应的标题文字一致
- 若不一致，说明该索引卡的 `chunk_list` 归属错误，必须重新定位正确的 chunk 并修正 `content_card_text`、`locate_context` 等全部派生字段
- `locate_context` 非空时，必须验证它确实是 `content_card_text` 的子串；否则清空并重新截取

### 步骤二失败条件（任一满足即失败）
- 任意需求没有 `chunk_list` 或 `chunk_count = 0`
- 任意需求 `content_card_text` 为空
- 任意 EEA 文档存在 `orphan_chunks`
- `gac_orphan_chunks` 非空
- 任意文档 `assigned_chunks + len(excluded_chunks_with_reason) != total_chunks_scanned`
- 存在 `boundary_errors`
- 任意一份 EEA 文档没有完成全量索引
- 任意 EEA 索引卡的 `requirement_id` 或 `title` 与 `EEA_编号总表.md` 不一致
- 任意索引卡 `locate_context` 非空但不是 `content_card_text` 的子串

### 步骤二交付门禁
只有当 `步骤2_索引校验.json.pass = true` 时，才允许进入步骤三。
---

## 步骤三：基于索引冻结唯一真值映射

### 目标
只做一件事，把所有 EEA 与 GAC 的最终映射关系冻结到 `步骤3_真值映射.json`。不做高亮、不做超链接、不写 Excel。

### 执行顺序
1. 读取 `步骤2_需求索引.json`
2. 先按 `content_card_text` 做主候选匹配，再用 `content_summary + signal_list + state_value_list + hmi_list + trigger_list` 做辅助收敛
3. 对候选双方按各自 `chunk_list` 提取整块内容做确认
4. 生成唯一真值映射
5. 做 GAC → EEA 反向补扫，把漏掉的候选并回已有语义簇
6. 写出 `步骤3_真值映射.json`
7. 写出 `步骤3_映射校验.json`

### 强约束
- 匹配必须先比较 `content_card_text`，再读取 `chunk_list` 对应内容确认
- 不能直接用标题或命名去匹配
- search 只允许作为"补充召回"，不是主匹配入口
- 如果 search 找到新候选，必须先补进索引卡并写回 `步骤2_需求索引.json`，然后再参与真值映射

### 一对多二次穷举规则（必须执行）
只要某个 EEA 编号确认了第一个 GAC FUNC 命中，必须继续做：
1. 基于该条索引卡的 `signal_list / state_value_list / hmi_list / trigger_list`，继续找同语义 sibling FUNC
2. 对新增 sibling FUNC 也必须读取其 `chunk_list` 对应内容做确认
3. 只有全部 sibling FUNC 确认完，才能最终确定 `gac_id_list`

### 反向补扫规则（必须执行）
- 对 GAC 文档每个 FUNC，都要反向搜索所有 EEA 的索引卡
- 若该 FUNC 实际属于某条已有 EEA 语义簇，必须并回该条记录的 `gac_id_list`
- 不能把同一 (`eea_source_doc`, `eea_id`) 拆成两条记录
- 若该 FUNC 无对应，写入 `unmatched_gac_funcs`

### `步骤3_真值映射.json` 结构要求

```json
{
  "metadata": { "source_index_revision": "..." },
  "mappings": [
    {
      "eea_source_doc": "...",
      "eea_output_doc": "...",
      "eea_id": "...",
      "eea_name": "...",
      "match_type": "...",
      "gac_id_list": ["..."],
      "gac_name_list": ["..."],
      "core_signal_evidence": "...",
      "cluster_reason": "...",
      "source_chunk_list": [...],
      "target_chunk_list_map": {...},
      "rejected_gac_candidates": [...]
    }
  ],
  "unmatched_gac_funcs": [...]
}
```

### `步骤3_映射校验.json` 必须包含

```
docs（必须包含所有 EEA 文档和 GAC 文档的 doc_key）
eea_total, eea_processed, gac_total, gac_processed,
matched_rows, no_match_rows, one_to_many_rows, multi_to_one_rows,
unmatched_gac_funcs, duplicate_eea_keys, duplicate_gac_ids_within_rows,
pass, blocking_issues
```

### 步骤三失败条件（任一满足即失败）
- 任意文档 `processed_count != expected_count`
- 同一 (`eea_source_doc`, `eea_id`) 出现多条记录
- 某条记录标为 `一对多` 但 `gac_id_list` 长度 < 2
- 某条记录没有完整的 `source_chunk_list` 或 `target_chunk_list_map`
- `metadata.source_index_revision` 不等于当前 `步骤2_需求索引.json.metadata.index_revision`
- 真值映射中仍保留明显的"映射错误但未修正"记录

### 步骤三交付门禁
只有当 `步骤3_映射校验.json.pass = true` 时，才允许进入步骤四。
---

## 步骤四：基于索引 + 真值映射生成差异、高亮与需求细节对比

### 目标
严格基于 `步骤2_需求索引.json` 和 `步骤3_真值映射.json` 做差异分析和高亮，并写出 `需求细节对比`。

### 强约束
- 差异分析必须按 `chunk_list` 提取整块需求内容
- `步骤4_差异清单.json` 只能补充差异字段，不能改映射主键
- 如果差异分析发现"当前真值映射实际不成立"，必须返回步骤三修正真值映射
- 最终 `需求细节对比` 中，一条真值映射只能占一行
- 高亮定位必须先在 `source_chunk_list / target_chunk_list_map` 对应范围内找锚点
- 映射说明与差异说明应同步写入 Word 注释（comment）
- 注释锚点必须挂在原需求标题或原需求正文范围内

### 执行内容
1. 读取 `步骤2_需求索引.json` 和 `步骤3_真值映射.json`
2. 按 `chunk_list` 提取 EEA 与 GAC 的整块内容逐项对比
3. 生成 `步骤4_差异清单.json`
4. 在所有 EEA_OUT 与 GAC_OUT 上写入映射/差异注释和高亮
5. 生成 `{XLSX_OUT}` 的 `需求细节对比` sheet

### `需求细节对比` sheet 必填字段

`EEA来源文档`、`EEA输出文档`、`EEA编号`、`EEA功能名称`、`GAC编号/列表`、`GAC功能名称/列表`、`匹配类型`、`差异描述`、`结论`

### 注释执行要求
- 注释插入是步骤四的必要执行项，不是可选项
- 已匹配：写入完整目标列表 + 简短差异摘要
- 无匹配：写入无对应原因
- 校验时必须验证注释内容包含当前 session 生成的映射信息

### `步骤4_差异与高亮校验.json` 必须包含

```
truth_row_count, detail_sheet_rows, matched_rows, no_match_rows,
docs（必须包含所有 EEA 文档的 doc_key，各含 matched_count, highlight_runs,
      highlight_sample_ids, zero_highlight_ids, anchor_fallbacks,
      diff_comment_count, comment_mapping_mirror_missing, pass）
gac_highlight_runs, gac_anchor_fallbacks, gac_diff_comment_count,
gac_comment_mapping_mirror_missing, pass, blocking_issues
```

### 步骤四校验规则
- `detail_sheet_rows` 必须等于 `步骤3_真值映射.json` 的真值记录数 + `unmatched_gac_funcs` 的行数
- 任何已匹配文档若 `highlight_runs = 0`，校验失败
- 如果 `步骤4_差异清单.json` 中仍出现"映射错误"结论，校验失败，必须回退步骤三修正
- 若某条一对多在 `需求细节对比` 被拆成多行，校验失败
- 若存在未记录的锚点 fallback，校验失败
- 结论 != 一致 的记录大面积缺少差异注释，校验失败
- 任意文档 `comment_mapping_mirror_missing` 非空，或 `gac_comment_mapping_mirror_missing` 非空，校验失败
- 任意文档 `diff_comment_count = 0` 或 `gac_diff_comment_count = 0`（说明注释插入步骤被跳过），校验失败
---

## 步骤五：基于真值映射生成超链接与需求映射

### 目标
只基于 `步骤3_真值映射.json` 结果追加链接文本、插入双向超链接、写 `需求映射` sheet。

### 强约束
- 超链接只消费 `步骤3_真值映射.json`
- **定位必须使用 `keyword_locator.batch_locate()` + 索引卡 `locate_context` 字段**；禁止用 ES `para_start_int` 做段落偏移定位
- **所有 bookmark / hyperlink / split_hyperlink 操作必须通过 `docx_link_engine.batch_operations()` 一次性完成**
- 双向链接必须是真正可点击的 Word hyperlink
- 正文中禁止追加任何新的映射文本（不写 `→ FUNC_XXXX`、不写 `→ GAC_xxx_xx`、不写 `[↗]`）
- 映射关系的完整目标列表统一写入注释（comment），不出现在正文中

### 编号复用链接规则（核心 — 正文零新增文字）
- **一对一**：把该条需求的完整编号文本整体变成一个跨文档超链接
- **一对多**：把编号文本拆成 N 段（N = 目标数量），每段各自变成一个独立跨文档超链接
  - 拆分方式：按字符均匀分段，保证每段至少 1 个字符
  - 例：`GAC_驾驶信息_09` 对应 2 个目标 → `GAC_驾驶信` 链到 FUNC_0098，`息_09` 链到 FUNC_0051
  - 例：`FUNC_0092` 对应 3 个 EEA → `FUN` 链到 GAC_驾驶信息_01，`C_0` 链到 GAC_驾驶信息_02，`092` 链到 GAC_驾驶信息_03
- **多对一**（EEA 视角多个 EEA → 同一 GAC FUNC）：
  - EEA 侧：每个 EEA 编号完整变成一个 hyperlink，全部指向同一个 GAC FUNC 的 bookmark
  - GAC 侧：该 FUNC 编号用 `split_hyperlink` 拆成 N 段，每段指向不同 EEA 编号的 bookmark
  - 来自不同 EEA 文档时，各段的 `target_doc` 必须指向正确的 EEA_OUT 文件
- 每个分段链接的目标顺序必须与注释中的目标列表顺序一致

### GAC 侧超链接规则
- 一对一：FUNC 编号整体变成一个 `hyperlink`，指向对应 EEA 编号的 bookmark
- 一对多（一个 EEA → 多个 GAC FUNC）：每个 FUNC 编号各自整体变成 `hyperlink`，全部指向同一个 EEA 编号的 bookmark
- 多对一（多个 EEA → 同一 GAC FUNC）：该 FUNC 编号用 `split_hyperlink` 拆成 N 段，每段指向不同 EEA 编号的 bookmark

### 执行内容（定位→操作两阶段管线）
1. 读取 `步骤2_需求索引.json`、`步骤3_真值映射.json`
2. **构建 Locator Manifest**：对每个已匹配编号，从索引卡取 `requirement_id` 和 `locate_context`，组成 `keyword_locator.batch_locate()` 的 specs 列表
3. **构建 Operations 列表**：根据映射类型组装 `docx_link_engine.batch_operations()` 的 operations 数组
4. 对所有 EEA_OUT 各执行 `batch_operations()`
5. 对所有 GAC_OUT 各执行 `batch_operations()`
6. 生成或覆写 `{XLSX_OUT}` 的 `需求映射` sheet
7. 写出 `步骤5_链接校验.json`

### `需求映射` sheet 必填字段

`EEA来源文档`、`EEA输出文档`、`EEA编号`、`GAC编号/列表`、`匹配类型`、`校验备注`

### `步骤5_链接校验.json` 必须包含

```
matched_rows, mapping_sheet_rows,
docs（必须包含所有 EEA 文档和 GAC 文档的 doc_key）
one_to_many_link_checks, multi_to_one_link_checks,
eea_clickable_hyperlink_count, gac_clickable_hyperlink_count,
eea_nonclickable_link_texts, gac_nonclickable_link_texts,
comment_link_overlap_errors, duplicate_eea_link_targets, duplicate_gac_link_targets,
eea_anchor_fallbacks, gac_anchor_fallbacks,
zip_validation, context_samples, pass, blocking_issues
```

### 步骤五校验规则
- `mapping_sheet_rows` 必须等于 `步骤3_真值映射.json` 中 `match_type != 无对应` 的记录数
- `one_to_many_link_checks` 必须逐条验证：期望链接数 == `gac_id_list` 长度
- `multi_to_one_link_checks` 必须逐条验证：期望链接数 == `eea_id_list` 长度或实际应补写数量
- 若某条一对多的编号分段数量与 `gac_id_list` 长度不一致，则失败
- 若某条编号的分段超链接目标与注释中目标列表顺序不一致，则失败
- 若同一个编号文本被重复处理（拆分 + 链接）两次及以上，则失败
- 若任一输出文档缺失统计，则失败
- 若存在未记录的链接锚点 fallback，则失败
- 若 `eea_nonclickable_link_texts` 或 `gac_nonclickable_link_texts` 非空，则失败
- 若存在 `comment_link_overlap_errors`，则失败

---

## 最终完成条件（必须全部满足）

- `步骤1_编号校验.json.pass = true`
- `步骤2_索引校验.json.pass = true`
- `步骤3_映射校验.json.pass = true`
- `步骤4_差异与高亮校验.json.pass = true`
- `步骤5_链接校验.json.pass = true`
- `{XLSX_OUT}` 同时包含 `需求细节对比` 和 `需求映射`
- 所有 EEA 文档全部出现在编号、索引、映射、高亮、链接统计中
- 不存在未处理的 EEA 编号
- 不存在未解释的 GAC FUNC 漏扫
- 不存在被压扁的一对多 / 多对一记录
- 不存在"差异清单已经判错，但真值映射没改"的记录

**⚠️ 如果任一条件不满足**：不要输出"任务完成"，必须输出 `TASK_PARTIAL`，列出 blocking issues，明确指出卡在哪一步。