# PPTX 编辑详细流程

## Step 1: 复制文档到 workspace

1. 调用 `copy_kb_document(doc_id)`
2. 返回 `ws_doc_id` 和 `workspace_path`
3. 已在 workspace → 跳过

## Step 2: 检索定位

`unified_search` 返回的 `structured_info` 包含：
- `source_type`: "pptx"
- `slide_num`: 幻灯片编号
- `workspace_path`: workspace 中的文件路径

## Step 4: 编辑

### 使用 pptx skill / execute_code 编辑
PPTX 支持两种编辑方式，优先使用 skill。

**定位**：根据 `slide_num` 定位幻灯片。

#### 方式 1: pptx skill（推荐）

适合：修改幻灯片内容、样式、布局等常见操作。

```python
# 通过 skill 编辑幻灯片
# skill 会根据 slide_num 定位并编辑
```

#### 方式 2: execute_code + python-pptx

适合：skill 不支持的复杂操作。

```python
from pptx import Presentation

# 加载演示文稿
prs = Presentation("{workspace_path}")

# 定位幻灯片（slide_num 从 1 开始）
slide = prs.slides[{slide_num} - 1]

# 修改标题
for shape in slide.shapes:
    if shape.has_text_frame:
        if "旧标题" in shape.text:
            shape.text = "新标题"

# 保存
prs.save("{workspace_path}")
```

### 完整工作流
```python
# Step 1: 复制到 workspace
result = unified_search(action="copy_kb_document", doc_ids="pptx123")
workspace_path = result["storage_ref"]["path"]

# Step 2: 检索定位
search_result = unified_search(
    action="search",
    query="市场分析",
    doc_ids="pptx_ws_{sid}_pptx123"
)
slide_num = search_result["results"][0]["structured_info"]["slide_num"]

# Step 3: 向用户确认
print(f"将修改第 {slide_num} 张幻灯片")
print(search_result["results"][0]["content"])

# Step 4: 执行编辑（优先用 skill，失败则回退到 execute_code）
# 尝试 pptx skill...

# 如果 skill 不可用或失败，回退到 execute_code
execute_code(f"""
from pptx import Presentation

prs = Presentation("{workspace_path}")
slide = prs.slides[{slide_num} - 1]

for shape in slide.shapes:
    if shape.has_text_frame:
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                if "2025" in run.text:
                    run.text = run.text.replace("2025", "2026")

prs.save("{workspace_path}")
print(f"已更新 {workspace_path}")
""")

# Step 5: 文件已自动注册为产出物（无需手动调用 register_artifact）
```

## PPTX 独特优势

PPTX 是三种二进制格式中最简单的：

| 维度 | PPTX | DOCX | XLSX |
|------|------|------|------|
| **定位单位** | Slide（幻灯片） | 段落 | 行 + 工作表 |
| **分块粒度** | **1 slide = 1 chunk**（天然映射） | 多段落合并 | 多行合并 |
| **是否需要范围** | **否**（单一 `slide_num`） | 是（para_range） | 是（row_range） |
| **跨 chunk 编辑** | **不存在** | 存在 | 存在 |

## 增删幻灯片
### 插入新幻灯片
```python
execute_code(f"""
from pptx import Presentation
from pptx.util import Inches, Pt

prs = Presentation("{workspace_path}")

# 在第 3 张幻灯片后插入（插入位置索引从 0 开始）
slide_layout = prs.slide_layouts[1]  # 使用标题和内容布局
new_slide = prs.slides.add_slide(slide_layout)

# 填充内容
title = new_slide.shapes.title
title.text = "新幻灯片标题"

prs.save("{workspace_path}")
print(f"已插入新幻灯片")
""")
```
**注意**：插入新幻灯片后，后续幻灯片的 `slide_num` 会自动增加，ES chunks 也会相应更新。

### 删除幻灯片
```python
execute_code(f"""
from pptx import Presentation

prs = Presentation("{workspace_path}")

# 删除第 5 张幻灯片（索引从 0 开始）
rId = prs.slides._sldIdLst[4].rId
prs.part.drop_rel(rId)

prs.save("{workspace_path}")
print(f"已删除第 5 张幻灯片")
""")
```
**注意**：删除幻灯片后，后续幻灯片的 `slide_num` 会自动减少，ES chunks 也会相应更新。

## Section（节）功能
PPTX 支持"节"（Section）分组幻灯片：
```python
# 按 section 筛选搜索
search_result = unified_search(
    action="search",
    query="市场分析",
    doc_ids="pptx_ws_{sid}_pptx123"
)
# 返回结果中包含 section_name 字段（如果有节分组）
```

## 注意事项
1. **slide_num 基准**：slide_num 从 1 开始（用户视角），但在 python-pptx 中索引从 0 开始
2. **1:1 映射**：一个 slide 对应一个 chunk，无需处理跨 chunk 编辑
3. **自动更新**：编辑后系统自动更新 ES chunks，偏移后续 slide_num（如果增删幻灯片）
4. **skill 优先**：优先使用 pptx skill，失败则回退到 execute_code
5. **样式保留**：pptx skill 和 python-pptx 都能在 XML 层操作，保留样式
