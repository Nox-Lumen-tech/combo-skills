---
name: detekt
description: Kotlin 静态分析，代码异味 + 复杂度 + 规范检查，内含 ktlint 规则集
execution_mode: sandbox
metadata:
  language: kotlin
  upstream:
    repo: https://github.com/detekt/detekt
    stars: 6900
    since: 2016
    license: Apache-2.0
    latest: "2.0.0-alpha.2 (2026-01)"
    rules: 200+（含 ktlint wrapper）
    contributors: 300
    commits_12mo: 759
    release_cadence: 月更
    integrations: [Gradle, IntelliJ, SonarQube, MegaLinter, reviewdog]
  rating:
    community: 4/5       # 6.9K stars, Kotlin 社区唯一首选
    rules_richness: 4/5  # 200+ 规则 + ktlint 覆盖风格
    speed: 5/5           # 源码级, 快速
    accuracy: 4/5        # 成熟规则集
    integration: 4/5     # Gradle 优先, SARIF 原生
    overall: "4.2/5 ⭐⭐⭐⭐"
---

| 检查范围 | Detekt 规则集 |
|---------|-------------|
| 命名规范 | `naming` (ClassNaming, FunctionNaming, VariableNaming) |
| 代码复杂度 | `complexity` (TooManyFunctions, LongMethod, CyclomaticComplexMethod) |
| 代码异味 | `style` (MagicNumber, ReturnCount, ForbiddenComment) |
| 潜在 Bug | `potential-bugs` (EqualsAlwaysReturnsTrueOrFalse, UnreachableCode) |
| 性能 | `performance` (SpreadOperator, ForEachOnRange) |
| 格式（ktlint） | `detekt-rules-ktlint-wrapper` 插件 |

CLI: `java -jar detekt-cli.jar -c {config_from_standards_converter} -i src/ --report sarif:detekt.sarif`
特点: Detekt 内置 ktlint wrapper，一个工具覆盖 Kotlin 规范 + 代码质量

**现有库**: [detekt/detekt](https://github.com/detekt/detekt)（v2.0.0-alpha.2），Gradle plugin `dev.detekt`。添加 `detekt-rules-ktlint-wrapper` 插件即包含 ktlint 规则。原生 SARIF 输出，reviewdog 可直接消费。MegaLinter 已内置。
