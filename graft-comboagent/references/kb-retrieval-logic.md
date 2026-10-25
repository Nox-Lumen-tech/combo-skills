# KB 检索逻辑 — Agent 必读（self-awareness）

> 本地 agent 最容易搞错的不是「命令拼写」，而是**三条检索路径的语义**。搞错会把 `offset` 当 PDF 页码，或对大文档顺序翻页，永远读不到 page 3000+ 的 chunk。

---

## 1. 两条阶段：先找 id，再取全文

| 阶段 | 动作 | 回答的问题 |
|------|------|------------|
| **定位** | `search --source document --query "..." --kb-ids <id> [--doc-ids <doc>]` | 「哪几条 chunk 和这个问题相关？」 |
| **取全文** | `list_chunks --chunk-ids <16hex> --window 0` | 「这条 chunk 的完整正文是什么？」 |

**默认 workflow（大文档 / 标准库 / SWTD 类 PDF 一律用这个）：**

```
list_kbs / list_documents          → kb_id, doc_id
search --source document ...       → metadata.items[].chunk_id（16 位 hex）
list_chunks --chunk-ids <id> --window 0   → 该 chunk 完整文本
```

`search` 返回的 snippet 可能被 highlight 截断；**要完整 step / 表格 / 引用编号，必须第二步 `--chunk-ids`**。

---

## 2. 三条路径对比（不要混用）

| 路径 | 参数 | 适用场景 | 不适用 |
|------|------|----------|--------|
| **语义检索** | `search --source document` | 不知道 chunk 在哪、按自然语言找 | 已知 chunk_id 还要再 search |
| **按 id 精确取** | `list_chunks --chunk-ids <id> [--window N]` | search 命中后取全文；高页 chunk（page 3000+） | 不知道 id 时瞎猜 id |
| **按 doc 顺序翻页** | `list_chunks --doc-ids <id> --offset N --limit M` | 从文档**开头**顺序浏览；chunk 总数不大（见 §4） | 当 PDF 页码用；大文档「扫到某一页」 |

### `offset` 是什么

- **是**：该文档 chunk 列表里的**第几条**（0-based 游标），配合 `--limit` 翻下一批
- **不是**：PDF 页码、字节偏移、ES 的 `page` 参数

响应里的 `next_offset` / `budget_hint` 是「下一批从第几条 chunk 开始读」。

### `--window` 是什么

仅在与 `--chunk-ids` 联用时有效：

- `--window 0`：只要目标 chunk（**推荐，最稳**）
- `--window 1`：目标 + 同文档前后各 1 条 chunk（需要邻接上下文时）

---

## 3. 从 `search` 结果里拿 chunk_id

`call.py` 的 document search 走 `/v1/chunk/retrieval_test`，命中在：

```json
{
  "metadata": {
    "items": [
      {
        "chunk_id": "3b564ca1102cbcae",
        "doc_id": "...",
        "doc_name": "...",
        "content": "…片段…"
      }
    ]
  }
}
```

- 用 **`metadata.items[].chunk_id`**（16 hex）
- `content` 是预览片段，不是全文
- 若走 unified_search（session 源），id 可能在 `id` 字段；document 原生 search 已统一为 `chunk_id`

---

## 4. 工具边界（必须 self-aware）

### 大文档：`--doc-ids --offset` 有天花板

`list_chunks --doc-ids` 在客户端会先分页拉整 doc 的 chunk 列表，再 `all_chunks[offset:offset+limit]`。

当前实现：**最多拉约 10000 条**（100 页 × 每页 100）。文档若 >~10000 chunks（例如 SWTD ~10219 chunks），**列表尾部 chunk 进不了内存**，因此：

- ❌ 用 `--offset` 递增「扫到 page 3000+」——**做不到**
- ❌ 以为「offset 不够大就继续加大 offset」——**不是页码问题，是工具够不着**
- ✅ `search` 语义命中 + `--chunk-ids --window 0`——**任意位置 chunk 都能取**

### `--window > 0` 在大文档上也可能失败

邻居上下文依赖同 doc 的全量 chunk 顺序；超过 ~10000 条时，高页 chunk 可能不在 `id_order` 里，`window` 扩邻会 silently 缩水。**大文档优先 `--window 0`；要上下文就换 query 再 search 相邻段落。**

### 小文档才适合顺序翻页

`get_doc_profile` / `list_documents` 可看 chunk 规模。仅当 **total_chunks 明显 < 10000** 且任务真是「从第 1 条顺序读」时，才用：

```bash
list_chunks --doc-ids <doc_id> --offset 0 --limit 20
# 续读 metadata.next_offset
```

---

## 5. Agent 判定规则（必读）

```
用户 query 是已知字符串（ID/编号/信号名/原文短语）?  → search --exact
用户 query 是问题描述（怎么做/是什么/找相关）?      → search（混合，默认）
```

| 用户说法 | 模式 | 示例 query |
|----------|------|------------|
| 「查 TC 1023265」 | `--exact` | `1023265` |
| 「Test Case ID:1023265 在哪」 | `--exact` | `Test Case ID:1023265` 或 `1023265` |
| 「Bus Sleep 切换步骤是什么」 | 混合 | `Bus Sleep Mode transition steps` |
| 「和 CAN bus off 恢复相关的用例」 | 混合 | `Recover time of CAN bus off` |

**禁止**：混合 `search` 查 ID → 0 命中或低分噪声 → 断言「文档里没有该 ID」。必须先 `--exact`;仍 0 再怀疑 parse。

## 6. Agent 反模式（禁止）

| 反模式 | 为什么错 |
|--------|----------|
| 混合 `search` 查纯 ID 并下「不存在」结论 | 向量噪声会淹没全文命中；应用 `--exact` |
| 拿到 doc_id 后 `offset=0,20,40…` 翻完整本书 | 浪费 token；大文档还读不全 |
| 把 `offset` 换算成「PDF 第 N 页 × 每页 chunks」 | offset 单位是 chunk 序号，与 PDF 页无固定映射 |
| search 命中后不再 `list_chunks --chunk-ids`，直接用 snippet 写结论 | snippet 可能截断 / highlight 不完整 |
| 大文档 search 不到就怀疑 KB 没入库 | 应先 `--exact` / 加 `--doc-ids`，而不是 offset 扫库 |
| 用 `list_doc_chunks --page N` 当「读第 N 页 PDF」 | `--page` 是 API 分页页码，不是 PDF page_num |

---

## 7. 精确检索 `--exact`（ID / 编号 / 原文短语）

要「正文里必须含这个字符串」（不是"相关"），用 `--exact`：

```
search --source document --query "1023265" --doc-ids <doc> --exact
```

- 关掉向量（`vector_similarity_weight=0`），走纯全文
- 客户端再按**子串必含**过滤（空白/大小写不敏感，等价 `content LIKE '%q%'`）
- 通用，不限 ID —— 任何原文短语都能用

**为什么默认混合 `search` 会漏**：混合把向量占大头、全文占小头融合排序；纯数字/编号向量语义弱，即便全文命中也被低分噪声挤出 top_k。精确查找必须 `--exact`。

---

## 8. 典型场景速查

| 用户意图 | 做法 |
|----------|------|
| 「TC 1023265 在哪」（ID/编号） | `search --query 1023265 --doc-ids <swtd> --exact` → `--chunk-ids` |
| 「这条 SWTD 用例的 step 8 是什么」 | `search`（query 含用例名/step）→ `--chunk-ids` |
| 「Basetech 方法库里 CanNm 相关段落」 | `list_kbs` → `search --kb-ids …` → `--chunk-ids` |
| 「这份 doc 一共多少 chunk、什么 parser」 | `get_doc_profile` / `list_documents` |
| 「从文档开头读前 20 段摘要」 | 小 doc：`list_chunks --doc-ids … --offset 0 --limit 20` |

---

## 9. PDF 里有 ID、KB 搜不到（parse 漏索引）

**现象**：Adobe/Ctrl+F 在 PDF 里能找到 `1023265`，但 `search --exact` / `list_doc_chunks --query` 都是 0。

**原因**：KB 搜的是 **chunk 入库正文**（`content_with_weight`），不是 PDF 二进制。Parser 常漏：
- 表格里 Testcase ID 列（抽成空字段 + REQ 表）
- 扫描页 / 嵌入图里的字
- 页眉页脚与正文分 chunk 时 ID 落在未索引区域

**怎么办**：

1. **验收**：`download_document` → 本地 `grep/pdfgrep 1023265`（确认 PDF 文本层）
2. **对比**：`list_doc_chunks --doc-id … --query "1023265"`（确认 chunk 索引层）
3. **修复**（三选一）：
   - `patch_chunk`：把含 ID 的段落补进对应 chunk + re-embed
   - 前端/KB **重跑 parse**（会覆盖已有 patch，慎用）
   - 改 SWTD parser skill：解析时把 Test Case ID 写入 `important_kwd`（检索加权 5×）

---

## 10. 与 `list_doc_chunks` 的分工

| 命令 | 用途 |
|------|------|
| `list_chunks` | **RAG 检索链路**（search 后续、metadata+content 格式） |
| `list_doc_chunks` | **patch 前读正文**；`--query` 与 `--exact` 同源（纯全文） |

修 Excel 链接走 patch 流程；**精确查找用 `--exact`，自然语言用混合 `search`**。
