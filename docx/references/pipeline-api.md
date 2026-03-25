# Pipeline 组合层 API 参考

> Agent 执行**多文档批量操作**或**跨文档交叉链接**前 `read_file` 此文档。

```python
from ragbase_skills.docx import docx_pipeline as pipeline
```

## 层级关系

| 层级 | 函数 | 适用场景 |
|------|------|---------|
| **Layer 0** | `keyword_locator.batch_locate` / `dle.batch_operations` | 最灵活，自定义控制每一步 |
| **Layer 1** | `pipeline.multi_doc_locate` / `pipeline.locate_and_apply` | 省去手动组装 locator→operation |
| **Layer 2** | `pipeline.bidirectional_link` | 一键完成 N 对文档双向链接 |

> 所有层级可混用。pipeline 内部调用 Layer 0 原语，不隐藏任何 API。

---

## multi_doc_locate — 跨文档批量定位

```python
results = pipeline.multi_doc_locate({
    "CHASSIS.docx": [
        {"keyword": "GAC_ESP配置_01", "context": "", "nearby": ""},
        {"keyword": "GAC_IBCS配置_01"},
    ],
    "GAC_multi.docx": [
        {"keyword": "FUNC_0028"},
    ],
})
# results["CHASSIS.docx"][0] == {"found": True, "keyword": "GAC_ESP配置_01", "paragraph_idx": 47, ...}
# results["GAC_multi.docx"][0] == {"found": True, ...}
```

**参数**: `docs_specs: Dict[str, List[Dict]]` — key=文档路径，value=`batch_locate` spec 列表

**返回**: `Dict[str, List[Dict]]` — key=文档路径，value=locator 列表（与 specs 顺序一一对应）

**内部调用**: `keyword_locator.batch_locate(doc, specs)` × N 个文档

---

## locate_and_apply — 定位+操作一步完成

```python
result = pipeline.locate_and_apply(
    doc="CHASSIS.docx",
    specs=[
        {
            "keyword": "GAC_ESP配置_01", "nearby": "ESP",
            "op": "bookmark", "bookmark_name": "bm_ESP_01",
        },
        {
            "keyword": "GAC_IBCS配置_01",
            "op": "hyperlink", "target_doc": "GAC_multi_对比版.docx", "bookmark_name": "bm_FUNC_0028",
        },
    ],
    out="CHASSIS_linked.docx",
)
```

**spec 格式** = `batch_locate` spec + 操作字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `keyword` | ✅ | 定位关键词 |
| `context` | | 同段落消歧 |
| `nearby` | | ±3 段落消歧 |
| `para_range` | | `[start, end]` 限定搜索 |
| `op` | ✅ | `"bookmark"` / `"hyperlink"` / `"split_hyperlink"` |
| `bookmark_name` | bookmark/hyperlink | 书签名 |
| `target_doc` | hyperlink | 目标文件名 |
| `targets` | split_hyperlink | `[(target_doc, bookmark_name), ...]` |

**返回**:

```python
{
    "locate_results": [...],     # 每个 spec 的定位结果（可检查/补救）
    "apply_results": {           # batch_operations 返回
        "bookmarks": 2, "hyperlinks": 1, "splits": 0, "failed": 0,
        "failed_details": [],
    },
    "not_found": [               # 定位失败的 spec（未进入 apply）
        {"keyword": "...", "spec_index": 3, "error": "..."},
    ],
}
```

**内部调用**: `batch_locate(doc, specs)` → 组装 operations → `dle.batch_operations(doc, ops, out)`

---

## bidirectional_link — N 对文档双向交叉链接

```python
result = pipeline.bidirectional_link(
    pairs=[
        {
            "doc_a": "/workspace/downloads/CHASSIS.docx",
            "doc_b": "/workspace/downloads/GAC_multi.docx",
            "mappings": [
                {
                    "keyword_a": "GAC_ESP配置制动系统提示_01",
                    "keyword_b": "FUNC_0028",
                    "bookmark_a": "bm_GAC_ESP_01",
                    "bookmark_b": "bm_FUNC_0028",
                    "match_type": "many_to_one",
                },
                {
                    "keyword_a": "GAC_ESP配置制动系统提示_02",
                    "keyword_b": "FUNC_0028",
                    "bookmark_a": "bm_GAC_ESP_02",
                    "bookmark_b": "bm_FUNC_0028",
                    "match_type": "many_to_one",
                },
            ],
        },
    ],
    output_dir="/workspace/outputs/",
    validate=True,
)
```

**4 步自动完成**:
1. doc_a 建 bookmark（所有 keyword_a）
2. doc_b 建 bookmark（所有 keyword_b）
3. doc_a 建 hyperlink → doc_b#bookmark_b
4. doc_b 建 hyperlink → doc_a#bookmark_a

**match_type 处理**:

| match_type | doc_a 操作 | doc_b 操作 |
|------------|-----------|-----------|
| `one_to_one` | bookmark + hyperlink | bookmark + hyperlink |
| `many_to_one` | bookmark + hyperlink | bookmark + hyperlink（多个 keyword_a 指向同一 keyword_b） |
| `one_to_many` | bookmark + hyperlink | bookmark + **split_hyperlink**（将 keyword_b 文本拆段，每段指向一个 doc_a bookmark） |

**mapping 字段**:

| 字段 | 必填 | 说明 |
|------|------|------|
| `keyword_a` / `keyword_b` | ✅ | 两端的关键词 |
| `bookmark_a` / `bookmark_b` | ✅ | 两端的书签名 |
| `match_type` | | 默认 `"one_to_one"` |
| `context_a` / `context_b` | | 同段落消歧 |
| `nearby_a` / `nearby_b` | | ±3 段落消歧 |
| `para_range_a` / `para_range_b` | | 限定搜索 |

**返回**:

```python
{
    "doc_results": {
        "CHASSIS.docx": {
            "out_path": "/workspace/outputs/CHASSIS.docx",
            "bookmarks": 3, "hyperlinks": 3, "splits": 0, "failed": 0,
            "not_found": [], "failed_details": [],
            "validation": {"valid": True, "errors": [], "warnings": []},
        },
        "GAC_multi.docx": { ... },
    },
    "total_bookmarks": 6,
    "total_hyperlinks": 6,
    "total_failed": 0,
}
```

---

## 常见用法

### 只做定位，自己控制操作

```python
locs = pipeline.multi_doc_locate({"A.docx": specs_a, "B.docx": specs_b})
# 检查 locs，手动构建 operations 列表
ops = [{"op": "bookmark", "locator": locs["A.docx"][0], "bookmark_name": "bm_X"}]
dle.batch_operations("A.docx", ops, "A_out.docx")
```

### 单文档批量操作（不需要跨文档）

```python
result = pipeline.locate_and_apply("report.docx", [
    {"keyword": "第一章", "op": "bookmark", "bookmark_name": "bm_ch1"},
    {"keyword": "第二章", "op": "bookmark", "bookmark_name": "bm_ch2"},
], out="report_bookmarked.docx")
```

### 完整双向链接 + 错误处理

```python
result = pipeline.bidirectional_link(pairs, output_dir="/tmp/out/", validate=True)
for doc, info in result["doc_results"].items():
    if info["not_found"]:
        print(f"⚠️ {doc}: {len(info['not_found'])} 个关键词未找到")
    if info["failed_details"]:
        for fd in info["failed_details"]:
            print(f"❌ {doc}: op={fd['op']} keyword={fd['keyword']} reason={fd['reason']}")
    if info["validation"] and not info["validation"]["valid"]:
        print(f"🔴 {doc}: 验证失败 {info['validation']['errors']}")
```
