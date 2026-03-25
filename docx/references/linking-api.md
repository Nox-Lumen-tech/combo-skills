# 链接步骤 API 参考

> Agent 执行书签/超链接/批量链接任务前 `read_file` 此文档。

## docx_link_engine — 书签 & 超链接

```python
from ragbase_skills.docx import docx_link_engine as dle
```

### 书签

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `insert_bookmark` | `(docx, text, bookmark_name, out, occurrence=0, nearby="", para_range=None)` | `bool` | 在**包含 text 的段落**上加书签 |
| `insert_bookmark_on_run` | `(docx, text, bookmark_name, out, occurrence=0, nearby="", para_range=None)` | `bool` | 在**包含 text 的 run** 上加书签（更精准） |
| `batch_insert_bookmarks` | `(docx, bookmark_specs, out)` | `int` | 批量加书签，`bookmark_specs` = `List[Tuple[str, str]]`（text, name） |
| `batch_insert_bookmarks_on_run` | `(docx, bookmark_specs, out)` | `int` | 批量 run 级书签（一次 unzip） |

### 内部超链接（同文档跳转）

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `insert_internal_hyperlink` | `(docx, text, bookmark_name, link_text=None, out="", occurrence=0, nearby="", para_range=None)` | `bool` | 将 text 替换为指向 bookmark_name 的超链接 |

### 跨文档超链接

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `insert_cross_document_hyperlink` | `(docx, text, target_doc, bookmark_name, out="", occurrence=0, nearby="", para_range=None)` | `Tuple[bool, Optional[str]]` | 返回 `(success, rId)` |
| `insert_cross_document_hyperlink_on_run` | `(docx, text, target_doc, bookmark_name, link_text=None, out="", occurrence=0, nearby="", para_range=None)` | `Tuple[bool, Optional[str]]` | 只替换包含 text 的 run |
| `batch_insert_cross_document_hyperlinks_on_run` | `(docx, specs, out)` | `int` | 批量跨文档超链接。`specs` = `List[Tuple[str, str, str, Optional[str]]]`（text, target_doc, bookmark_name, link_text）。一次 unzip/zip |
| `split_run_with_cross_document_hyperlinks` | `(docx, text, targets, out="", nearby="", para_range=None)` | `Tuple[int, List[str]]` | **一对多分段链接**。将 text 拆成 N 段。`targets` = `List[Tuple[str, str]]`（target_doc, bookmark_name）。返回 `(links_created, rIds)` |
| `batch_operations` | `(docx, operations, out="")` | `dict` | **坐标驱动的批量操作（推荐）**。接收 `keyword_locator.batch_locate()` 返回的 Locator 坐标 |

### batch_operations 格式

```python
operations = [
    {"op": "bookmark",  "locator": locator_dict, "bookmark_name": "bm_FUNC_0007"},
    {"op": "hyperlink", "locator": locator_dict, "target_doc": "GAC_OUT.docx", "bookmark_name": "bm_FUNC_0007"},
    {"op": "split_hyperlink", "locator": locator_dict, "targets": [("GAC_OUT.docx", "bm_FUNC_0098"), ("GAC_OUT.docx", "bm_FUNC_0051")]},
]
```

`locator_dict` 直接使用 `keyword_locator.batch_locate()` 返回的结果 dict。

### batch_operations 返回值

```python
{
    "bookmarks": 3, "hyperlinks": 5, "splits": 2, "failed": 1,
    "failed_details": [
        {"index": 4, "op": "hyperlink", "keyword": "FUNC_0082",
         "reason": "run_not_found", "detail": "..."}
    ]
}
```

**失败 reason 码**：`nav_failed`、`keyword_not_in_para`、`run_not_found`、`coalesce_failed`、`empty_targets`、`keyword_not_in_run`、`segment_mismatch`、`unknown_op`。

### 公共参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `docx` | `str` | 输入 DOCX **本地路径** |
| `text` | `str` | 搜索文本（支持跨 run、表格内搜索） |
| `bookmark_name` | `str` | 书签名（支持中文，自动 sanitize） |
| `out` | `str` | 输出路径。空则覆盖输入 |
| `target_doc` | `str` | 目标文档的**最终输出文件名**（不是临时路径），如 `"docB.docx"` |
| `occurrence` | `int` | 第几个匹配（0 = 第一个） |
| `nearby` | `str` | 附近段落须包含此文本，消歧用 |
| `para_range` | `Tuple[int,int]` | 段落索引范围（来自 ES） |

### comment.build_mapping_comment（注释文本标准化）

```python
from ragbase_skills.docx.comment import build_mapping_comment

text = build_mapping_comment(
    match_type="一对多",
    gac_id_list=["FUNC_0103", "FUNC_0105"],
    diff_detail="核心信号完全匹配...",
    conclusion="部分差异",
)
```

Word 注释和 Excel 差异描述必须使用同一个 `diff_detail` 字段，禁止自行拼接子字段。

---

## 完整示例

```python
from ragbase_tools import init_context, read_file_bytes, write_file_bytes
from ragbase_skills.docx import docx_link_engine as dle, docx_validator
import tempfile, os, shutil

def main(**args):
    init_context(session_id=args["session_id"], user_id=args["user_id"])
    tmp = tempfile.mkdtemp(prefix="docx_")
    local = os.path.join(tmp, "input.docx")
    with open(local, "wb") as f:
        f.write(read_file_bytes("sessions/.../input.docx"))

    dle.insert_bookmark(local, "FUNC_0007", "FUNC_0007", local,
                        nearby="前雾灯", para_range=(350, 360))

    ok, rid = dle.insert_cross_document_hyperlink(
        local, "FUNC_0007", "target.docx", "target_bookmark", local,
        nearby="前雾灯", para_range=(350, 360))

    check = docx_validator.validate_docx(local)
    if not check["valid"]:
        print(f"❌ {check['errors']}")
        shutil.rmtree(tmp); return

    with open(local, "rb") as f:
        write_file_bytes("sessions/.../output.docx", f.read())
    shutil.rmtree(tmp)
```

## ⚠️ 关键陷阱

### 循环覆盖 — 多条操作必须 out=docx

```python
# ❌ docx ≠ out → 每轮从原始读，覆盖上一轮
for text, bm in pairs:
    dle.insert_bookmark(local_original, text, bm, local_output)

# ✅ out = docx → 每轮读到最新版本
for text, bm, pr in pairs:
    dle.insert_bookmark(local, text, bm, local, nearby=..., para_range=pr)
```

### 严禁混用 python-docx `doc.save()` 和 `dle.insert_*()` 循环

`doc.save()` 写内存对象到磁盘，`dle.insert_*()` 从磁盘读XML修改再写回。循环中交替调用会互相覆盖。

```python
# ❌ 循环中 doc.save() 覆盖 dle 写入的超链接
for gac_id in func_ids:
    docx_utils.safe_append_text(para, f" {gac_id}")
    doc.save(local_path)
    dle.insert_cross_document_hyperlink_on_run(local_path, gac_id, ...)

# ✅ 两阶段：先 python-docx save 一次，再批量 dle
for gac_id in func_ids:
    docx_utils.safe_append_text(para_map[gac_id], f" {gac_id}")
doc.save(local_path)

specs = [(gac_id, target_doc, gac_id, gac_id) for gac_id in func_ids]
dle.batch_insert_cross_document_hyperlinks_on_run(local_path, specs, local_path)
```

### N-to-N 双向链接

```python
# 阶段 1：两个文档各自加 bookmark
for text_a, bm_a, pr_a, nb_a, text_b, bm_b, pr_b, nb_b in mapping:
    dle.insert_bookmark(local_a, text_a, bm_a, local_a, nearby=nb_a, para_range=pr_a)
    dle.insert_bookmark(local_b, text_b, bm_b, local_b, nearby=nb_b, para_range=pr_b)

# 阶段 2：两个文档各自加 hyperlink
for text_a, bm_a, pr_a, nb_a, text_b, bm_b, pr_b, nb_b in mapping:
    dle.insert_cross_document_hyperlink(
        local_a, text_b, final_b_name, bm_b, local_a, nearby=nb_a, para_range=pr_a)
    dle.insert_cross_document_hyperlink(
        local_b, text_a, final_a_name, bm_a, local_b, nearby=nb_b, para_range=pr_b)
```
