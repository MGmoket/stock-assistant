#!/bin/bash
# ─────────────────────────────────────────────────────
#  A股短线交易助手 — 一键安装脚本
# ─────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_NAME="stock-assistant"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📦 A股短线交易助手 — 环境安装"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ─── 1. 检查 conda ─────────────────────────────────────
if ! command -v conda &> /dev/null; then
    echo "  ❌ 未检测到 conda，请先安装 Miniconda 或 Anaconda:"
    echo "     https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi
echo "  ✅ conda 已安装"

# ─── 2. 安装系统依赖 (TA-Lib C 库) ───────────────────────
echo ""
echo "  ⏳ 安装系统依赖 (TA-Lib C 库)..."
OS="$(uname -s)"
case "$OS" in
    Darwin)
        if brew list ta-lib &>/dev/null; then
            echo "  ✅ ta-lib 已安装 (Homebrew)"
        else
            if command -v brew &> /dev/null; then
                echo "  📦 通过 Homebrew 安装 ta-lib..."
                brew install ta-lib
            else
                echo "  ⚠️ 未检测到 Homebrew，跳过 ta-lib 安装"
                echo "     请手动安装: brew install ta-lib"
                echo "     如不安装，K线形态识别功能将不可用，其他功能正常"
            fi
        fi
        ;;
    Linux)
        if ldconfig -p 2>/dev/null | grep -q libta_lib; then
            echo "  ✅ ta-lib 已安装"
        else
            echo "  📦 安装 ta-lib (需要 sudo 权限)..."
            if command -v apt-get &> /dev/null; then
                sudo apt-get update -qq && sudo apt-get install -y -qq libta-lib0-dev 2>/dev/null || {
                    echo "  ⚠️ apt 安装失败，尝试从源码编译..."
                    _install_talib_from_source
                }
            elif command -v yum &> /dev/null; then
                sudo yum install -y ta-lib-devel 2>/dev/null || {
                    echo "  ⚠️ yum 安装失败，尝试从源码编译..."
                    _install_talib_from_source
                }
            else
                _install_talib_from_source
            fi
        fi
        ;;
    *)
        echo "  ⚠️ 不支持的操作系统: $OS，跳过 ta-lib 安装"
        ;;
esac

_install_talib_from_source() {
    echo "  📦 从源码编译 ta-lib..."
    local TMP_DIR=$(mktemp -d)
    cd "$TMP_DIR"
    curl -sL https://github.com/ta-lib/ta-lib/releases/download/v0.6.4/ta-lib-0.6.4-src.tar.gz | tar xz
    cd ta-lib-0.6.4
    ./configure --prefix=/usr/local
    make -j$(nproc 2>/dev/null || echo 2)
    sudo make install
    cd "$SCRIPT_DIR"
    rm -rf "$TMP_DIR"
    echo "  ✅ ta-lib 从源码安装完成"
}

# ─── 3. 创建/更新 conda 环境 ─────────────────────────────
echo ""
echo "  ⏳ 创建 conda 环境: $ENV_NAME..."

if conda env list | grep -q "^${ENV_NAME} "; then
    echo "  📦 环境已存在，更新依赖..."
    conda env update -n "$ENV_NAME" -f "$SCRIPT_DIR/environment.yml" --prune -q
else
    echo "  📦 创建新环境..."
    conda env create -f "$SCRIPT_DIR/environment.yml" -q
fi
echo "  ✅ conda 环境就绪"

# ─── 4. 创建数据目录 ──────────────────────────────────────
mkdir -p "$SCRIPT_DIR/data"
echo "  ✅ 数据目录就绪"

# ─── 5. 验证安装 ──────────────────────────────────────────
echo ""
echo "  ⏳ 验证安装..."
PYTHON="$(conda run -n $ENV_NAME which python)"

conda run -n "$ENV_NAME" python -c "
import sys
checks = []

# 核心依赖
for mod in ['pandas', 'numpy', 'akshare']:
    try:
        __import__(mod)
        checks.append(('✅', mod))
    except ImportError:
        checks.append(('❌', mod))

# pytdx
try:
    from pytdx.hq import TdxHq_API
    checks.append(('✅', 'pytdx'))
except ImportError:
    checks.append(('❌', 'pytdx'))

# TA-Lib (可选)
try:
    import talib
    checks.append(('✅', f'TA-Lib v{talib.__version__}'))
except ImportError:
    checks.append(('⚠️', 'TA-Lib (未安装，K线形态不可用)'))

for status, name in checks:
    print(f'  {status} {name}')

failed = [c for c in checks if c[0] == '❌']
if failed:
    print()
    print('  ❌ 有依赖安装失败，请检查上方输出')
    sys.exit(1)
"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🎉 安装完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  使用方法:"
echo "    conda activate $ENV_NAME"
echo "    python3 scripts/trading_strategy.py plan --capital 100000"
echo ""
