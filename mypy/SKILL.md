---
name: mypy
description: Python 类型检查，检测类型不匹配/缺失注解/不兼容赋值，PEP 484 参考实现
execution_mode: sandbox
metadata:
  language: python
  upstream:
    repo: https://github.com/python/mypy
    stars: 19000
    since: 2012
    license: MIT
    latest: "1.15.x (2026)"
    rules: 50+ 错误码
    pypi_downloads: "50M+/月"
    backed_by: Python 官方（PEP 484 参考实现）
    contributors: 700
    release_cadence: 月更
    integrations: [pip, pre-commit, VSCode, IntelliJ, MegaLinter, reviewdog]
  rating:
    community: 5/5       # 19K stars, Python 官方类型检查器
    rules_richness: 4/5  # 50+ 错误码, 完整类型系统
    speed: 3/5           # 增量模式快, 全量较慢
    accuracy: 5/5        # 类型系统精确
    integration: 4/5     # JSON 输出, 全平台
    overall: "4.2/5 ⭐⭐⭐⭐"
---

| 检查范围 | 检查内容 | 错误码示例 |
|---------|---------|----------|
| 类型不匹配 | 函数参数/返回值类型错误 | `arg-type`, `return-value` |
| 缺失注解 | 未注解的函数定义 | `no-untyped-def` |
| 不兼容赋值 | 变量赋值类型不匹配 | `assignment` |
| 不可达代码 | 类型系统推断出的死代码 | `unreachable` |
| 导入错误 | 缺失类型存根 | `import-untyped` |
| None 安全 | Optional 未检查直接使用 | `union-attr` |

CLI: `mypy src/ --no-color --show-error-codes --show-column-numbers`
JSON: `mypy src/ --output json`（mypy >= 1.10）
严格模式: `mypy src/ --strict --ignore-missing-imports`

**现有库**: `pip install mypy`（[python/mypy](https://github.com/python/mypy)，19K stars）。Python 官方 PEP 484 参考实现。支持 JSON 输出、增量检查、daemon 模式（`dmypy`）。reviewdog 有 `reviewdog/action-mypy` 直接桥接。MegaLinter 已内置。
