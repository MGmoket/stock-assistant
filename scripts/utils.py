"""
公共工具函数 — A股交易助手
提供股票代码处理、过滤、缓存、格式化输出等通用功能。
"""

import os
import json
import time
import hashlib
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


# ─── 网络兼容性补丁 ──────────────────────────────────────────────────────────────
# 修复本地代理（如 Clash、Surge 等）导致的 SSL 证书验证错误。
# 当流量经过本地代理时，自签名证书可能导致 SSL 验证失败。

def _patch_network():
    """应用网络兼容性补丁。"""
    # 禁用 SSL 验证警告
    warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    # 猴子补丁 requests.Session: 禁用 SSL 验证
    try:
        import requests
        _original_init = requests.Session.__init__

        def _patched_init(self, *args, **kwargs):
            _original_init(self, *args, **kwargs)
            self.verify = False

        requests.Session.__init__ = _patched_init
    except Exception:
        pass


# 在导入时自动应用补丁
_patch_network()

# ─── 路径 ───────────────────────────────────────────────────────────────────────

SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SKILL_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"


def ensure_dirs():
    """确保数据目录存在。"""
    DATA_DIR.mkdir(exist_ok=True)
    CACHE_DIR.mkdir(exist_ok=True)


# ─── Sina 实时行情接口 ───────────────────────────────────────────────────────────

SINA_QUOTE_URL = "https://hq.sinajs.cn/list="
SINA_HEADERS = {"Referer": "https://finance.sina.com.cn"}


def _sina_symbol(code: str) -> str:
    """将 6 位代码转换为 Sina 格式（sh600519 / sz000858）。"""
    code = normalize_symbol(code)
    if code.startswith(("6", "9")):
        return f"sh{code}"
    else:
        return f"sz{code}"


def sina_realtime_quote(symbols: list) -> pd.DataFrame:
    """
    通过 Sina 接口获取实时行情（稳定可靠，不依赖东方财富 push2）。
    支持批量查询，symbols 为 6 位代码列表。自动分批（每批 80 只）。
    """
    import requests
    import time

    if not symbols:
        return pd.DataFrame()

    batch_size = 80
    all_rows = []

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        sina_codes = [_sina_symbol(s) for s in batch]
        url = SINA_QUOTE_URL + ",".join(sina_codes)
        try:
            r = requests.get(url, headers=SINA_HEADERS, timeout=10)
            r.encoding = "gbk"
        except Exception:
            continue

        for line in r.text.strip().split("\n"):
            if "=" not in line or '""' in line:
                continue
            var_part, data_part = line.split("=", 1)
            sina_code = var_part.split("_")[-1]
            code = sina_code[2:]  # 去掉 sh/sz 前缀
            data = data_part.strip('";\\n').split(",")
            if len(data) < 32:
                continue
            all_rows.append({
                "代码": code,
                "名称": data[0],
                "今开": float(data[1]) if data[1] else 0,
                "昨收": float(data[2]) if data[2] else 0,
                "最新价": float(data[3]) if data[3] else 0,
                "最高": float(data[4]) if data[4] else 0,
                "最低": float(data[5]) if data[5] else 0,
                "成交量": int(float(data[8])) if data[8] else 0,  # 股
                "成交额": float(data[9]) if data[9] else 0,
                "日期": data[30],
                "时间": data[31],
            })

        # 批间短暂延迟，避免限流
        if i + batch_size < len(symbols):
            time.sleep(0.1)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    # 计算涨跌幅
    df["涨跌额"] = df["最新价"] - df["昨收"]
    df["涨跌幅"] = df.apply(
        lambda r: round((r["最新价"] - r["昨收"]) / r["昨收"] * 100, 2) if r["昨收"] > 0 else 0,
        axis=1,
    )
    df["换手率"] = 0.0  # Sina 接口不提供，后续可从其他接口补充
    return df


def sina_batch_realtime(code_list: list, batch_size: int = 50) -> pd.DataFrame:
    """分批查询大量股票的实时行情。"""
    all_dfs = []
    for i in range(0, len(code_list), batch_size):
        batch = code_list[i:i + batch_size]
        df = sina_realtime_quote(batch)
        if not df.empty:
            all_dfs.append(df)
        time.sleep(0.3)

    if not all_dfs:
        return pd.DataFrame()
    return pd.concat(all_dfs, ignore_index=True)


# ─── 全市场股票列表 ──────────────────────────────────────────────────────────────

def get_all_stock_codes() -> list:
    """获取全部 A 股代码列表（从 AkShare Sina 接口获取）。"""
    cached = get_cache("all_stock_codes", ttl_minutes=60)
    if cached:
        return cached

    try:
        import akshare as ak
        df = ak.stock_zh_a_spot()  # Sina 接口
        codes = df["代码"].tolist()
    except Exception:
        try:
            import akshare as ak
            # 备用：从 Sina 日线数据获取
            df = ak.stock_info_a_code_name()
            codes = df["code"].tolist()
        except Exception:
            codes = []

    if codes:
        set_cache("all_stock_codes", codes)
    return codes


# ─── 股票代码工具 ────────────────────────────────────────────────────────────────

def normalize_symbol(symbol: str) -> str:
    """
    标准化股票代码为 6 位数字字符串。
    支持输入: '600519', 'sh600519', 'SH600519', '600519.SH'
    """
    symbol = symbol.strip().upper()
    # 去掉前缀
    for prefix in ("SH", "SZ", "BJ"):
        if symbol.startswith(prefix):
            symbol = symbol[len(prefix):]
    # 去掉后缀
    for suffix in (".SH", ".SZ", ".BJ"):
        if symbol.endswith(suffix):
            symbol = symbol[: -len(suffix)]
    return symbol.zfill(6)


def get_market(symbol: str) -> str:
    """根据代码判断所属市场。"""
    code = normalize_symbol(symbol)
    if code.startswith(("600", "601", "603", "605")):
        return "上海主板"
    elif code.startswith(("000", "001")):
        return "深圳主板"
    elif code.startswith("300"):
        return "创业板"
    elif code.startswith("688"):
        return "科创板"
    elif code.startswith(("8",)):
        return "北交所"
    else:
        return "未知"


def is_main_board(symbol: str) -> bool:
    """判断是否为主板股票（沪市主板 + 深市主板）。"""
    market = get_market(symbol)
    return market in ("上海主板", "深圳主板")


def is_st(name: str) -> bool:
    """判断是否为 ST 股票（通过股票名称）。"""
    if not name:
        return False
    name = name.upper()
    return "ST" in name or "*ST" in name


def filter_stocks(df: pd.DataFrame, main_board_only: bool = True,
                  exclude_st: bool = True, name_col: str = "名称",
                  code_col: str = "代码") -> pd.DataFrame:
    """
    过滤股票 DataFrame：
    - 排除 ST 股
    - 仅保留主板股票
    """
    result = df.copy()
    if exclude_st and name_col in result.columns:
        result = result[~result[name_col].apply(is_st)]
    if main_board_only and code_col in result.columns:
        result = result[result[code_col].apply(is_main_board)]
    return result.reset_index(drop=True)


# ─── 缓存 ───────────────────────────────────────────────────────────────────────

def _cache_key(func_name: str, **kwargs) -> str:
    """生成缓存 key。"""
    raw = f"{func_name}:{json.dumps(kwargs, sort_keys=True)}"
    return hashlib.md5(raw.encode()).hexdigest()


def get_cache(func_name: str, ttl_minutes: int = 5, **kwargs):
    """
    获取缓存数据。
    ttl_minutes: 缓存有效期（分钟）
    返回 None 表示缓存不存在或已过期。
    """
    ensure_dirs()
    key = _cache_key(func_name, **kwargs)
    cache_file = CACHE_DIR / f"{key}.json"
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cached = json.load(f)
        ts = cached.get("timestamp", 0)
        if time.time() - ts > ttl_minutes * 60:
            return None
        return cached.get("data")
    except (json.JSONDecodeError, KeyError):
        return None


def set_cache(func_name: str, data, **kwargs):
    """写入缓存。"""
    ensure_dirs()
    key = _cache_key(func_name, **kwargs)
    cache_file = CACHE_DIR / f"{key}.json"
    payload = {"timestamp": time.time(), "data": data}
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def clear_cache():
    """清除所有缓存。"""
    if CACHE_DIR.exists():
        for f in CACHE_DIR.glob("*.json"):
            f.unlink()


# ─── 格式化输出 ──────────────────────────────────────────────────────────────────

def format_number(value, decimals: int = 2, unit: str = "") -> str:
    """格式化数字，支持带单位（万/亿）。"""
    if pd.isna(value):
        return "N/A"
    try:
        value = float(value)
    except (ValueError, TypeError):
        return str(value)

    if abs(value) >= 1e8:
        return f"{value / 1e8:,.{decimals}f}亿{unit}"
    elif abs(value) >= 1e4:
        return f"{value / 1e4:,.{decimals}f}万{unit}"
    else:
        return f"{value:,.{decimals}f}{unit}"


def format_percent(value, decimals: int = 2) -> str:
    """格式化百分比。"""
    if pd.isna(value):
        return "N/A"
    try:
        return f"{float(value):+.{decimals}f}%"
    except (ValueError, TypeError):
        return str(value)


def format_price(value) -> str:
    """格式化价格。"""
    if pd.isna(value):
        return "N/A"
    try:
        return f"¥{float(value):,.2f}"
    except (ValueError, TypeError):
        return str(value)


def print_header(title: str):
    """打印格式化标题。"""
    width = 50
    print(f"\n{'━' * width}")
    print(f"  📊 {title}")
    print(f"{'━' * width}")


def print_section(title: str):
    """打印小节标题。"""
    print(f"\n  ▸ {title}")
    print(f"  {'─' * 40}")


def print_kv(key: str, value: str, indent: int = 4):
    """打印键值对。"""
    print(f"{' ' * indent}{key}: {value}")


def print_table(df: pd.DataFrame, max_rows: int = 20):
    """打印 DataFrame 为格式化表格。"""
    if df.empty:
        print("    (无数据)")
        return
    display_df = df.head(max_rows)
    print(display_df.to_string(index=False))
    if len(df) > max_rows:
        print(f"    ... 共 {len(df)} 条，仅显示前 {max_rows} 条")


def today_str() -> str:
    """返回今天日期字符串 YYYYMMDD。"""
    return datetime.now().strftime("%Y%m%d")


def is_trading_time() -> bool:
    """粗略判断当前是否在交易时段（工作日 9:15-15:00）。"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    from datetime import time as dtime
    return dtime(9, 15) <= t <= dtime(15, 0)
