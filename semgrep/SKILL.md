---
name: semgrep
description: 跨语言 SAST 扫描，SQL 注入/XSS/密钥泄露/taint tracking，支持自定义 YAML 规则
execution_mode: sandbox
metadata:
  language: [java, kotlin, python, c, cpp, javascript, go, ruby, "30+"]
  upstream:
    repo: https://github.com/semgrep/semgrep
    stars: 14700
    rules_repo: https://github.com/semgrep/semgrep-rules (1,100 stars)
    since: 2020
    license: LGPL-2.1
    latest: "v1.157.0 (2026-03)"
    rules: "2,800+ 社区 / 20,000+ Pro / 600+ 高置信安全规则"
    languages: 30+
    enterprise_usage: "1M+ 周扫描, 100M+ 行/天"
    notable_users: [Dropbox, Figma, Snowflake, HashiCorp, GitLab]
    mcp_server: "semgrep mcp（官方 MCP Server, AI 助手可直接调用扫描）"
    scan_speed: "中位 10 秒 CI 扫描"
    contributors: 200
    integrations: [GitHub Actions, GitLab CI, Jenkins, VSCode, IntelliJ, MegaLinter, reviewdog]
  rating:
    community: 5/5       # 14.7K stars, 企业级广泛采用, 背后有商业公司
    rules_richness: 5/5  # 2800+ 社区规则 + 自定义 YAML + taint tracking
    speed: 5/5           # 10-30s 完成扫描
    accuracy: 4.5/5      # Pro 引擎跨文件 dataflow, 72-75% 漏洞检出率
    integration: 5/5     # 官方 MCP Server, JSON/SARIF, 全 CI 平台
    overall: "4.9/5 ⭐⭐⭐⭐⭐"
---

| 检查范围 | 对应需求 | Semgrep 规则集 |
|---------|---------|--------------|
| SQL 注入 | "SQL注入" | `p/java` + `p/python` 内置规则 |
| XSS | "XSS攻击" | `p/xss` |
| 敏感信息泄露 | "敏感信息泄露" | `p/secrets` |
| 权限控制 | "权限控制不当" | `p/owasp-top-ten` |
| 公司自定义规则 | 公司特定检查 | `standards-converter` 从 KB 生成的 `.yaml` 规则 |

CLI: `semgrep scan --config=auto --config=p/java --config={custom_rules_from_standards_converter}/ --json src/`
特点: 支持编写公司自定义规则（YAML），可检测业务特有的安全模式

**现有库**: `pip install semgrep`（[semgrep/semgrep](https://github.com/semgrep/semgrep)，15K stars）。原生 JSON/SARIF 输出。**重要：Semgrep 已有官方 MCP Server**（`semgrep mcp`），可让 AI 助手直接调扫描，代码在 `cli/src/semgrep/mcp/semgrep.py`。Docker 运行：`docker run --rm -v "${PWD}:/src" semgrep/semgrep semgrep scan --config=auto --json`。2800+ 社区规则 + 自定义 YAML 规则。
