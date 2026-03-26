---
name: eea-gac-cross-reference
description: EEA与GAC需求文档对比与交叉引用（v9-lite真值映射版）。对多份EEA需求文档与GAC需求文档进行编号、基于内容索引的语义匹配、真值映射冻结、差异分析与高亮、Word批注、双向跨文档超链接、Excel汇总表。触发短语：需求对比、交叉引用、EEA GAC 映射、需求编号。不适用场景：单文档编辑、非汽车需求文档、无映射关系的文档合并。
---

# EEA 与 GAC 需求文档对比与交叉引用（v9-lite 真值映射版）

## 概述

对多份 EEA 需求文档与 GAC 需求文档进行：唯一编号标注、基于内容索引的语义匹配、真值映射冻结、差异分析与高亮、Word 批注（注释）、双向跨文档超链接、Excel 汇总表。

## 依赖技能

| 技能 | 职责 |
|------|------|
| `/document-editing` | 工作流编排：ES 检索定位 → execute_code 编辑 → snapshot_and_index |
| `/docx` | DOCX 技术实现：ragbase_skills.docx 中的工具函数 |

## 核心原则（v9-lite）

> 完整版展开见 `references/core-principles-and-validation.md`

1. 准源分层：步骤2是内容边界准源，步骤3是映射关系准源
2. 整文件覆写，禁止 append
3. 索引卡保留整块内容
4. 一对多必须二次穷举
5. 差异阶段发现映射错误必须回退修正
6. 一条 EEA 需求只允许一条真值记录
7. GAC 反向补扫是必须步骤
8. chunk 级覆盖率按文档闭合

## 通用约束

- 禁止在最终输出文件上使用 `office.pack.py` 打包
- batch_operations() 后必须追加 python-docx resave 重新序列化

## 步骤一至步骤五

详见 references/ 目录下的详细规则文件。

| 步骤 | Reference 文件 |
|------|---------------|
| 步骤一 | references/pipeline-step1-numbering.md |
| 步骤二 | references/pipeline-step2-indexing.md |
| 步骤三 | references/pipeline-step3-mapping.md |
| 步骤四 | references/pipeline-step4-diff-highlight.md |
| 步骤五 | references/pipeline-step5-hyperlink.md |
| 核心原则 | references/core-principles-and-validation.md |
