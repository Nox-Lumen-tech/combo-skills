---
name: cppcheck
description: C/C++ Bug 检测，内存泄漏/空指针/数组越界/未定义行为，无需编译
execution_mode: sandbox
metadata:
  language: [c, cpp]
  upstream:
    repo: https://github.com/danmar/cppcheck
    stars: 6600
    since: 2007
    license: GPL-3.0
    latest: "2.20.0 (2026-03)"
    rules: 700+ checks
    commits_12mo: 846
    contributors: 380
    user_rating: "4.7/5 (OpenHub)"
    install: "apt install cppcheck"
    advantage: 不需要编译, 直接分析源码
    integrations: [CLion, Eclipse, Jenkins, MegaLinter, reviewdog]
  rating:
    community: 4/5       # 6.6K stars, 17 年历史, C/C++ 社区广泛使用
    rules_richness: 4/5  # 700+ checks, 含 MISRA C/C++ 规则
    speed: 4/5           # 无需编译, 比 clang-tidy 快
    accuracy: 3.5/5      # 某些场景误报率高于 clang-tidy
    integration: 4/5     # XML 输出, reviewdog 原生支持
    overall: "3.9/5 ⭐⭐⭐⭐"
---

CLI: `cppcheck --enable=all --xml --suppress=missingIncludeSystem src/ 2>report.xml`
优势: 不需要编译，直接分析源码，适合快速扫描

**现有库**: `apt install cppcheck`（[danmar/cppcheck](https://github.com/danmar/cppcheck)，6K stars）。XML 输出，violations-command-line `PARSER=CPPCHECK` 可转 SARIF。reviewdog 有 `reviewdog/action-cppcheck` 直接桥接。MegaLinter 已内置。
