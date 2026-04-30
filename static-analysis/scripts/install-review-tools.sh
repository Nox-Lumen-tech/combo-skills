#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# 代码审核工具一键安装脚本
# 用法: bash scripts/install-review-tools.sh [--phase 1|2|3|all]
# ============================================================

TOOLS_DIR="${TOOLS_DIR:-$HOME/.review-tools}"
PHASE="${1:---phase}"
PHASE_NUM="${2:-1}"

if [[ "$PHASE" == "--phase" ]]; then
    true
elif [[ "$PHASE" == "--all" ]]; then
    PHASE_NUM="all"
else
    PHASE_NUM="$PHASE"
fi

mkdir -p "$TOOLS_DIR/bin" "$TOOLS_DIR/lib"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[SKIP]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }

check_cmd() { command -v "$1" &>/dev/null; }

# ----------------------------------------------------------
# Phase 1: Java 核心 + 跨语言安全 + Python
# ----------------------------------------------------------
install_phase1() {
    echo ""
    echo "========== Phase 1: Java 核心 + 跨语言安全 + Python =========="

    # --- Java JRE 检查 ---
    if check_cmd java; then
        JAVA_VER=$(java -version 2>&1 | head -1)
        ok "Java: $JAVA_VER"
    else
        warn "Java 未安装，跳过 Java 工具链（checkstyle/pmd/spotbugs）"
        warn "安装: sudo apt install openjdk-17-jre-headless"
    fi

    # --- Checkstyle (Java 编码规范) ---
    if [[ -f "$TOOLS_DIR/lib/checkstyle.jar" ]]; then
        ok "Checkstyle 已存在: $TOOLS_DIR/lib/checkstyle.jar"
    elif check_cmd java; then
        echo "安装 Checkstyle 10.21.4 ..."
        curl -fsSL -o "$TOOLS_DIR/lib/checkstyle.jar" \
            "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-10.21.4/checkstyle-10.21.4-all.jar"
        cat > "$TOOLS_DIR/bin/checkstyle" <<'WRAPPER'
#!/usr/bin/env bash
exec java -jar "$HOME/.review-tools/lib/checkstyle.jar" "$@"
WRAPPER
        chmod +x "$TOOLS_DIR/bin/checkstyle"
        ok "Checkstyle 10.21.4 → $TOOLS_DIR/lib/checkstyle.jar"
    fi

    # --- PMD (Java 反模式检测) ---
    if [[ -d "$TOOLS_DIR/lib/pmd" ]]; then
        ok "PMD 已存在: $TOOLS_DIR/lib/pmd/"
    elif check_cmd java; then
        echo "安装 PMD 7.12.0 ..."
        curl -fsSL -o /tmp/pmd.zip \
            "https://github.com/pmd/pmd/releases/download/pmd_releases%2F7.12.0/pmd-dist-7.12.0-bin.zip"
        unzip -qo /tmp/pmd.zip -d "$TOOLS_DIR/lib/"
        mv "$TOOLS_DIR/lib/pmd-bin-7.12.0" "$TOOLS_DIR/lib/pmd"
        ln -sf "$TOOLS_DIR/lib/pmd/bin/pmd" "$TOOLS_DIR/bin/pmd"
        rm -f /tmp/pmd.zip
        ok "PMD 7.12.0 → $TOOLS_DIR/lib/pmd/"
    fi

    # --- SpotBugs + FindSecBugs (Java 字节码分析) ---
    if [[ -f "$TOOLS_DIR/lib/spotbugs.jar" ]]; then
        ok "SpotBugs 已存在: $TOOLS_DIR/lib/spotbugs.jar"
    elif check_cmd java; then
        echo "安装 SpotBugs 4.9.3 + FindSecBugs 1.13.0 ..."
        curl -fsSL -o "$TOOLS_DIR/lib/spotbugs.jar" \
            "https://repo.maven.apache.org/maven2/com/github/spotbugs/spotbugs/4.9.3/spotbugs-4.9.3.jar"
        curl -fsSL -o "$TOOLS_DIR/lib/findsecbugs.jar" \
            "https://repo.maven.apache.org/maven2/com/h3xstream/findsecbugs/findsecbugs-plugin/1.13.0/findsecbugs-plugin-1.13.0.jar"
        cat > "$TOOLS_DIR/bin/spotbugs" <<'WRAPPER'
#!/usr/bin/env bash
exec java -jar "$HOME/.review-tools/lib/spotbugs.jar" "$@"
WRAPPER
        chmod +x "$TOOLS_DIR/bin/spotbugs"
        ok "SpotBugs 4.9.3 + FindSecBugs 1.13.0"
    fi

    # --- Semgrep (跨语言安全扫描, 2800+ 规则) ---
    if check_cmd semgrep; then
        ok "Semgrep: $(semgrep --version 2>/dev/null || echo 'installed')"
    else
        echo "安装 Semgrep ..."
        pip install --quiet semgrep && ok "Semgrep $(semgrep --version 2>/dev/null)" || fail "Semgrep 安装失败"
    fi

    # --- Ruff (Python lint, 900+ 规则, Rust 编写极快) ---
    if check_cmd ruff; then
        ok "Ruff: $(ruff version 2>/dev/null)"
    else
        echo "安装 Ruff ..."
        pip install --quiet ruff && ok "Ruff $(ruff version 2>/dev/null)" || fail "Ruff 安装失败"
    fi

    # --- Bandit (Python 安全扫描) ---
    if check_cmd bandit; then
        ok "Bandit: $(bandit --version 2>/dev/null | head -1)"
    else
        echo "安装 Bandit ..."
        pip install --quiet bandit && ok "Bandit installed" || fail "Bandit 安装失败"
    fi

    # --- reviewdog (lint → 仓库 inline comment 桥接) ---
    if check_cmd reviewdog; then
        ok "reviewdog: $(reviewdog -version 2>/dev/null || echo 'installed')"
    else
        echo "安装 reviewdog ..."
        if check_cmd go; then
            go install github.com/reviewdog/reviewdog/cmd/reviewdog@latest \
                && ln -sf "$HOME/go/bin/reviewdog" "$TOOLS_DIR/bin/reviewdog" \
                && ok "reviewdog (go install → $TOOLS_DIR/bin/)"
        else
            curl -sfL https://raw.githubusercontent.com/reviewdog/reviewdog/master/install.sh | sh -s -- -b "$TOOLS_DIR/bin" && ok "reviewdog → $TOOLS_DIR/bin/"
        fi
    fi

    # --- ripgrep (极快文本搜索) ---
    if check_cmd rg; then
        ok "ripgrep: $(rg --version | head -1)"
    else
        echo "安装 ripgrep ..."
        sudo apt-get install -y -qq ripgrep 2>/dev/null && ok "ripgrep" || warn "ripgrep 安装失败，手动: sudo apt install ripgrep"
    fi

    # --- ast-grep (AST 代码结构搜索) ---
    if check_cmd sg || check_cmd ast-grep; then
        ok "ast-grep: installed"
    else
        echo "安装 ast-grep ..."
        if check_cmd npm; then
            npm install -g @ast-grep/cli 2>/dev/null && ok "ast-grep (npm)" || warn "ast-grep npm 安装失败"
        elif check_cmd cargo; then
            cargo install ast-grep 2>/dev/null && ok "ast-grep (cargo)" || warn "ast-grep cargo 安装失败"
        else
            warn "ast-grep 需要 npm 或 cargo，跳过"
        fi
    fi
}

# ----------------------------------------------------------
# Phase 2: Kotlin + Python 类型 + 仓库集成
# ----------------------------------------------------------
install_phase2() {
    echo ""
    echo "========== Phase 2: Kotlin + Python 类型 + 仓库集成 =========="

    # --- Detekt (Kotlin 静态分析, 含 ktlint) ---
    if [[ -f "$TOOLS_DIR/lib/detekt-cli.jar" ]]; then
        ok "Detekt 已存在: $TOOLS_DIR/lib/detekt-cli.jar"
    elif check_cmd java; then
        echo "安装 Detekt 1.23.7 ..."
        curl -fsSL -o "$TOOLS_DIR/lib/detekt-cli.jar" \
            "https://github.com/detekt/detekt/releases/download/v1.23.7/detekt-cli-1.23.7-all.jar"
        cat > "$TOOLS_DIR/bin/detekt" <<'WRAPPER'
#!/usr/bin/env bash
exec java -jar "$HOME/.review-tools/lib/detekt-cli.jar" "$@"
WRAPPER
        chmod +x "$TOOLS_DIR/bin/detekt"
        ok "Detekt 1.23.7 → $TOOLS_DIR/lib/detekt-cli.jar"
    fi

    # --- Mypy (Python 类型检查) ---
    if check_cmd mypy; then
        ok "Mypy: $(mypy --version 2>/dev/null)"
    else
        echo "安装 Mypy ..."
        pip install --quiet mypy && ok "Mypy installed" || fail "Mypy 安装失败"
    fi

    # --- python-gerrit-api (Gerrit REST API) ---
    pip install --quiet python-gerrit-api 2>/dev/null && ok "python-gerrit-api" || warn "python-gerrit-api 安装失败"

    # --- python-gitlab (GitLab REST API) ---
    pip install --quiet python-gitlab 2>/dev/null && ok "python-gitlab" || warn "python-gitlab 安装失败"

    # --- httpx (Gitee V5 API 调用) ---
    pip install --quiet httpx 2>/dev/null && ok "httpx" || warn "httpx 安装失败"
}

# ----------------------------------------------------------
# Phase 3: C/C++
# ----------------------------------------------------------
install_phase3() {
    echo ""
    echo "========== Phase 3: C/C++ =========="

    # --- cppcheck (C/C++ Bug 检测, 无需编译) ---
    if check_cmd cppcheck; then
        ok "cppcheck: $(cppcheck --version 2>/dev/null)"
    else
        echo "安装 cppcheck ..."
        sudo apt-get install -y -qq cppcheck 2>/dev/null && ok "cppcheck" || warn "cppcheck: sudo apt install cppcheck"
    fi

    # --- clang-tidy (C/C++ 深度分析) ---
    if check_cmd clang-tidy; then
        ok "clang-tidy: $(clang-tidy --version 2>/dev/null | head -1)"
    else
        echo "安装 clang-tidy ..."
        sudo apt-get install -y -qq clang-tidy 2>/dev/null && ok "clang-tidy" || warn "clang-tidy: sudo apt install clang-tidy"
    fi
}

# ----------------------------------------------------------
# 安装后验证
# ----------------------------------------------------------
verify() {
    echo ""
    echo "========== 安装验证 =========="
    local total=0 passed=0

    for tool in checkstyle pmd spotbugs semgrep ruff bandit reviewdog rg; do
        total=$((total + 1))
        if check_cmd "$tool" || [[ -x "$TOOLS_DIR/bin/$tool" ]]; then
            ok "$tool"
            passed=$((passed + 1))
        else
            fail "$tool 未安装"
        fi
    done

    echo ""
    echo "验证结果: $passed/$total 工具可用"

    if [[ ! ":$PATH:" == *":$TOOLS_DIR/bin:"* ]]; then
        echo ""
        echo -e "${YELLOW}[提示]${NC} 请将工具目录加入 PATH:"
        echo "  export PATH=\"$TOOLS_DIR/bin:\$PATH\""
        echo "  echo 'export PATH=\"$TOOLS_DIR/bin:\$PATH\"' >> ~/.bashrc"
    fi
}

# ----------------------------------------------------------
# 主入口
# ----------------------------------------------------------
echo "================================================"
echo "  代码审核工具一键安装"
echo "  安装目录: $TOOLS_DIR"
echo "  Phase: $PHASE_NUM"
echo "================================================"

case "$PHASE_NUM" in
    1)     install_phase1 ;;
    2)     install_phase1; install_phase2 ;;
    3)     install_phase1; install_phase2; install_phase3 ;;
    all)   install_phase1; install_phase2; install_phase3 ;;
    *)     echo "用法: $0 [--phase 1|2|3|all]"; exit 1 ;;
esac

verify
