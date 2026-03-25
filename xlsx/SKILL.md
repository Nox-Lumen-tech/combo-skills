---
name: xlsx
description: "Use this skill whenever the user wants to create, read, edit, or manipulate Excel spreadsheets (.xlsx/.xls files). Triggers include: any mention of \"Excel\", \"spreadsheet\", \".xlsx\", \".xls\", or requests to produce tables, reports, dashboards with cell formatting, charts, or formulas. Also use when inserting images into spreadsheets, modifying cell values, adding/deleting rows or columns, formatting cells (fonts, colors, borders), working with multiple sheets, or generating data-driven reports as Excel files. Do NOT use for Word documents (.docx), PDFs, or general coding tasks unrelated to spreadsheet generation."
---

# XLSX creation, editing, and analysis

## ⚠️ 场景选择

| 场景 | 使用的 Skill |
|------|-------------|
| **编辑知识库中的文档**（已在 ES 中有 chunks） | `document-editing` → 先 ES 检索定位 → 再用本 skill |
| **本地/新 XLSX 文件操作** | 直接使用本 skill |

**知识库文档编辑流程**（必须先完成这些步骤）：
1. `copy_kb_document(doc_id)` → 复制到 workspace
2. `unified_search(query)` → ES 检索定位，获取 `sheet_name` + `row_range` 和 `workspace_path`
3. 使用本 skill 编辑 `workspace_path` 中的文件
4. `workspace_ops(action="snapshot_and_index")` → 触发 ES 快照更新

详见 `document-editing` skill 的 `references/xlsx-editing.md`。

---

## 工具：execute_code + openpyxl

XLSX 统一通过 `execute_code` + openpyxl 编辑。沙箱镜像已预装 openpyxl、Pillow、pandas、xlrd、xlwt。

```python
from openpyxl import load_workbook

wb = load_workbook("path/to/file.xlsx")
ws = wb["Sheet1"]
ws["A1"] = "Hello"
wb.save("path/to/file.xlsx")
```

---

<!-- COMPACTION_CONSTRAINTS_START -->
1. 沙箱中直接使用 `openpyxl`（已预装），禁止 `pip install`
2. 定位必须用 `sheet_name` + `row_range`（从 ES unified_search 获取），禁止全表遍历
3. 图片插入必须用 `openpyxl.drawing.image.Image`，依赖 Pillow（已预装）
4. 保存前检查工作表名是否存在，避免 `KeyError`
5. 行号从 1 开始（openpyxl 和 Excel 一致）
<!-- COMPACTION_CONSTRAINTS_END -->

<!-- AGENT_CONTEXT_START -->
## ⛔ MANDATORY RULES（必须遵守）

### Rule 1: 沙箱中使用预装包

在 `execute_code` 中操作 XLSX 时，**直接使用预装的 openpyxl**，无需 `pip install` 或 `ensure_installed`：

```python
from ragbase_tools import init_context, read_file_bytes, write_file_bytes
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.drawing.image import Image
import tempfile, os
from io import BytesIO

def main(**args):
    init_context(session_id=args["session_id"], user_id=args["user_id"])

    tmp = tempfile.mkdtemp(prefix="xlsx_")
    xlsx_bytes = read_file_bytes("sessions/.../input.xlsx")
    local_path = os.path.join(tmp, "input.xlsx")
    with open(local_path, "wb") as f:
        f.write(xlsx_bytes)

    wb = load_workbook(local_path)
    ws = wb["Sheet1"]
    # ... edit ...
    wb.save(local_path)

    with open(local_path, "rb") as f:
        write_file_bytes("sessions/.../output.xlsx", f.read())
```

### Rule 2: 二级定位

XLSX 需要 **工作表 + 行号** 二级定位：
- 第一级：`sheet_name`（工作表名）
- 第二级：`row_start_int` / `row_end_int`（行范围）

`unified_search` 返回的 `structured_info` 包含：
```json
{
    "source_type": "xlsx",
    "sheet_name": "Sheet1",
    "row_start_int": 10,
    "row_end_int": 50
}
```

### Rule 3: 编辑后必须 snapshot_and_index

每次 `execute_code` 产出新 XLSX 后，必须立即调用 `snapshot_and_index`：

```python
workspace_ops(
    action="snapshot_and_index",
    params='{"parent_ws_doc_id": "ws_xxx", "output_path": "sessions/.../output.xlsx", "source_type": "xlsx"}'
)
```
<!-- AGENT_CONTEXT_END -->

---

## 完整工作流

```python
# Step 1: 复制到 workspace
result = unified_search(action="copy_kb_document", doc_ids="xlsx_doc_id")
workspace_path = result["storage_ref"]["path"]
ws_doc_id = result["storage_ref"]["ws_doc_id"]

# Step 2: 检索定位
search_result = unified_search(action="search", query="产品价格", doc_ids=ws_doc_id)
sheet_name = search_result["results"][0]["structured_info"]["sheet_name"]
row_range = [
    search_result["results"][0]["structured_info"]["row_start_int"],
    search_result["results"][0]["structured_info"]["row_end_int"]
]

# Step 3: 向用户确认
print(f"将修改工作表 '{sheet_name}' 的第 {row_range[0]}-{row_range[1]} 行")

# Step 4: 执行编辑
execute_code(f"""
from openpyxl import load_workbook
wb = load_workbook("{workspace_path}")
ws = wb["{sheet_name}"]
for row_idx in range({row_range[0]}, {row_range[1]} + 1):
    for col_idx in range(1, ws.max_column + 1):
        cell = ws.cell(row_idx, col_idx)
        if cell.value == "旧价格":
            cell.value = "新价格"
wb.save("{workspace_path}")
print(f"已更新 {workspace_path}")
""")

# Step 5: snapshot_and_index（必须）
workspace_ops(
    action="snapshot_and_index",
    params='{{"parent_ws_doc_id": "{ws_doc_id}", "output_path": "{workspace_path}", "source_type": "xlsx"}}'
)
```

---

## 常见操作

### 创建新 Excel 文件

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

wb = Workbook()
ws = wb.active
ws.title = "报告"

# 表头
headers = ["序号", "项目", "状态", "备注"]
header_font = Font(bold=True, size=11, color="FFFFFF")
header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

for col, header in enumerate(headers, 1):
    cell = ws.cell(row=1, column=col, value=header)
    cell.font = header_font
    cell.fill = header_fill
    cell.alignment = Alignment(horizontal="center")

# 数据
data = [
    [1, "功能A", "完成", ""],
    [2, "功能B", "进行中", "预计下周"],
]
for row_idx, row_data in enumerate(data, 2):
    for col_idx, value in enumerate(row_data, 1):
        ws.cell(row=row_idx, column=col_idx, value=value)

# 列宽
ws.column_dimensions["A"].width = 8
ws.column_dimensions["B"].width = 20
ws.column_dimensions["C"].width = 12
ws.column_dimensions["D"].width = 25

wb.save("report.xlsx")
```

### 修改单元格值

```python
from openpyxl import load_workbook

wb = load_workbook("{workspace_path}")
ws = wb["{sheet_name}"]

# 直接引用
ws["C5"] = "新值"

# 批量修改
for row in ws.iter_rows(min_row=10, max_row=50):
    for cell in row:
        if cell.value and "旧关键词" in str(cell.value):
            cell.value = str(cell.value).replace("旧关键词", "新关键词")

wb.save("{workspace_path}")
```

### 插入新行

```python
from openpyxl import load_workbook

wb = load_workbook("{workspace_path}")
ws = wb["{sheet_name}"]

ws.insert_rows(11, 3)  # 在第 10 行后插入 3 行

wb.save("{workspace_path}")
```

**注意**：插入行后，后续行的 `row_start_int` / `row_end_int` 会自动偏移。

### 删除行

```python
from openpyxl import load_workbook

wb = load_workbook("{workspace_path}")
ws = wb["{sheet_name}"]

ws.delete_rows(10, 6)  # 从第 10 行开始删除 6 行

wb.save("{workspace_path}")
```

### 格式化单元格

```python
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

wb = load_workbook("{workspace_path}")
ws = wb["{sheet_name}"]

cell = ws["B5"]
cell.font = Font(bold=True, size=12, color="FF0000")
cell.fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
cell.border = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin")
)

wb.save("{workspace_path}")
```

### 插入单张图片

```python
from ragbase_tools import read_file_bytes
from openpyxl import load_workbook
from openpyxl.drawing.image import Image
from io import BytesIO

wb = load_workbook("{workspace_path}")
ws = wb["{sheet_name}"]

img_bytes = read_file_bytes("{image_path}")
img = Image(BytesIO(img_bytes))
img.width = 300
img.height = 200
ws.add_image(img, "B5")

wb.save("{workspace_path}")
print("已插入图片到 B5")
```

### 从知识库批量提取图片嵌入 Excel

知识库文档（PDF/DOCX/图片）解析后，图片存储在 chunks 的 `img_id` 字段中，格式为 `{kb_id}-{chunk_id}`。
沙箱的 `read_file_bytes()` **直接支持** KB image ID 格式：传入 `"{kb_id}-{chunk_id}"` 即可读取图片字节。

**Step 1：Agent 侧 — 收集 img_id 列表**

通过 `unified_search` 检索含图片的 chunks：

```python
# Agent 调用（不是 execute_code 内部）
result = unified_search(action="list_chunks", doc_ids="doc_id_1,doc_id_2")
# 每个 chunk 的 img_id 格式: "{kb_id}-{chunk_id}"
# 收集所有非空 img_id
```

**Step 2：execute_code — 生成 Excel 框架（文字数据）**

第一次 execute_code：只创建表结构和填充文字数据。

```python
execute_code("""
from ragbase_tools import write_file_bytes
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

wb = Workbook()
# ... 创建 sheets、填充表头和文字数据 ...
ws.column_dimensions["D"].width = 40  # 图片列预留宽度
ws.column_dimensions["E"].width = 40

import tempfile, os
tmp = tempfile.mkdtemp()
local_path = os.path.join(tmp, "output.xlsx")
wb.save(local_path)
with open(local_path, "rb") as f:
    write_file_bytes("sessions/{sid}/outputs/report.xlsx", f.read())
""")
```

**Step 3：execute_code — 批量插入图片**

第二次 execute_code：读取已生成的 Excel，用 `read_file_bytes(img_id)` 直接从 KB 读图片并嵌入。

```python
execute_code(f"""
from ragbase_tools import read_file_bytes, write_file_bytes
from openpyxl import load_workbook
from openpyxl.drawing.image import Image
from openpyxl.utils import get_column_letter
from io import BytesIO
import tempfile, os

xlsx_bytes = read_file_bytes("{output_xlsx_path}")
tmp = tempfile.mkdtemp()
local_path = os.path.join(tmp, "output.xlsx")
with open(local_path, "wb") as f:
    f.write(xlsx_bytes)
wb = load_workbook(local_path)

# 图片映射表：[(sheet_name, row, col, img_id), ...]
# img_id 格式: "{{kb_id}}-{{chunk_id}}"，read_file_bytes 直接支持
image_map = {image_map_json}

inserted = 0
failed = 0
for sheet_name, row_idx, col_idx, img_id in image_map:
    try:
        ws = wb[sheet_name]
        img_bytes = read_file_bytes(img_id)  # 直接读 KB 图片
        img = Image(BytesIO(img_bytes))
        img.width = 280
        img.height = 180
        cell_ref = f"{{get_column_letter(col_idx)}}{{row_idx}}"
        ws.add_image(img, cell_ref)
        ws.row_dimensions[row_idx].height = 140
        inserted += 1
    except Exception as e:
        print(f"⚠️ 图片插入失败 {{sheet_name}} row={{row_idx}}: {{e}}")
        failed += 1

wb.save(local_path)
with open(local_path, "rb") as f:
    write_file_bytes("{output_xlsx_path}", f.read())
print(f"✅ 图片插入完成：成功 {{inserted}} 张，失败 {{failed}} 张")
""")
```

**完整编排流程**：

```
Step A: unified_search(list_chunks) → 收集 img_id 列表
           ↓
Step B: 构建 image_map = [(sheet, row, col, img_id), ...]
           ↓
Step C: execute_code 第一次 — 生成 Excel 框架（文字数据、表头、格式）
           ↓
Step D: execute_code 第二次 — 批量插入图片（传入 image_map + img_id）
           ↓
Step E: snapshot_and_index（如需 ES 索引）
```

**⚠️ 编排要求**：
- Step C 和 Step D **必须分两次 execute_code**：文字先行，图片后续（图片操作容易失败，分开保证文字数据不丢）
- image_map 中的 img_id **直接传入 execute_code**，沙箱 `read_file_bytes` 会自动路由到 KB 桶

**图片列宽/行高参考**：

| 图片尺寸 | 列宽 | 行高 | 适用场景 |
|----------|------|------|---------|
| 280×180 | 40 | 140 | 缩略图预览 |
| 400×300 | 55 | 230 | 标准展示 |
| 600×400 | 80 | 310 | 大图展示 |

### 合并单元格

```python
from openpyxl import load_workbook

wb = load_workbook("{workspace_path}")
ws = wb["{sheet_name}"]

ws.merge_cells("A1:D1")  # 合并 A1 到 D1
ws["A1"] = "合并后的标题"

wb.save("{workspace_path}")
```

### 使用 pandas 读写

```python
import pandas as pd

# 读取
df = pd.read_excel("{workspace_path}", sheet_name="{sheet_name}")

# 处理
df["新列"] = df["列A"].apply(lambda x: x * 2)

# 写回（保留其他 sheet）
from openpyxl import load_workbook
wb = load_workbook("{workspace_path}")
with pd.ExcelWriter("{workspace_path}", engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
    writer.book = wb
    df.to_excel(writer, sheet_name="{sheet_name}", index=False)
```

### 条件格式

```python
from openpyxl import load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import PatternFill

wb = load_workbook("{workspace_path}")
ws = wb["{sheet_name}"]

red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")

ws.conditional_formatting.add("C2:C100",
    CellIsRule(operator="equal", formula=['"失败"'], fill=red_fill))
ws.conditional_formatting.add("C2:C100",
    CellIsRule(operator="equal", formula=['"通过"'], fill=green_fill))

wb.save("{workspace_path}")
```

---

## XLSX 数据模型

### 二级定位
- 第一级：`sheet_name`（工作表名）
- 第二级：`row_start_int` / `row_end_int`（行范围）

### 按 Sheet 隔离
增量更新时按 sheet 隔离，只偏移同一 sheet 内的后续 chunks：
- 修改 Sheet1 的行不会影响 Sheet2 的行号
- 每个 sheet 的 chunks 独立管理

### 固定分块
XLSX 按 `chunk_rows=256` 固定切分，一个 chunk 对应 256 行：
- Chunk 1: rows 1-256
- Chunk 2: rows 257-512
- Chunk 3: rows 513-768

### 跨 Chunk 编辑
**场景**：编辑 rows [250, 300]（跨越 Chunk A [1,256] 和 Chunk B [257,512]）

**处理**：
1. 查询同一 sheet 内所有与 [250, 300] 重叠的 chunks
2. 计算实际边界：actual_start=1, actual_end=512
3. 删除 chunk A + chunk B
4. 重新解析 rows [1, 512+delta]
5. 只偏移同一 sheet 内后续 chunks 的 row_range

---

## 注意事项

1. **行号从 1 开始**：Excel 和 openpyxl 都是 1-based
2. **openpyxl 已预装**：沙箱镜像已包含 openpyxl、Pillow、pandas，无需 `pip install`
3. **格式保留**：openpyxl 能保留单元格格式、公式、样式
4. **原始 KB 不变**：编辑只影响 workspace chunks，原始 KB chunks 永不修改
5. **大文件优化**：超过 10000 行时使用 `read_only=True` 模式读取，`write_only=True` 模式写入
6. **公式保留**：`load_workbook(path, data_only=False)` 保留公式；`data_only=True` 只保留计算值
