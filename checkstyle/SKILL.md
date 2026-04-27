---
name: checkstyle
description: >
  Java 编码规范检查。分析 Java 源码的命名规范、注释规范、代码格式、import 管理等。
  规则配置可由 standards-converter Skill 从知识库编码手册自动生成，
  或使用 Google/Sun 内置规范。
  触发："检查 Java 代码规范"、"跑 checkstyle"、"Java 命名/注释/格式检查"。
license: LGPL-2.1
metadata:
  author: ragbase-team
  version: "1.0.0"
  source: Nox-Lumen-tech/combo-skills/checkstyle
  tags: [java, lint, code-standard, checkstyle, static-analysis]
  language: java
  upstream:
    repo: https://github.com/checkstyle/checkstyle
    stars: 8900
    since: 2001
    license: LGPL-2.1
    latest: "10.21.1"
    rules: 200+ checks
    downloads: Maven 顶级（全球 Java 项目标配）
    contributors: 380
    release_cadence: 月更
    integrations: [Maven, Gradle, IntelliJ, Eclipse, SonarQube, MegaLinter, reviewdog]
  rating:
    community: 4/5
    rules_richness: 4/5
    speed: 5/5
    accuracy: 4/5
    integration: 5/5
    overall: "4.4/5"
execution_mode: sandbox
---

## Checkstyle — Java 编码规范检查

### 工具位置

宿主机预装，Volume 挂载进入 sandbox。自动发现路径：

```bash
CHECKSTYLE_JAR="${CHECKSTYLE_JAR:-$(find /home -path '*/review-tools/checkstyle*.jar' -print -quit 2>/dev/null)}"
CHECKS_XML="${CHECKS_XML:-$(dirname "$CHECKSTYLE_JAR")/google_checks.xml}"
```

> 如果 find 没找到，可尝试 `which checkstyle` 或 `ls /home/*/review-tools/checkstyle*.jar`。

### 执行命令

用 `execute_code` 在 sandbox 中运行：

```bash
CHECKSTYLE_JAR="$(find /home -path '*/review-tools/checkstyle*.jar' -print -quit 2>/dev/null)"
CHECKS_XML="$(dirname "$CHECKSTYLE_JAR")/google_checks.xml"
java -jar "$CHECKSTYLE_JAR" \
  -c "$CHECKS_XML" \
  -f sarif \
  {target_java_files_or_dir}
```

参数说明：
- `$CHECKSTYLE_JAR`: JAR 路径，通过 find 自动发现（宿主机 `review-tools/` 挂载进来）
- `-c {config}`: 规则配置文件。可用 standards-converter 生成自定义配置
- `-f sarif`: 输出格式。**必须用 sarif**（Checkstyle 不支持 `-f json`，仅支持 xml/sarif/plain）
- 最后一个参数: 要扫描的 Java 源码文件或目录

退出码：0 = 无违规，非 0 = 有违规（正常，不是错误）。

### 输出格式（SARIF JSON）

```json
{
  "runs": [{
    "results": [{
      "ruleId": "com.puppycrawl.tools.checkstyle.checks.naming.MemberNameCheck",
      "level": "warning",
      "message": { "text": "Member name 'Foo' must match pattern..." },
      "locations": [{
        "physicalLocation": {
          "artifactLocation": { "uri": "/workspace/.../MyClass.java" },
          "region": { "startLine": 15, "startColumn": 5 }
        }
      }]
    }]
  }]
}
```

### Severity 映射

将 SARIF `level` 映射到统一严重级别：

| SARIF level | 统一 severity | 含义 |
|-------------|--------------|------|
| `error` | 致命 | 必须修复 |
| `warning` | 一般 | 建议修复 |
| `note` | 提示 | 可选修复 |

### 解析输出

从 SARIF JSON 中提取每个 Finding：

```
runs[].results[] → 每个 result:
  rule_id = ruleId 最后一段（如 "MemberNameCheck"）
  severity = level 按上表映射
  file = locations[0].physicalLocation.artifactLocation.uri（去掉 /workspace/.../code/ 前缀）
  line = locations[0].physicalLocation.region.startLine
  message = message.text
```

### 检查范围（对应需求原文）

| 维度 | 需求原文 | Checkstyle 模块 |
|------|---------|----------------|
| 命名规范 | "命名规范" | NamingConventions (LocalVariableName, MemberName, MethodName, TypeName) |
| 注释规范 | "注释规范" | Javadoc (JavadocMethod, JavadocType, MissingJavadoc) |
| 代码格式 | "代码格式" | Whitespace + Blocks (WhitespaceAround, LeftCurly, NeedBraces) |
| import 管理 | "代码冗余" | Imports (AvoidStarImport, UnusedImports, RedundantImport) |

### 配置来源

1. **默认**: `/google_checks.xml`（Google Java Style Guide）
2. **自动生成**: standards-converter Skill 从 KB 编码手册生成自定义 XML
3. **手动上传**: 用户上传到 session workspace 的自定义配置
