# 步骤五：双向超链接

## 1. 强约束

1. 超链接只消费 `步骤3_真值映射.json`
2. 定位使用 `keyword_locator.batch_locate()`
3. 所有操作通过 `docx_link_engine.batch_operations()` 一次性完成
4. **正文零新增文字**：不写 → FUNC_XXXX，映射列表统一写入注释
5. **batch_operations() 后必须执行 python-docx resave**

## 2. 编号复用链接规则

### 一对一
将编号文本整体变成跨文档超链接。

### 一对多
将编号文本拆成 N 段，每段各自变成独立跨文档超链接。

### 多对一
每个 EEA 编号完整变成 hyperlink，全部指向同一 GAC FUNC。

## 3. 执行顺序

1. 读取索引和真值映射
2. 构建 Locator Manifest
3. 构建 Operations 列表
4. 执行 batch_operations()
5. **python-docx resave**（必须步骤）
6. 生成 `需求映射` sheet
7. 写出 `步骤5_链接校验.json`

## 4. 校验门禁

`步骤5_链接校验.json.pass = true`（所有超链接可点击）
