---
name: bandit
description: Python 安全漏洞扫描，检测 SQL 注入/命令注入/硬编码密钥/不安全函数
execution_mode: sandbox
metadata:
  language: python
  upstream:
    repo: https://github.com/PyCQA/bandit
    stars: 7900
    since: 2015
    license: Apache-2.0
    latest: "1.9.4 (2026-02)"
    rules: 70+ 安全规则
    pypi_downloads: "18.8M/月"
    origin: OpenStack Security Project
    contributors: 150
    integrations: [pip, pre-commit, MegaLinter, reviewdog, SonarQube]
  rating:
    community: 4/5       # 7.9K stars, PyCQA 官方, Python 安全标配
    rules_richness: 3/5  # 70+ 规则, 专注安全（与 Ruff 互补）
    speed: 5/5           # AST 扫描, 极快
    accuracy: 4/5        # 安全规则精度高
    integration: 4/5     # JSON/SARIF/HTML, Docker 镜像
    overall: "4.0/5 ⭐⭐⭐⭐"
---

| 安全分类 | 规则示例 | 对应需求 |
|---------|---------|---------|
| 注入 | `B608` SQL 注入, `B602` subprocess shell=True | "SQL注入" |
| 硬编码 | `B105` 硬编码密码, `B106` 硬编码密码参数 | "敏感信息泄露" |
| 弱加密 | `B303` MD5/SHA1, `B413` 不安全 TLS | "加密安全" |
| 反序列化 | `B301` pickle.loads, `B506` yaml.load | "不安全反序列化" |

CLI: `bandit -r src/ -f json -ll`（只报 medium+ 级别）
SARIF: `bandit -r src/ -f sarif -o bandit.sarif`
Docker: `docker run --rm -v $(pwd):/src ghcr.io/pycqa/bandit bandit -r /src -f json`
