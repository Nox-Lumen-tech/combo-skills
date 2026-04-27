---
name: ruff
description: Python 极速 lint（替代 Flake8/Pylint/isort/Black），900+ 规则，Rust 编写
execution_mode: sandbox
metadata:
  language: python
  upstream:
    repo: https://github.com/astral-sh/ruff
    stars: 46800
    since: 2022
    license: MIT
    latest: "0.15.9 (2026-04)"
    rules: 900+（移植自 Flake8 全插件生态 + Pylint + isort + Black + pyupgrade）
    pypi_downloads: "183M/月（3.2M/天）"
    contributors: 460
    backed_by: Astral（uv/ty 公司）
    used_by: "137K+ GitHub 仓库"
    release_cadence: 周更
    integrations: [pip, uvx, pre-commit, VSCode, IntelliJ, MegaLinter, reviewdog]
  rating:
    community: 5/5       # 46.8K stars, 1.83 亿/月下载, Python 生态现象级
    rules_richness: 5/5  # 900+ 规则, 一个工具替代全家桶
    speed: 5/5           # Rust 编写, 50K 行 ~0.15s, 比 Flake8 快 100x
    accuracy: 4/5        # 从成熟工具移植规则, 已被大规模验证
    integration: 5/5     # JSON/SARIF 原生, 全平台
    overall: "4.8/5 ⭐⭐⭐⭐⭐"
---

| 检查范围 | 对应需求 | Ruff 规则前缀 |
|---------|---------|-------------|
| 语法/风格 | "代码规范" | `E`(pycodestyle) + `W`(warnings) + `F`(pyflakes) |
| 命名规范 | "命名规范" | `N`(pep8-naming) |
| Bug 检测 | "逻辑漏洞" | `B`(flake8-bugbear) |
| import 管理 | "代码冗余" | `I`(isort) |
| 安全初筛 | "安全风险" | `S`(flake8-bandit) |
| 现代化 | 代码质量 | `UP`(pyupgrade) + `SIM`(flake8-simplify) |

CLI: `ruff check --output-format json src/`
速度: 50K 行 Python 代码 ~0.15s（比 Flake8 快 100x）

**现有库**: `pip install ruff`（[astral-sh/ruff](https://github.com/astral-sh/ruff)，v0.15.x，15K+ stars）。原生 JSON/SARIF 输出。或用 [PyGuard](https://github.com/cboyd0319/PyGuard)（`pip install pyguard`）一体化替代 Ruff+Bandit+Pylint+Black，739 规则，含 SARIF 输出。
