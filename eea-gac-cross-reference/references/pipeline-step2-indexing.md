# 步骤二：需求索引建立 — 详细规则

## 1. 索引建立规则

- **先全量扫描**，不要先 search 再拼需求
- 每条需求必须记录**全部 `chunk_list`**
- 不允许只记录命中的一个 chunk
- 每个被扫描到的 chunk 必须归属到某条需求或写入排除清单

## 2. 索引卡必填字段（21个）

| 字段 | 说明 |
|------|------|
| doc_key | 所属文档的动态键 |
| requirement_id | 步骤一编号或 GAC FUNC 编号 |
| chunk_list | 全部归属 chunk ID 列表 |
| content_card_text | 由 chunk_list 内容按原顺序拼接归一化 |
| locate_context | requirement_id 前后各 10-15 字 |
| signal_list | 信号名 / 状态名 |
| state_value_list | 取值、状态、颜色、模式 |
| hmi_list | 图标、文字、区域 |
| trigger_list | 触发 / 解除 / 前置条件 |

## 3. 需求边界确定

- **EEA 侧**：从编号标题到下一个同级编号标题之前
- **GAC 侧**：从 FUNC 到下一个同级 FUNC 之前

## 4. 校验门禁

`步骤2_索引校验.json.pass = true`（无 orphan_chunks、覆盖率闭合）
