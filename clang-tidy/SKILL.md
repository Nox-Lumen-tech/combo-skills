---
name: clang-tidy
description: C/C++ 静态分析，覆盖 bugprone/performance/modernize/cert/security 检查
execution_mode: sandbox
metadata:
  language: [c, cpp]
  upstream:
    repo: https://github.com/llvm/llvm-project (clang-tools-extra/clang-tidy)
    stars: 37700 (LLVM 整体)
    since: 2013
    license: Apache-2.0 with LLVM Exception
    latest: LLVM 18.x
    rules: 400+ checks（18 个检查组：bugprone/cert/performance/modernize/cppcoreguidelines/...）
    install: "apt install clang-tidy"
    integrations: [CMake, Bear, MegaLinter, reviewdog]
  rating:
    community: 5/5       # LLVM 37.7K stars, C++ 社区核心基础设施
    rules_richness: 5/5  # 400+ checks, 18 组, 含 Clang Static Analyzer
    speed: 2/5           # 需 compile_commands.json, 大项目慢
    accuracy: 5/5        # 编译器级精度, 极低误报
    integration: 3/5     # 需要构建系统配合
    overall: "4.0/5 ⭐⭐⭐⭐"
---

| 检查范围 | 对应需求 | clang-tidy 检查组 |
|---------|---------|-----------------|
| Bug 检测 | "逻辑漏洞" | `bugprone-*`（悬垂指针、使用后移动、未初始化） |
| 性能 | "性能问题" | `performance-*`（不必要拷贝、低效容器操作） |
| 安全 | "安全风险" | `cert-*` + `clang-analyzer-security.*` |
| 现代化 | 代码质量 | `modernize-*`（auto、范围 for、nullptr） |
| C++ 核心规范 | "代码规范" | `cppcoreguidelines-*` |
| 空指针/越界 | "空指针风险、数组越界" | `clang-analyzer-core.NullDereference` + `clang-analyzer-core.VLASize` |

CLI: `clang-tidy src/*.cpp --checks='bugprone-*,performance-*,cert-*,modernize-*' --export-fixes=fixes.yaml`
前提: 需要 `compile_commands.json`（CMake 生成或 Bear 工具生成）

**现有库**: LLVM 自带，`apt install clang-tidy`。输出为 YAML fixes 文件，可用 `clang-apply-replacements` 自动修复。reviewdog 有 `reviewdog/action-clang-tidy` 直接桥接到 PR 评论。MegaLinter 已内置。
