#!/bin/bash
# ─────────────────────────────────────────────────────
#  A股短线交易助手 — 一键安装脚本 (venv)
# ─────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📦 A股短线交易助手 — 环境安装"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ─── 1. 检查 Python ────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
        if [ "$major" = "3" ] && [ "$minor" -ge 9 ]; then
            PYTHON="$cmd"
            echo "  ✅ Python $ver ($cmd)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  ❌ 需要 Python 3.9+，请先安装"
    exit 1
fi

# ─── 2. 安装系统依赖 (TA-Lib C 库) ───────────────────────
echo ""
echo "  ⏳ 检查系统依赖 (TA-Lib C 库)..."
TALIB_INSTALLED=false
OS="$(uname -s)"

case "$OS" in
    Darwin)
        if brew list ta-lib &>/dev/null 2>&1; then
            echo "  ✅ ta-lib 已安装"
            TALIB_INSTALLED=true
        elif command -v brew &>/dev/null; then
            echo "  📦 通过 Homebrew 安装 ta-lib..."
            brew install ta-lib && TALIB_INSTALLED=true
        else
            echo "  ⚠️ 未检测到 Homebrew，跳过 ta-lib"
            echo "     K线形态识别功能将不可用，其他功能正常"
        fi
        ;;
    Linux)
        if ldconfig -p 2>/dev/null | grep -q libta_lib; then
            echo "  ✅ ta-lib 已安装"
            TALIB_INSTALLED=true
        elif command -v apt-get &>/dev/null; then
            echo "  📦 通过 apt 安装 ta-lib..."
            sudo apt-get update -qq && sudo apt-get install -y -qq libta-lib-dev && TALIB_INSTALLED=true
        else
            echo "  ⚠️ 跳过 ta-lib，K线形态识别功能将不可用"
        fi
        ;;
esac

# ─── 3. 创建 venv ──────────────────────────────────────
echo ""
if [ -d "$VENV_DIR" ]; then
    echo "  ✅ venv 已存在，更新依赖..."
else
    echo "  ⏳ 创建 venv..."
    "$PYTHON" -m venv "$VENV_DIR"
    echo "  ✅ venv 已创建: .venv/"
fi

# 激活
source "$VENV_DIR/bin/activate"

# ─── 4. 安装 pip 依赖 ──────────────────────────────────
echo "  ⏳ 安装 Python 依赖..."
pip install --upgrade pip -q

if [ "$TALIB_INSTALLED" = true ]; then
    pip install -r "$SCRIPT_DIR/requirements.txt" -q
else
    # 跳过 TA-Lib，装其他的
    grep -v "TA-Lib" "$SCRIPT_DIR/requirements.txt" | pip install -r /dev/stdin -q
    echo "  ⚠️ 跳过 TA-Lib Python 包（系统库未安装）"
fi

# ─── 5. 创建数据目录 ──────────────────────────────────
mkdir -p "$SCRIPT_DIR/data"

# ─── 6. 验证 ──────────────────────────────────────────
echo ""
echo "  ⏳ 验证安装..."
python -c "
checks = []
for mod in ['pandas', 'numpy', 'akshare', 'requests']:
    try:
        __import__(mod)
        checks.append(('✅', mod))
    except ImportError:
        checks.append(('❌', mod))
try:
    from pytdx.hq import TdxHq_API
    checks.append(('✅', 'pytdx'))
except ImportError:
    checks.append(('❌', 'pytdx'))
try:
    import talib
    checks.append(('✅', f'TA-Lib v{talib.__version__}'))
except ImportError:
    checks.append(('⚠️', 'TA-Lib (未安装，K线形态不可用)'))

for s, n in checks:
    print(f'  {s} {n}')
failed = [c for c in checks if c[0] == '❌']
if failed:
    import sys; sys.exit(1)
"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🎉 安装完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  使用方法:"
echo "    source .venv/bin/activate"
echo "    python3 scripts/trading_strategy.py plan --capital 100000"
echo ""
