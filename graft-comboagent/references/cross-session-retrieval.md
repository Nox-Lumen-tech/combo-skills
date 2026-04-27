# 跨 Session 检索 — 先看全貌，再精确取回

## §1 核心原则

读别人的 Session 和读自己的历史一样：**Digest 是目录，不是数据。**

每个 Session 的 Digest 是该 Session 所有执行轮次的结构化摘要表，包含：
- 每轮做了什么（reasoning_brief，~60 字）
- 产出了什么文件（artifacts 列表）
- 执行状态（成功/失败/部分完成）
- 轮次编号（round_id）和 Epoch

你拿到 Digest 后就知道目标 Session 的全部工作脉络，然后按需 drill down 取精确内容。

## §2 标准检索流程

### Step 1: 发现目标 Session

```
unified_search(action="list_sessions", query="关键词")
```

返回可见 Session 列表（自己的 + 共享的）。用户已说明目标名称时可跳过。

### Step 2: 获取 Digest — 看全貌

```
unified_search(action="get_digest", session_id="目标 Session 名称")
```

返回该 Session 的完整执行摘要表。从中你能看到：

| Digest 告诉你的 | 你接下来该做什么 |
|----------------|---------------|
| Round 3 产出了 `report_v2.docx` | `read_file` 或 `search_by_artifact` 取内容 |
| Round 5 做了 DFMEA 分析 | `get_round(round_id=5, session_id="X")` 取完整输出 |
| Round 7 失败了 | `get_round(round_id=7, session_id="X")` 查原因 |
| 共 12 轮，最终结论在 Round 12 | 直接取最后一轮 |

### Step 3: 精确取回

根据 Digest 中的线索选择合适的检索方式：

| 需要什么 | 用什么 |
|---------|--------|
| 某轮的完整 Agent 输出 | `get_round(round_id=N, session_id="X")` |
| 某几轮的概要 | `get_round(round_id=1, end_round=10, session_id="X")` |
| 某个产出物的内容 | `search_by_artifact(query="产出物名", session_id="X")` |
| 某个产出物的文件 | `read_file(query="文件路径", session_id="X")` |
| 按关键词搜索 | `search(source="round", query="关键词", session_id="X")` |

## §3 高效模式 vs 低效模式

**高效**（先 Digest 后定点）：
```
get_digest → 知道 Round 5 有 DFMEA 结论 → get_round(5) → 拿到精确数据
```
一次 Digest + 一次精确查询 = 2 次调用。

**低效**（盲搜）：
```
search(query="DFMEA 结论", session_id="X") → 模糊命中多条 → 逐条 get_round 确认
```
一次搜索 + N 次确认 = N+1 次调用，且可能漏掉关键内容。

## §4 多 Session 协作场景

当你需要汇总多个 Session 的成果时：

```
1. list_sessions → 发现所有相关 Session
2. 对每个 Session: get_digest → 快速了解做了什么、产出了什么
3. 根据各 Digest 的线索，有选择地 get_round / read_file 取精确内容
4. 在当前 Session 中整合、分析、产出报告
```

这比逐个 Session 盲搜效率高一个数量级，尤其当目标 Session 有几十轮执行历史时。

## §5 注意事项

- Digest 中的 reasoning_brief 只有 ~60 字，是压缩后的摘要，不能当精确数据用
- 产出物名称出现在 Digest 的 artifacts 列中，但内容需要 `read_file` 或 `search_by_artifact` 取回
- 跨 Session 读取是只读的，不会修改目标 Session 的任何数据
- 权限校验自动完成：你只能读自己的和团队共享的 Session
