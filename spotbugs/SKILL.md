---
name: spotbugs
description: Java 字节码级 Bug 检测 + FindSecBugs 安全扫描，检测空指针/资源泄漏/并发/OWASP
execution_mode: sandbox
metadata:
  language: java
  plugins: [findsecbugs]
  upstream:
    repo: https://github.com/spotbugs/spotbugs
    stars: 3850
    findsecbugs_repo: https://github.com/find-sec-bugs/find-sec-bugs
    findsecbugs_stars: 2400
    since: 2016 (FindBugs 传承自 2003)
    license: LGPL-2.1
    latest: "4.9.8 (2025-10)"
    rules: "400+ core + 150+ security (FindSecBugs)"
    maven_downloads: "~600K/月"
    contributors: 200 + 70 (FindSecBugs)
    notable_users: [Netflix, Atlassian, GitLab, Liferay]
    integrations: [Maven, Gradle, IntelliJ, Eclipse, SonarQube, MegaLinter]
  rating:
    community: 3.5/5     # 3.9K + 2.4K stars, 企业级广泛采用
    rules_richness: 5/5  # 550+ 规则, 字节码级检测独一无二
    speed: 3/5           # 需先编译, 大项目分钟级
    accuracy: 4.5/5      # 字节码分析精度高
    integration: 4/5     # Maven/Gradle 好, reviewdog 支持
    overall: "4.0/5 ⭐⭐⭐⭐"
---

| 检查范围 | 对应需求原文 | SpotBugs 类别 |
|---------|------------|--------------|
| 空指针风险 | "空指针风险" | `NP_NULL_ON_SOME_PATH`, `NP_DEREFERENCE_OF_READLINE_VALUE` |
| 资源未释放 | "资源未释放" | `OS_OPEN_STREAM`, `ODR_OPEN_DATABASE_RESOURCE` |
| 并发问题 | 逻辑漏洞 | `IS2_INCONSISTENT_SYNC`, `DC_DOUBLECHECK` |
| SQL 注入 | "SQL注入" | FindSecBugs: `SQL_INJECTION`, `SQL_INJECTION_JDBC` |
| XSS | "XSS攻击" | FindSecBugs: `XSS_REQUEST_WRAPPER`, `XSS_SERVLET` |
| 硬编码密钥 | "敏感信息泄露" | FindSecBugs: `HARD_CODE_PASSWORD`, `HARD_CODE_KEY` |

CLI: `spotbugs -textui -xml:withMessages -pluginList findsecbugs.jar -effort:max build/classes/`
前提: **需先编译**（`mvn compile` / `gradle build`）
桥接: violations-command-line `PARSER=FINDBUGS` → SARIF → reviewdog
Maven: `com.github.spotbugs:spotbugs-maven-plugin` + FindSecBugs [find-sec-bugs/find-sec-bugs](https://github.com/find-sec-bugs/find-sec-bugs)
