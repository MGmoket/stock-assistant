"""
K 线形态识别模块 — A股交易助手
依赖 TA-Lib，用于识别常见蜡烛图形态。
"""

import argparse

import akshare as ak
import pandas as pd

from utils import (
    normalize_symbol, _sina_symbol,
    print_header, print_section, print_kv,
)


PATTERNS = [
    {"name": "锤子线", "func": "CDLHAMMER", "score": 10, "desc": "看涨反转"},
    {"name": "上吊线", "func": "CDLHANGINGMAN", "score": 8, "desc": "看跌警告"},
    {"name": "吞没", "func": "CDLENGULFING", "score": 8, "desc": "趋势反转"},
    {"name": "十字星", "func": "CDLDOJI", "score": 3, "desc": "犹豫/转折"},
    {"name": "早晨之星", "func": "CDLMORNINGSTAR", "score": 10, "desc": "强看涨"},
    {"name": "黄昏之星", "func": "CDLEVENINGSTAR", "score": 10, "desc": "强看跌"},
    {"name": "三白兵", "func": "CDL3WHITESOLDIERS", "score": 10, "desc": "强势上攻"},
    {"name": "三黑鸦", "func": "CDL3BLACKCROWS", "score": 10, "desc": "连续下跌"},
    {"name": "穿刺线", "func": "CDLPIERCING", "score": 8, "desc": "看涨反转"},
    {"name": "乌云盖顶", "func": "CDLDARKCLOUDCOVER", "score": 8, "desc": "看跌反转"},
    {"name": "孕线", "func": "CDLHARAMI", "score": 4, "desc": "趋势暂停"},
    {"name": "启明星", "func": "CDLMORNINGDOJISTAR", "score": 10, "desc": "强底部信号"},
]


def _load_talib():
    try:
        import talib  # type: ignore
        return talib
    except Exception as e:
        raise ImportError("缺少 TA-Lib，请先安装: pip install TA-Lib") from e


def _get_daily_kline(symbol: str, count: int = 120) -> pd.DataFrame:
    code = normalize_symbol(symbol)
    sina_code = _sina_symbol(code)
    df = ak.stock_zh_a_daily(symbol=sina_code, adjust="qfq")
    if df.empty:
        return df
    col_map = {
        "date": "日期", "open": "开盘", "close": "收盘",
        "high": "最高", "low": "最低",
        "volume": "成交量", "amount": "成交额",
    }
    df = df.rename(columns=col_map)
    return df.tail(count).reset_index(drop=True)


def _get_60min_kline(symbol: str, count: int = 120) -> pd.DataFrame:
    from tdx_data import get_minute_kline
    df = get_minute_kline(symbol, period="60min", count=count)
    if df.empty:
        return df
    return df.reset_index(drop=True)


def get_kline(symbol: str, period: str = "daily", count: int = 120) -> pd.DataFrame:
    if period == "daily":
        return _get_daily_kline(symbol, count=count)
    if period == "60min":
        return _get_60min_kline(symbol, count=count)
    raise ValueError("period 仅支持 daily 或 60min")


def detect_candlestick(df: pd.DataFrame) -> list:
    """检测当前 K 线形态，返回形态列表。"""
    if df is None or df.empty:
        return []

    for col in ["开盘", "最高", "最低", "收盘"]:
        if col not in df.columns:
            return []

    talib = _load_talib()

    open_ = df["开盘"].astype(float).values
    high = df["最高"].astype(float).values
    low = df["最低"].astype(float).values
    close = df["收盘"].astype(float).values

    results = []
    for p in PATTERNS:
        func = getattr(talib, p["func"], None)
        if func is None:
            continue
        out = func(open_, high, low, close)
        if len(out) == 0:
            continue
        val = out[-1]
        if val == 0:
            continue
        direction = "看涨" if val > 0 else "看跌"
        score = p["score"] if val > 0 else -p["score"]
        results.append({
            "形态": p["name"],
            "方向": direction,
            "分值": score,
            "描述": p["desc"],
        })

    results.sort(key=lambda x: abs(x["分值"]), reverse=True)
    return results


def display_scan(symbol: str, period: str = "daily", count: int = 120):
    """展示形态识别结果。"""
    df = get_kline(symbol, period=period, count=count)
    if df.empty:
        print(f"  ❌ 未获取到 K 线数据: {symbol}")
        return

    title = "日线" if period == "daily" else "60分钟"
    print_header(f"{symbol} K 线形态识别 ({title})")
    patterns = detect_candlestick(df)
    if not patterns:
        print("  当前未识别到明显形态")
        return

    print_section("识别结果")
    for p in patterns:
        print_kv(p["形态"], f"{p['方向']} | 分值 {p['分值']} | {p['描述']}")


def main():
    parser = argparse.ArgumentParser(description="K 线形态识别")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    p_scan = sub.add_parser("scan", help="扫描单只股票的形态")
    p_scan.add_argument("--symbol", required=True, help="股票代码")
    p_scan.add_argument("--period", default="daily", choices=["daily", "60min"])
    p_scan.add_argument("--count", type=int, default=120)

    args = parser.parse_args()

    if args.action == "scan":
        display_scan(args.symbol, period=args.period, count=args.count)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
