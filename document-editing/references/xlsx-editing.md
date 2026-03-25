# XLSX 编辑详细流程

## Step 1: 复制文档到 workspace

1. 调用 `copy_kb_document(doc_id)`
2. 返回 `ws_doc_id` 和 `workspace_path`
3. 已在 workspace → 跳过

## Step 2: 检索定位

`unified_search` 返回的 `structured_info` 包含：
- `source_type`: "xlsx"
- `sheet_name`: 工作表名（二级定位的第一级）
- `row_start_int` / `row_end_int`: 行范围
- `workspace_path`: workspace 中的文件路径

## Step 4: 编辑

### 使用 execute_code + openpyxl 编辑

XLSX 不使用 skill，统一通过 `execute_code` + openpyxl 进行编辑。

**定位**：根据 `sheet_name` 和 `row_range` 定位单元格范围。

```python
from openpyxl import load_workbook

# 加载工作簿
wb = load_workbook("{workspace_path}")

# 选择工作表（根据 sheet_name）
ws = wb["{sheet_name}"]

# 定位行范围（row_start_int 到 row_end_int，行号从 1 开始）
for row_idx in range({row_start_int}, {row_end_int} + 1):
    for col_idx, range(1, ws.max_column + 1):
        cell = ws.cell(row_idx, col_idx)
        if cell.value == "旧值":
            cell.value = "新值"

# 保存
wb.save("{workspace_path}")
print(f"已更新 {workspace_path}")
```

### 完整工作流
```python
# Step 1: 复制到 workspace
result = unified_search(action="copy_kb_document", doc_ids="xlsx123")
workspace_path = result["storage_ref"]["path"]
ws_doc_id = result["storage_ref"]["ws_doc_id"]

# Step 2: 检索定位
search_result = unified_search(
    action="search",
    query="产品价格",
    doc_ids=ws_doc_id
)
sheet_name = search_result["results"][0]["structured_info"]["sheet_name"]
row_range = [
    search_result["results"][0]["structured_info"]["row_start_int"],
    search_result["results"][0]["structured_info"]["row_end_int"]
]

# Step 3: 向用户确认
print(f"将修改工作表 '{sheet_name}' 的第 {row_range[0]}-{row_range[1]} 行")
print(search_result["results"][0]["content"])

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

# Step 5: 文件已自动注册为产出物（无需手动调用 register_artifact）
```

## XLSX 独特设计
### 二级定位
XLSX 需要**工作表 + 行号**二级定位：
- 第一级：`sheet_name`（工作表名）
- 第二级：`row_start_int` / `row_end_int`（行范围）

```python
# XLSX chunk 的位置信息
{
    "source_type": "xlsx",
    "sheet_name": "Sheet1",
    "row_start_int": 10,
    "row_end_int": 50
}
```

### 按 Sheet 隔离
增量更新时按 sheet 隔离，只偏移同一 sheet 内的后续 chunks：
- 修改 Sheet1 的行不会影响 Sheet2 的行号
- 每个 sheet 的 chunks 独立管理

### 固定分块
XLSX 按 `chunk_rows=256` 固定切分，一个 chunk 对应 256 行：
- Chunk 1: rows 1-256
- Chunk 2: rows 257-512
- Chunk 3: rows 513-768
- ...

## 常见操作

### 修改单元格值
```python
execute_code(f"""
from openpyxl import load_workbook

wb = load_workbook("{workspace_path}")
ws = wb["{sheet_name}"]

# 修改特定单元格
ws["C5"] = "新值"  # 直接用 Excel 风格的单元格引用

# 批量修改
for row in ws.iter_rows(min_row=10, max_row=50):
    for cell in row:
        if cell.value and "旧关键词" in str(cell.value):
            cell.value = str(cell.value).replace("旧关键词", "新关键词")

wb.save("{workspace_path}")
""")
```

### 插入新行
```python
execute_code(f"""
from openpyxl import load_workbook

wb = load_workbook("{workspace_path}")
ws = wb["{sheet_name}"]

# 在第 10 行后插入 3 行
ws.insert_rows(11, 3)

wb.save("{workspace_path}")
print(f"已插入 3 行")
""")
```
**注意**：插入行后，后续行的 `row_start_int` / `row_end_int` 会自动偏移。

### 删除行
```python
execute_code(f"""
from openpyxl import load_workbook

wb = load_workbook("{workspace_path}")
ws = wb["{sheet_name}"]

# 删除第 10-15 行
ws.delete_rows(10, 15)

wb.save("{workspace_path}")
print(f"已删除第 10-15 行")
""")
```
**注意**：删除行后，后续行的 `row_start_int` / `row_end_int` 会自动偏移。

### 格式化单元格
```python
execute_code(f"""
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill

wb = load_workbook("{workspace_path}")
ws = wb["{sheet_name}"]

# 设置字体
cell = ws["B5"]
cell.font = Font(bold=True, size=12)

# 设置背景色
cell.fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")

wb.save("{workspace_path}")
""")
```

### 插入图片
```python
execute_code(f"""
from ragbase_tools import read_file_bytes, ensure_installed
from openpyxl import load_workbook
from io import BytesIO

ensure_installed("Pillow>=10.0.0", "PIL")
from openpyxl.drawing.image import Image

wb = load_workbook("{workspace_path}")
ws = wb["{sheet_name}"]

img_bytes = read_file_bytes("{image_path}")
img = Image(BytesIO(img_bytes))
img.width = 300
img.height = 200
ws.add_image(img, "B5")

wb.save("{workspace_path}")
print("已插入图片到 B5")
""")
```
**注意**：`ensure_installed` 保证 Pillow 可用（openpyxl 图片功能依赖 Pillow）。容器内首次调用会 pip install，后续复用缓存。

## 注意事项
1. **行号基准**：Excel 行号从 1 开始，openpyxl 也是 1-based
2. **二级定位**：必须先指定 `sheet_name`，再指定 `row_range`
3. **按 sheet 隔离**：修改只影响同一 sheet 内的后续 chunks
4. **固定分块**：每个 chunk 对应 256 行（可配置）
5. **openpyxl 依赖**：系统已安装 openpyxl，可直接使用
6. **格式保留**：openpyxl 能保留单元格格式、公式、样式
7. **原始 KB 不变**：编辑只影响 workspace chunks，原始 KB chunks 永不修改

## 跨 Chunk 编辑处理
XLSX 支持跨 chunk 编辑的自动扩展边界：

**场景**：编辑 rows [250, 300]
- Chunk A: rows [1, 256] ← 部分重叠
- Chunk B: rows [257, 512] ← 部分重叠

**处理**：
1. 查询同一 sheet 内所有与 [250, 300] 重叠的 chunks
2. 计算实际边界：actual_start=1, actual_end=512
3. 删除 chunk A + chunk B
4. 重新解析 rows [1, 512+delta]
5. 只偏移同一 sheet 内后续 chunks 的 row_range

**结果**：未编辑的 rows [1, 249] 和 [301, 512] 内容不会丢失。
