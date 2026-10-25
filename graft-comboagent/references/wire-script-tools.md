# 任务：把 skill `{{SKILL_NAME}}` 的脚本接成可复用动态工具

你是云端 combo agent。`{{SKILL_NAME}}` 这个 skill 已装在我的个人技能库里，但它**没有
`skill.manifest.json`**，所以它的脚本现在只能靠"读 SKILL.md + `execute_code` 手动
跑"。请把其中**值得复用**的脚本，注册成 agent 工具池里可直接点名调用的**动态工具**。

全程**只用你已有的工具**（`unified_search` 读 + `write_file` 写 + `execute_code`
自测），不需要任何平台改动。

---

## 步骤

### 1. 读这个 skill
- 读 `skills/users/<我的uid>/{{SKILL_NAME}}/SKILL.md`，弄清它有哪些脚本、各自干嘛、
  怎么调用（路径里的 uid 用你当前会话的用户；不确定就先
  `unified_search(action='grep_file', query='{{SKILL_NAME}}/SKILL.md')` 定位）。
- 列出它 `scripts/`（或根目录）下的 `*.py`，逐个读内容。

### 2. 选要暴露的脚本
只接 **通用、可复用、参数有实际意义** 的脚本。一次性 / 调试 / 仅对特定文件生效的
脚本 **跳过**。拿不准就少接、接最有复用价值的那 1~3 个。

### 3. 每个选中的脚本，写一个**自包含**的 wrapper
平台的动态工具执行约定：调用时会在沙箱里执行 `main(**_PARAMS)`。所以每个工具的
`main.py` 必须满足：

- **自包含**：把原脚本里要复用的逻辑**搬进来**。不要 `import` 原 skill 目录、不要读
  `skills/...` 路径——沙箱访问不到 MinIO 的 skills/ 区。
- 暴露 `main(**params)` 入口，`params` 的键 = 你为它定义的 `parameters_schema`。
- 把结果 `return`（平台会把返回值 print 出来给你看）。
- 原脚本是 argparse / `__main__` 风格的，就把核心逻辑抽成函数，再用 `main` 包一层。

示例（原脚本是 CLI，重构成函数 + main）：

```python
def _core(region: str) -> str:
    # …从原脚本搬过来的、真正干活的逻辑…
    return f"pong from {region}"

def main(**params):
    return _core(region=params.get("region", "us-east-1"))
```

先用 `execute_code` 跑一下确认 wrapper 能正常 `main(...)` 返回，再注册。

### 4. 注册（"方式二"：立即写注册表）
对每个工具，**先读、后合并、再写**，绝不能覆盖已有工具：

1. 读现有注册表：
   `unified_search(action='read_file', query='users/<我的uid>/scripts/registry.json')`
   —— 不存在就当作 `{"version": 1, "tools": {}}`。
2. 写 wrapper 脚本：
   `write_file(path="users/<我的uid>/scripts/<tool_name>/main.py", content=<wrapper代码>, mode="write")`
3. 把这个工具条目并进 registry 的 `tools` 里，再**整体写回**：
   `write_file(path="users/<我的uid>/scripts/registry.json", content=<合并后的完整JSON>, mode="write")`

registry.json 里每个工具条目长这样（注意 `script_path` 带 `workspace/` 前缀）：

```json
"<tool_name>": {
  "tool_name": "<tool_name>",
  "script_path": "workspace/users/<我的uid>/scripts/<tool_name>/main.py",
  "description": "<这个工具干嘛、什么时候该用——写清楚，LLM 靠它选工具>",
  "parameters_schema": {
    "type": "object",
    "properties": { "<参数名>": { "type": "string", "description": "..." } },
    "required": [ "<必填参数名>" ]
  },
  "type": "script",
  "status": "active"
}
```

### 5. 命名与归属
- `tool_name` 一律以 skill 名打头：`{{SKILL_NAME}}_<功能>`（snake_case，全局唯一）。
  平台暂不记录工具属于哪个 skill，用这个前缀来标识归属、便于以后清理。
- 注册前读 registry.json 自查，别和已有工具撞名。

---

## 完成后回报
一句话总结：接了哪几个工具、各自 `tool_name` + 一句话描述。并提醒我：
**这些工具要到【下一个会话】才会被加载进工具池**（当前会话不会自动刷新）。

## 兜底
如果某个脚本不适合接（依赖太重 / 无法自包含 / 参数说不清），就**跳过它**并说明原因。
跳过没关系——这个 skill 本来就能以纯 markdown 方式用（读 SKILL.md + `execute_code`
跑脚本），接工具只是锦上添花。
