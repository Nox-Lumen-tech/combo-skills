---
name: pmd
description: >
  Java 源码反模式检测。识别冗余代码、未使用变量、空 catch、复杂度过高等问题，
  含 CPD 拷贝粘贴检测（跨文件重复代码）。支持 Java/Kotlin。
  规则配置可由 standards-converter Skill 从知识库编码手册自动生成，
  或使用内置 quickstart 规则集。
  触发："检查 Java 反模式"、"跑 PMD"、"检测重复代码"、
  "Java 冗余/复杂度/空 catch 检查"。
license: BSD-4-Clause
metadata:
  author: ragbase-team
  version: "1.0.0"
  source: Nox-Lumen-tech/combo-skills/pmd
  tags: [java, kotlin, lint, anti-pattern, cpd, duplicate, static-analysis]
  language: [java, kotlin]
  upstream:
    repo: https://github.com/pmd/pmd
    stars: 5400
    since: 2002
    license: BSD-4-Clause
    latest: "7.12.0"
    rules: 400+（覆盖 17 种语言）
    downloads: Maven #6 Code Analyzers
    contributors: 200+
    release_cadence: 月更
    extra: 含 CPD（Copy-Paste Detector）跨文件重复检测
    integrations: [Maven, Gradle, IntelliJ, Eclipse, SonarQube, MegaLinter, reviewdog]
  rating:
    community: 4/5
    rules_richness: 5/5
    speed: 5/5
    accuracy: 4/5
    integration: 5/5
    overall: "4.6/5"
execution_mode: sandbox
---

## PMD — Java 源码反模式检测

### 工具位置

宿主机预装，Volume 挂载进入 sandbox。自动发现：

```bash
PMD_HOME="${PMD_HOME:-$(find /home -maxdepth 3 -name 'pmd-bin-*' -type d -print -quit 2>/dev/null)}"
PMD_BIN="$PMD_HOME/bin/pmd"
```

> 如果 find 没找到，可尝试 `ls /home/*/review-tools/pmd*/bin/pmd`。

### 一、反模式检测（pmd check）

#### 执行命令

用 `execute_code` 在 sandbox 中运行：

```bash
PMD_HOME="$(find /home -maxdepth 3 -name 'pmd-bin-*' -type d -print -quit 2>/dev/null)"
"$PMD_HOME/bin/pmd" check \
  -d {target_java_files_or_dir} \
  -R rulesets/java/quickstart.xml \
  -f json \
  --no-cache
```

参数说明：
- `-d {dir}`: 要扫描的 Java 源码文件或目录
- `-R {ruleset}`: 规则集。默认 `rulesets/java/quickstart.xml`（PMD 推荐入门），可用自定义规则集
- `-f json`: 输出 JSON 格式（PMD 7.x 原生支持）
- `--no-cache`: 禁用缓存（sandbox 无状态环境）

退出码：0 = 无违规，4 = 有违规（正常，不是错误）。

#### 输出格式（JSON）

```json
{
  "formatVersion": 0,
  "pmdVersion": "7.12.0",
  "timestamp": "2026-04-07T...",
  "files": [
    {
      "filename": "/workspace/.../BadCode.java",
      "violations": [
        {
          "beginline": 5,
          "begincolumn": 17,
          "endline": 5,
          "endcolumn": 28,
          "description": "Avoid unused private fields such as 'unusedField'.",
          "rule": "UnusedPrivateField",
          "ruleset": "Best Practices",
          "priority": 3,
          "externalInfoUrl": "https://docs.pmd-code.org/..."
        }
      ]
    }
  ]
}
```

#### Priority → Severity 映射

| PMD priority | 统一 severity | 含义 |
|:---:|---|---|
| 1 | 致命 | 必须修复（安全、严重 bug） |
| 2 | 致命 | 必须修复 |
| 3 | 一般 | 建议修复（反模式、冗余） |
| 4 | 一般 | 建议修复 |
| 5 | 提示 | 可选修复（风格建议） |

#### 解析输出

从 JSON 中提取每个 Finding：

```
files[] → 每个 file:
  filename → 去掉 /workspace/.../code/ 前缀 → file
  violations[] → 每个 violation:
    rule_id = rule
    ruleset = ruleset
    severity = priority 按上表映射
    file = （来自外层 filename）
    line = beginline
    column = begincolumn
    message = description
    info_url = externalInfoUrl
```

### 二、重复代码检测（pmd cpd）

#### 执行命令

```bash
pmd cpd \
  -d /workspace/sessions/{session_id}/code/src/main/java \
  -l java \
  --minimum-tokens 100 \
  -f xml
```

参数说明：
- `-d {dir}`: 要检测的源码目录
- `-l {lang}`: 语言（java/kotlin/ecmascript/python/scala 等）
- `--minimum-tokens {n}`: 最小重复 token 数（越小检出越多，推荐 50-200）
- `-f xml`: 输出格式（CPD 只支持 text/csv/xml，**不支持 json**）

退出码：0 = 无重复，4 = 有重复。

#### 输出格式（XML）

```xml
<pmd-cpd xmlns="https://pmd-code.org/schema/cpd-report" pmdVersion="7.12.0">
  <duplication lines="9" tokens="43">
    <file line="2" endline="10" column="24"
          path="/workspace/.../Dup1.java"/>
    <file line="2" endline="10" column="24"
          path="/workspace/.../Dup2.java"/>
    <codefragment><![CDATA[
        int x = 1;
        int y = 2;
        ...
    ]]></codefragment>
  </duplication>
</pmd-cpd>
```

#### 解析输出

从 XML 中提取每个重复块：

```
duplication → 每个:
  lines = @lines（重复行数）
  tokens = @tokens（重复 token 数）
  locations = file[] → 每个:
    file = @path（去前缀）
    line = @line
    end_line = @endline
  fragment = codefragment 文本（截取前 500 字符）
```

### 检查范围（对应需求原文）

| 维度 | 需求原文 | PMD 规则集 |
|------|---------|-----------|
| 代码冗余 | "代码冗余" | `bestpractices.xml` (UnusedPrivateField, UnusedLocalVariable) |
| 循环问题 | "循环冗余" | `performance.xml` (AvoidInstantiatingObjectsInLoops) |
| 空 catch | "逻辑漏洞" | `errorprone.xml` (EmptyCatchBlock, AvoidCatchingThrowable) |
| 复杂度 | 代码质量 | `design.xml` (CyclomaticComplexity, GodClass, ExcessiveMethodLength) |
| 拷贝粘贴 | 代码质量 | CPD（跨文件重复代码检测） |

### 常用规则集

| 规则集 | 用途 |
|--------|------|
| `rulesets/java/quickstart.xml` | 入门推荐（覆盖主要反模式） |
| `category/java/bestpractices.xml` | 最佳实践 |
| `category/java/errorprone.xml` | 易错代码 |
| `category/java/performance.xml` | 性能问题 |
| `category/java/design.xml` | 设计缺陷 |
| `category/java/codestyle.xml` | 代码风格 |

多规则集组合：`-R category/java/bestpractices.xml,category/java/errorprone.xml`

### 配置来源

1. **默认**: `rulesets/java/quickstart.xml`（PMD 推荐入门规则集）
2. **自动生成**: standards-converter Skill 从 KB 编码手册生成 `pmd-ruleset.xml`
3. **手动上传**: 用户上传到 session workspace 的自定义规则集
