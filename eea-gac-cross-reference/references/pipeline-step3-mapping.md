# 步骤三：真值映射（详细规则）

## 1. 唯一输出准则

真值映射一旦通过校验，步骤四和步骤五只能读它，不能改它。

## 2. 执行顺序

1. 读取 `步骤2_需求索引.json`
2. 按 `content_card_text` 做主候选匹配
3. 生成唯一真值映射
4. 做 GAC → EEA 反向补扫
5. 写出 `步骤3_真值映射.json`

## 3. 强约束

- 匹配必须先比较 `content_card_text`
- 不能直接用标题或命名匹配
- search 只允许作为补充召回

## 4. 一对多二次穷举

确认第 1 个 GAC 命中后，必须继续找同语义 sibling FUNC。

## 5. 结构

```json
{
  "mappings": [
    {
      "eea_id": "GAC_xxx_01",
      "match_type": "一对一 | 一对多 | 多对一",
      "gac_id_list": ["FUNC_xxx", ...]
    }
  ],
  "unmatched_gac_funcs": []
}
```

## 6. 校验门禁

`步骤3_映射校验.json.pass = true`
