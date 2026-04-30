#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# 代码审核编排脚本
# 传入代码路径 → 自动检测语言 → 路由工具 → 输出 CodeEvidence JSON
#
# 用法:
#   bash scripts/code-review.sh [目标路径] [选项]
#
# 目标路径:
#   省略        → git diff HEAD 变更文件
#   文件/目录   → 审核指定文件或目录下所有源码
#   --all       → 审核当前项目全部源码
#
# 选项:
#   --lang java,python   仅审核指定语言
#   --severity severe    最低报告级别 (fatal|severe|general|minor)
#   --output FILE        输出 JSON 到文件 (默认 stdout)
#   --parallel           各语言组并行执行
# ============================================================

TOOLS_DIR="${TOOLS_DIR:-$HOME/.review-tools}"
export PATH="$TOOLS_DIR/bin:$PATH"

# --- .review-configs/ 自动检测 ---
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
CONFIGS_DIR="${REVIEW_CONFIGS_DIR:-$PROJECT_ROOT/.review-configs}"
if [[ -d "$CONFIGS_DIR" ]]; then
    echo "检测到自定义配置: $CONFIGS_DIR" >&2
fi

# --- 参数解析 ---
TARGET=""
LANG_FILTER=""
MIN_SEVERITY="minor"
OUTPUT="/dev/stdout"
PARALLEL=false
TMPDIR_BASE=$(mktemp -d /tmp/code-review.XXXXXX)
trap 'rm -rf "$TMPDIR_BASE"' EXIT

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)      TARGET="__ALL__"; shift ;;
        --lang)     LANG_FILTER="$2"; shift 2 ;;
        --severity) MIN_SEVERITY="$2"; shift 2 ;;
        --output)   OUTPUT="$2"; shift 2 ;;
        --parallel) PARALLEL=true; shift ;;
        -*)         echo "未知选项: $1" >&2; exit 1 ;;
        *)          TARGET="$1"; shift ;;
    esac
done

# --- Step 1: 确定审核文件列表 ---
collect_files() {
    if [[ "$TARGET" == "__ALL__" ]]; then
        # 全量扫描：项目下所有源码
        find . -type f \( \
            -name '*.java' -o -name '*.kt' -o -name '*.py' \
            -o -name '*.c' -o -name '*.cpp' -o -name '*.h' -o -name '*.hpp' \
            -o -name '*.js' -o -name '*.ts' -o -name '*.go' -o -name '*.rb' \
        \) ! -path '*/node_modules/*' ! -path '*/.git/*' ! -path '*/build/*' \
           ! -path '*/target/*' ! -path '*/__pycache__/*' ! -path '*/venv/*'
    elif [[ -n "$TARGET" ]]; then
        if [[ -d "$TARGET" ]]; then
            find "$TARGET" -type f \( \
                -name '*.java' -o -name '*.kt' -o -name '*.py' \
                -o -name '*.c' -o -name '*.cpp' -o -name '*.h' -o -name '*.hpp' \
                -o -name '*.js' -o -name '*.ts' -o -name '*.go' -o -name '*.rb' \
            \) ! -path '*/node_modules/*' ! -path '*/.git/*'
        elif [[ -f "$TARGET" ]]; then
            echo "$TARGET"
        else
            echo "路径不存在: $TARGET" >&2; exit 1
        fi
    else
        # git diff 变更文件
        local diff_files
        diff_files=$(git diff --name-only HEAD 2>/dev/null || true)
        if [[ -z "$diff_files" ]]; then
            diff_files=$(git diff --name-only HEAD~1 2>/dev/null || true)
        fi
        if [[ -z "$diff_files" ]]; then
            echo "无 git 变更且未指定路径。用法: $0 [路径|--all]" >&2
            exit 1
        fi
        echo "$diff_files" | while read -r f; do [[ -f "$f" ]] && echo "$f"; done
    fi
}

ALL_FILES=$(collect_files | sort -u)
if [[ -z "$ALL_FILES" ]]; then
    echo '{"version":"1.0","findings":[],"summary":{"total":0,"pass":true}}' > "$OUTPUT"
    exit 0
fi

# --- Step 2: 按语言分组 ---
JAVA_FILES=""
KOTLIN_FILES=""
PYTHON_FILES=""
CPP_FILES=""
OTHER_FILES=""

while IFS= read -r f; do
    ext="${f##*.}"
    case "$ext" in
        java)           JAVA_FILES+="$f"$'\n' ;;
        kt|kts)         KOTLIN_FILES+="$f"$'\n' ;;
        py)             PYTHON_FILES+="$f"$'\n' ;;
        c|cpp|cc|h|hpp) CPP_FILES+="$f"$'\n' ;;
        *)              OTHER_FILES+="$f"$'\n' ;;
    esac
done <<< "$ALL_FILES"

# 语言过滤
if [[ -n "$LANG_FILTER" ]]; then
    [[ "$LANG_FILTER" != *java* ]]   && JAVA_FILES=""
    [[ "$LANG_FILTER" != *kotlin* ]] && KOTLIN_FILES=""
    [[ "$LANG_FILTER" != *python* ]] && PYTHON_FILES=""
    [[ "$LANG_FILTER" != *cpp* && "$LANG_FILTER" != *"c++"* && "$LANG_FILTER" != *c* ]] && CPP_FILES=""
fi

echo "审核文件统计:" >&2
[[ -n "$JAVA_FILES" ]]   && echo "  Java:   $(echo "$JAVA_FILES" | grep -c .)" >&2
[[ -n "$KOTLIN_FILES" ]] && echo "  Kotlin: $(echo "$KOTLIN_FILES" | grep -c .)" >&2
[[ -n "$PYTHON_FILES" ]] && echo "  Python: $(echo "$PYTHON_FILES" | grep -c .)" >&2
[[ -n "$CPP_FILES" ]]    && echo "  C/C++:  $(echo "$CPP_FILES" | grep -c .)" >&2
[[ -n "$OTHER_FILES" ]]  && echo "  Other:  $(echo "$OTHER_FILES" | grep -c .)" >&2

# --- 工具检测 ---
has() { command -v "$1" &>/dev/null || [[ -x "$TOOLS_DIR/bin/$1" ]]; }

# --- Step 3: 各语言组跑工具，输出到临时文件 ---
FINDINGS_DIR="$TMPDIR_BASE/findings"
mkdir -p "$FINDINGS_DIR"

sev_num() {
    case "$1" in
        fatal)   echo 4 ;; severe)  echo 3 ;;
        general) echo 2 ;; minor)   echo 1 ;; *)       echo 0 ;;
    esac
}
MIN_SEV_NUM=$(sev_num "$MIN_SEVERITY")

# ------ Java 工具链 ------
run_java() {
    [[ -z "$JAVA_FILES" ]] && return 0
    local filelist="$TMPDIR_BASE/java_files.txt"
    echo "$JAVA_FILES" | grep -v '^$' > "$filelist"
    local src_dirs
    src_dirs=$(echo "$JAVA_FILES" | grep -v '^$' | xargs -I{} dirname {} | sort -u | head -5 | tr '\n' ' ')

    # Checkstyle
    if has checkstyle || { has java && [[ -f "$TOOLS_DIR/lib/checkstyle.jar" ]]; }; then
        local cs_config=""
        if [[ -f "$CONFIGS_DIR/checkstyle-rules.xml" ]]; then
            cs_config="-c $CONFIGS_DIR/checkstyle-rules.xml"
            echo "  [Java] Checkstyle (自定义配置) ..." >&2
        else
            echo "  [Java] Checkstyle (默认配置) ..." >&2
        fi
        local cs_out="$TMPDIR_BASE/checkstyle.json"
        java -jar "$TOOLS_DIR/lib/checkstyle.jar" $cs_config -f json \
            $(cat "$filelist" | tr '\n' ' ') \
            > "$cs_out" 2>/dev/null || true
        if [[ -s "$cs_out" ]]; then
            python3 -c "
import json, sys
try:
    data = json.load(open('$cs_out'))
except: sys.exit(0)
for item in (data if isinstance(data, list) else [data]):
    for v in item.get('violations', item.get('errors', [])):
        sev = {'error':'fatal','warning':'general','info':'minor'}.get(v.get('severity','info'),'minor')
        src = v.get('source','').rsplit('.',1)[-1] if v.get('source') else v.get('rule','')
        print(json.dumps({
            'tool':'checkstyle','file':item.get('filename',''),'line':v.get('line',0),
            'severity':sev,'rule_id':src,'title':src,'description':v.get('message','')
        }))
" >> "$FINDINGS_DIR/all.jsonl" 2>/dev/null || true
        fi
    fi

    # PMD
    if has pmd; then
        local pmd_rules="rulesets/java/quickstart.xml"
        if [[ -f "$CONFIGS_DIR/pmd-ruleset.xml" ]]; then
            pmd_rules="$CONFIGS_DIR/pmd-ruleset.xml"
            echo "  [Java] PMD (自定义规则集) ..." >&2
        else
            echo "  [Java] PMD (默认规则集) ..." >&2
        fi
        local pmd_out="$TMPDIR_BASE/pmd.json"
        pmd check -d $src_dirs -R "$pmd_rules" -f json --no-cache \
            > "$pmd_out" 2>/dev/null || true
        if [[ -s "$pmd_out" ]]; then
            python3 -c "
import json, sys
try:
    data = json.load(open('$pmd_out'))
except: sys.exit(0)
for f in data.get('files', []):
    for v in f.get('violations', []):
        p = v.get('priority', 5)
        sev = {1:'fatal',2:'severe',3:'general'}.get(p,'minor')
        print(json.dumps({
            'tool':'pmd','file':f.get('filename',''),'line':v.get('beginLine',0),
            'severity':sev,'rule_id':v.get('rule',''),'title':v.get('rule',''),
            'description':v.get('description','')
        }))
" >> "$FINDINGS_DIR/all.jsonl" 2>/dev/null || true
        fi
    fi

    # SpotBugs (需要编译产物)
    if has spotbugs || [[ -f "$TOOLS_DIR/lib/spotbugs.jar" ]]; then
        local classes_dir=""
        for d in build/classes target/classes out/production; do
            [[ -d "$d" ]] && classes_dir="$d" && break
        done
        if [[ -n "$classes_dir" ]]; then
            local sb_filter=""
            if [[ -f "$CONFIGS_DIR/spotbugs-filter.xml" ]]; then
                sb_filter="-include $CONFIGS_DIR/spotbugs-filter.xml"
                echo "  [Java] SpotBugs (自定义过滤器) ..." >&2
            else
                echo "  [Java] SpotBugs ..." >&2
            fi
            local sb_out="$TMPDIR_BASE/spotbugs.xml"
            java -jar "$TOOLS_DIR/lib/spotbugs.jar" -textui -xml \
                -pluginList "$TOOLS_DIR/lib/findsecbugs.jar" \
                $sb_filter -effort:max "$classes_dir" > "$sb_out" 2>/dev/null || true
            if [[ -s "$sb_out" ]]; then
                python3 -c "
import xml.etree.ElementTree as ET, json, sys
try:
    tree = ET.parse('$sb_out')
except: sys.exit(0)
for bug in tree.findall('.//BugInstance'):
    prio = int(bug.get('priority','3'))
    sev = {1:'fatal',2:'severe'}.get(prio,'general')
    sl = bug.find('.//SourceLine')
    print(json.dumps({
        'tool':'spotbugs','file':sl.get('sourcepath','') if sl is not None else '',
        'line':int(sl.get('start','0')) if sl is not None else 0,
        'severity':sev,'rule_id':bug.get('type',''),
        'title':bug.get('type',''),'description':(bug.findtext('LongMessage') or bug.findtext('ShortMessage') or '')
    }))
" >> "$FINDINGS_DIR/all.jsonl" 2>/dev/null || true
            fi
        else
            echo "  [Java] SpotBugs 跳过（未找到编译产物 build/classes 或 target/classes）" >&2
        fi
    fi

    # Semgrep (Java)
    run_semgrep "java" "$filelist" "p/java"
}

# ------ Kotlin 工具链 ------
run_kotlin() {
    [[ -z "$KOTLIN_FILES" ]] && return 0
    local filelist="$TMPDIR_BASE/kotlin_files.txt"
    echo "$KOTLIN_FILES" | grep -v '^$' > "$filelist"

    # Detekt
    if has detekt || [[ -f "$TOOLS_DIR/lib/detekt-cli.jar" ]]; then
        local det_config=""
        if [[ -f "$CONFIGS_DIR/detekt-config.yml" ]]; then
            det_config="-c $CONFIGS_DIR/detekt-config.yml"
            echo "  [Kotlin] Detekt (自定义配置) ..." >&2
        else
            echo "  [Kotlin] Detekt (默认配置) ..." >&2
        fi
        local det_out="$TMPDIR_BASE/detekt.sarif"
        java -jar "$TOOLS_DIR/lib/detekt-cli.jar" $det_config \
            -i "$(cat "$filelist" | head -1 | xargs dirname)" \
            --report "sarif:$det_out" 2>/dev/null || true
        if [[ -s "$det_out" ]]; then
            python3 -c "
import json, sys
try:
    data = json.load(open('$det_out'))
except: sys.exit(0)
for run in data.get('runs', []):
    for r in run.get('results', []):
        lvl = r.get('level','note')
        sev = {'error':'severe','warning':'general','note':'minor'}.get(lvl,'minor')
        loc = (r.get('locations') or [{}])[0].get('physicalLocation',{})
        print(json.dumps({
            'tool':'detekt','file':loc.get('artifactLocation',{}).get('uri',''),
            'line':loc.get('region',{}).get('startLine',0),
            'severity':sev,'rule_id':r.get('ruleId',''),
            'title':r.get('ruleId',''),'description':(r.get('message',{}).get('text',''))
        }))
" >> "$FINDINGS_DIR/all.jsonl" 2>/dev/null || true
        fi
    fi

    run_semgrep "kotlin" "$filelist" "p/kotlin"
}

# ------ Python 工具链 ------
run_python() {
    [[ -z "$PYTHON_FILES" ]] && return 0
    local filelist="$TMPDIR_BASE/python_files.txt"
    echo "$PYTHON_FILES" | grep -v '^$' > "$filelist"

    # Ruff
    if has ruff; then
        local ruff_config=""
        if [[ -f "$CONFIGS_DIR/ruff.toml" ]]; then
            ruff_config="--config $CONFIGS_DIR/ruff.toml"
            echo "  [Python] Ruff (自定义配置) ..." >&2
        else
            echo "  [Python] Ruff (默认配置) ..." >&2
        fi
        local ruff_out="$TMPDIR_BASE/ruff.json"
        ruff check $ruff_config --output-format json $(cat "$filelist" | tr '\n' ' ') \
            > "$ruff_out" 2>/dev/null || true
        if [[ -s "$ruff_out" ]]; then
            python3 -c "
import json, sys
try:
    data = json.load(open('$ruff_out'))
except: sys.exit(0)
for v in data:
    code = v.get('code','')
    sev = 'general'
    if code.startswith('E') or code.startswith('F'): sev = 'general'
    elif code.startswith('S'): sev = 'severe'
    elif code.startswith('W') or code.startswith('I'): sev = 'minor'
    print(json.dumps({
        'tool':'ruff','file':v.get('filename',''),
        'line':v.get('location',{}).get('row',0),
        'severity':sev,'rule_id':code,
        'title':code,'description':v.get('message','')
    }))
" >> "$FINDINGS_DIR/all.jsonl" 2>/dev/null || true
        fi
    fi

    # Bandit
    if has bandit; then
        echo "  [Python] Bandit ..." >&2
        local ban_out="$TMPDIR_BASE/bandit.json"
        bandit -f json -ll $(cat "$filelist" | tr '\n' ' ') \
            > "$ban_out" 2>/dev/null || true
        if [[ -s "$ban_out" ]]; then
            python3 -c "
import json, sys
try:
    data = json.load(open('$ban_out'))
except: sys.exit(0)
for r in data.get('results', []):
    sev = {'HIGH':'fatal','MEDIUM':'severe','LOW':'general'}.get(r.get('issue_severity','LOW'),'general')
    print(json.dumps({
        'tool':'bandit','file':r.get('filename',''),
        'line':r.get('line_number',0),
        'severity':sev,'rule_id':r.get('test_id',''),
        'title':r.get('test_name',''),'description':r.get('issue_text','')
    }))
" >> "$FINDINGS_DIR/all.jsonl" 2>/dev/null || true
        fi
    fi

    run_semgrep "python" "$filelist" "p/python"
}

# ------ C/C++ 工具链 ------
run_cpp() {
    [[ -z "$CPP_FILES" ]] && return 0
    local filelist="$TMPDIR_BASE/cpp_files.txt"
    echo "$CPP_FILES" | grep -v '^$' > "$filelist"

    # cppcheck
    if has cppcheck; then
        echo "  [C/C++] cppcheck ..." >&2
        local cpp_out="$TMPDIR_BASE/cppcheck.xml"
        cppcheck --enable=warning,style,performance --xml \
            $(cat "$filelist" | tr '\n' ' ') 2>"$cpp_out" || true
        if [[ -s "$cpp_out" ]]; then
            python3 -c "
import xml.etree.ElementTree as ET, json, sys
try:
    tree = ET.parse('$cpp_out')
except: sys.exit(0)
for err in tree.findall('.//error'):
    sev_map = {'error':'fatal','warning':'severe','style':'general','performance':'general','information':'minor'}
    sev = sev_map.get(err.get('severity','information'),'minor')
    loc = err.find('location')
    print(json.dumps({
        'tool':'cppcheck','file':loc.get('file','') if loc is not None else '',
        'line':int(loc.get('line','0')) if loc is not None else 0,
        'severity':sev,'rule_id':err.get('id',''),
        'title':err.get('id',''),'description':err.get('msg','')
    }))
" >> "$FINDINGS_DIR/all.jsonl" 2>/dev/null || true
        fi
    fi

    # clang-tidy
    if has clang-tidy; then
        if [[ -f compile_commands.json ]]; then
            echo "  [C/C++] clang-tidy ..." >&2
            clang-tidy $(cat "$filelist" | tr '\n' ' ') \
                --checks='bugprone-*,performance-*,cert-*' \
                2>/dev/null | python3 -c "
import sys, json, re
for line in sys.stdin:
    m = re.match(r'^(.+):(\d+):\d+: (warning|error|note): (.+) \[(.+)\]$', line)
    if m:
        sev = {'error':'fatal','warning':'severe','note':'general'}.get(m.group(3),'general')
        print(json.dumps({
            'tool':'clang-tidy','file':m.group(1),'line':int(m.group(2)),
            'severity':sev,'rule_id':m.group(5),
            'title':m.group(5),'description':m.group(4)
        }))
" >> "$FINDINGS_DIR/all.jsonl" 2>/dev/null || true
        else
            echo "  [C/C++] clang-tidy 跳过（缺少 compile_commands.json）" >&2
        fi
    fi

    run_semgrep "cpp" "$filelist" "auto"
}

# ------ Semgrep（所有语言共用） ------
run_semgrep() {
    local lang="$1" filelist="$2" config="$3"
    has semgrep || return 0
    local custom_config=""
    if [[ -d "$CONFIGS_DIR/semgrep-custom-rules" ]]; then
        custom_config="--config $CONFIGS_DIR/semgrep-custom-rules/"
        echo "  [$lang] Semgrep (内置 + 自定义规则) ..." >&2
    else
        echo "  [$lang] Semgrep ..." >&2
    fi
    local sg_out="$TMPDIR_BASE/semgrep_${lang}.json"
    semgrep scan --config="$config" $custom_config --json --quiet \
        $(cat "$filelist" | tr '\n' ' ') \
        > "$sg_out" 2>/dev/null || true
    if [[ -s "$sg_out" ]]; then
        python3 -c "
import json, sys
try:
    data = json.load(open('$sg_out'))
except: sys.exit(0)
for r in data.get('results', []):
    sev = {'ERROR':'fatal','WARNING':'severe','INFO':'general'}.get(
        r.get('extra',{}).get('severity','INFO'),'general')
    print(json.dumps({
        'tool':'semgrep','file':r.get('path',''),
        'line':r.get('start',{}).get('line',0),
        'severity':sev,'rule_id':r.get('check_id',''),
        'title':r.get('check_id','').rsplit('.',1)[-1],
        'description':r.get('extra',{}).get('message','')
    }))
" >> "$FINDINGS_DIR/all.jsonl" 2>/dev/null || true
    fi
}

# --- Step 3 执行 ---
if $PARALLEL; then
    run_java &
    run_kotlin &
    run_python &
    run_cpp &
    wait
else
    run_java
    run_kotlin
    run_python
    run_cpp
fi

# Other 文件只跑 semgrep
if [[ -n "$OTHER_FILES" ]] && has semgrep; then
    echo "$OTHER_FILES" | grep -v '^$' > "$TMPDIR_BASE/other_files.txt"
    run_semgrep "other" "$TMPDIR_BASE/other_files.txt" "auto"
fi

# --- Step 4: 合并所有 findings ---
touch "$FINDINGS_DIR/all.jsonl"
# 并行模式下可能有多个工具同时追加，这里做一次排序去空行保证格式
if $PARALLEL; then
    sort -u "$FINDINGS_DIR/all.jsonl" > "$FINDINGS_DIR/all_sorted.jsonl"
    mv "$FINDINGS_DIR/all_sorted.jsonl" "$FINDINGS_DIR/all.jsonl"
fi

REPO_NAME=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
HEAD_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
FILE_COUNT=$(echo "$ALL_FILES" | wc -l)

python3 -c "
import json, sys
from collections import Counter
from datetime import datetime

findings = []
with open('$FINDINGS_DIR/all.jsonl') as f:
    for line in f:
        line = line.strip()
        if line:
            try:
                findings.append(json.loads(line))
            except:
                pass

# 去重（同文件+同行+同rule_id）
seen = set()
deduped = []
for f in findings:
    key = (f.get('file',''), f.get('line',0), f.get('rule_id',''))
    if key not in seen:
        seen.add(key)
        deduped.append(f)

# severity 过滤
sev_rank = {'fatal':4,'severe':3,'general':2,'minor':1}
min_sev = $MIN_SEV_NUM
deduped = [f for f in deduped if sev_rank.get(f.get('severity','minor'),0) >= min_sev]
for i, f in enumerate(deduped):
    f['id'] = f'L1-{i+1:03d}'

sev_count = Counter(f['severity'] for f in deduped)
tool_count = Counter(f['tool'] for f in deduped)

has_fatal = sev_count.get('fatal', 0) > 0
has_severe = sev_count.get('severe', 0) > 0
passed = not has_fatal and not has_severe

gate_reasons = []
if has_fatal: gate_reasons.append(f'{sev_count[\"fatal\"]} 个致命问题')
if has_severe: gate_reasons.append(f'{sev_count[\"severe\"]} 个严重问题')

evidence = {
    'version': '1.0',
    'timestamp': '$TIMESTAMP',
    'repo': {
        'name': '$REPO_NAME',
        'branch': '$BRANCH',
        'head_commit': '$HEAD_COMMIT',
    },
    'scan_summary': {
        'files_scanned': $FILE_COUNT,
        'mode': '$(if [ "$TARGET" = "__ALL__" ]; then echo full; elif [ -n "$TARGET" ]; then echo target; else echo diff; fi)',
        'tools_used': list(tool_count.keys()),
        'custom_configs': $(if [[ -d "$CONFIGS_DIR" ]]; then echo "True"; else echo "False"; fi),
    },
    'findings': sorted(deduped, key=lambda x: {'fatal':0,'severe':1,'general':2,'minor':3}.get(x['severity'],9)),
    'summary': {
        'total': len(deduped),
        'by_severity': dict(sev_count),
        'by_tool': dict(tool_count),
        'pass': passed,
        'gate_reason': '、'.join(gate_reasons) if gate_reasons else None,
    }
}

json.dump(evidence, sys.stdout, ensure_ascii=False, indent=2)
print()
" > "$OUTPUT"

# 终端摘要
echo "" >&2
echo "========== 审核完成 ==========" >&2
if [[ -s "$FINDINGS_DIR/all.jsonl" ]]; then
    TOTAL=$(wc -l < "$FINDINGS_DIR/all.jsonl")
    echo "  发现问题: $TOTAL" >&2
else
    echo "  发现问题: 0" >&2
fi
echo "  输出: $OUTPUT" >&2
