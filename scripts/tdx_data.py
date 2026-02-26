"""
通达信行情数据模块 — A股交易助手
通过 pytdx 获取分钟K线、五档盘口、分时成交明细。
免费、无需注册，直接连接通达信公共行情服务器。
"""

import argparse
import random
import time

import pandas as pd
from pytdx.hq import TdxHq_API

from utils import (
    normalize_symbol, format_number, format_percent, format_price,
    print_header, print_section, print_kv, print_table,
    get_cache, set_cache,
)

# ─── 通达信服务器 ────────────────────────────────────────────────────────────────

# 公共行情服务器列表（自动选择最快的）
TDX_SERVERS = [
    ("119.147.212.81", 7709),
    ("112.74.214.43", 7727),
    ("221.231.141.60", 7709),
    ("101.227.73.20", 7709),
    ("101.227.77.254", 7709),
    ("14.215.128.18", 7709),
    ("59.173.18.140", 7709),
    ("218.75.126.9", 7709),
    ("115.238.56.198", 7709),
    ("124.160.88.183", 7709),
]


def _get_market(code: str) -> int:
    """返回 pytdx market 参数: 0=深圳, 1=上海。"""
    code = normalize_symbol(code)
    if code.startswith(("6", "9")):
        return 1  # 上海
    return 0  # 深圳


def _connect() -> TdxHq_API:
    """连接通达信服务器（自动选择）。"""
    api = TdxHq_API()
    servers = TDX_SERVERS.copy()
    random.shuffle(servers)

    for host, port in servers:
        try:
            if api.connect(host, port):
                return api
        except Exception:
            continue

    raise ConnectionError("无法连接通达信行情服务器，请检查网络")


# K 线类型映射
KLINE_CATEGORIES = {
    "1min": 8,    # 1分钟
    "5min": 0,    # 5分钟
    "15min": 1,   # 15分钟
    "30min": 2,   # 30分钟
    "60min": 3,   # 60分钟
    "daily": 4,   # 日线
    "weekly": 5,  # 周线
    "monthly": 6, # 月线
}


# ─── 核心数据接口 ────────────────────────────────────────────────────────────────

def get_minute_kline(symbol: str, period: str = "5min", count: int = 48) -> pd.DataFrame:
    """
    获取分钟级 K 线数据。
    period: 1min, 5min, 15min, 30min, 60min
    count: K 线条数（默认一个交易日的 5 分钟线 = 48 条）
    """
    code = normalize_symbol(symbol)
    market = _get_market(code)
    category = KLINE_CATEGORIES.get(period)
    if category is None:
        raise ValueError(f"不支持的周期: {period}，可选: {list(KLINE_CATEGORIES.keys())}")

    api = _connect()
    try:
        data = api.get_security_bars(category, market, code, 0, count)
        if not data:
            return pd.DataFrame()

        df = api.to_df(data)
        # 标准化列名
        col_map = {
            "datetime": "时间", "open": "开盘", "close": "收盘",
            "high": "最高", "low": "最低",
            "vol": "成交量", "amount": "成交额",
        }
        df = df.rename(columns=col_map)
        # 计算涨跌幅
        if "收盘" in df.columns:
            df["涨跌幅"] = df["收盘"].pct_change() * 100
            df["涨跌幅"] = df["涨跌幅"].round(2)
        return df
    finally:
        api.disconnect()


def get_orderbook(symbol: str) -> dict:
    """获取五档盘口数据。"""
    code = normalize_symbol(symbol)
    market = _get_market(code)

    api = _connect()
    try:
        data = api.get_security_quotes([(market, code)])
        if not data:
            return {}

        q = data[0]
        return {
            "代码": code,
            "名称": q.get("name", ""),
            "最新价": q.get("price", 0),
            "昨收": q.get("last_close", 0),
            "今开": q.get("open", 0),
            "最高": q.get("high", 0),
            "最低": q.get("low", 0),
            "成交量": q.get("vol", 0),
            "成交额": q.get("amount", 0),
            "涨跌幅": round((q.get("price", 0) - q.get("last_close", 1)) / q.get("last_close", 1) * 100, 2) if q.get("last_close", 0) > 0 else 0,
            "买一": {"价": q.get("bid1", 0), "量": q.get("bid_vol1", 0)},
            "买二": {"价": q.get("bid2", 0), "量": q.get("bid_vol2", 0)},
            "买三": {"价": q.get("bid3", 0), "量": q.get("bid_vol3", 0)},
            "买四": {"价": q.get("bid4", 0), "量": q.get("bid_vol4", 0)},
            "买五": {"价": q.get("bid5", 0), "量": q.get("bid_vol5", 0)},
            "卖一": {"价": q.get("ask1", 0), "量": q.get("ask_vol1", 0)},
            "卖二": {"价": q.get("ask2", 0), "量": q.get("ask_vol2", 0)},
            "卖三": {"价": q.get("ask3", 0), "量": q.get("ask_vol3", 0)},
            "卖四": {"价": q.get("ask4", 0), "量": q.get("ask_vol4", 0)},
            "卖五": {"价": q.get("ask5", 0), "量": q.get("ask_vol5", 0)},
        }
    finally:
        api.disconnect()


def get_tick_data(symbol: str, count: int = 60) -> pd.DataFrame:
    """
    获取分时成交明细。
    返回最近 count 笔成交，含大单标记。
    """
    code = normalize_symbol(symbol)
    market = _get_market(code)

    api = _connect()
    try:
        data = api.get_transaction_data(market, code, 0, count)
        if not data:
            return pd.DataFrame()

        df = api.to_df(data)
        col_map = {
            "time": "时间", "price": "价格", "vol": "手数",
            "buyorsell": "方向",
        }
        df = df.rename(columns=col_map)

        # 方向中文化
        if "方向" in df.columns:
            df["方向"] = df["方向"].map({0: "买入", 1: "卖出", 2: "中性"}).fillna("未知")

        # 金额计算（手数 × 100股 × 价格）
        if "手数" in df.columns and "价格" in df.columns:
            df["金额"] = df["手数"] * 100 * df["价格"]
            # 大单标记（>50万元）
            df["大单"] = df["金额"].apply(lambda x: "🔥" if x >= 500000 else "")

        return df
    finally:
        api.disconnect()


def get_batch_quotes(symbols: list) -> pd.DataFrame:
    """批量获取实时行情（含五档）。"""
    api = _connect()
    try:
        params = [(_get_market(normalize_symbol(s)), normalize_symbol(s)) for s in symbols]
        data = api.get_security_quotes(params)
        if not data:
            return pd.DataFrame()

        rows = []
        for q in data:
            rows.append({
                "代码": q.get("code", ""),
                "名称": q.get("name", ""),
                "最新价": q.get("price", 0),
                "涨跌幅": round((q.get("price", 0) - q.get("last_close", 1)) / q.get("last_close", 1) * 100, 2) if q.get("last_close", 0) > 0 else 0,
                "成交量": q.get("vol", 0),
                "成交额": q.get("amount", 0),
                "买一": q.get("bid1", 0),
                "卖一": q.get("ask1", 0),
            })
        return pd.DataFrame(rows)
    finally:
        api.disconnect()


# ─── 输出 ────────────────────────────────────────────────────────────────────────

def display_minute_kline(symbol: str, period: str = "5min", count: int = 20):
    """展示分钟K线。"""
    code = normalize_symbol(symbol)
    df = get_minute_kline(code, period=period, count=count)
    if df.empty:
        print(f"  ❌ 未获取到数据: {symbol}")
        return

    period_name = {"1min": "1分钟", "5min": "5分钟", "15min": "15分钟",
                   "30min": "30分钟", "60min": "60分钟"}.get(period, period)
    print_header(f"{code} {period_name} K线 (最近 {count} 条)")
    cols = ["时间", "开盘", "收盘", "最高", "最低", "成交量", "涨跌幅"]
    display_cols = [c for c in cols if c in df.columns]
    print_table(df[display_cols], max_rows=count)


def display_orderbook(symbol: str):
    """展示五档盘口。"""
    data = get_orderbook(symbol)
    if not data:
        print(f"  ❌ 未获取到盘口: {symbol}")
        return

    name = data.get("名称", "")
    code = data.get("代码", symbol)
    print_header(f"{name} ({code}) 五档盘口")

    print_kv("最新价", format_price(data["最新价"]))
    print_kv("涨跌幅", format_percent(data["涨跌幅"]))
    print_kv("今开", format_price(data["今开"]))
    print_kv("最高", format_price(data["最高"]))
    print_kv("最低", format_price(data["最低"]))
    print_kv("成交量", format_number(data["成交量"]))

    print_section("卖盘")
    for i in range(5, 0, -1):
        key = f"卖{['一','二','三','四','五'][i-1]}"
        info = data[key]
        print(f"    {key}: {format_price(info['价'])}  ×  {info['量']} 手")

    print_section("买盘")
    for i in range(1, 6):
        key = f"买{['一','二','三','四','五'][i-1]}"
        info = data[key]
        print(f"    {key}: {format_price(info['价'])}  ×  {info['量']} 手")


def display_ticks(symbol: str, count: int = 30):
    """展示分时成交明细。"""
    code = normalize_symbol(symbol)
    df = get_tick_data(code, count=count)
    if df.empty:
        print(f"  ❌ 未获取到成交明细: {symbol}")
        return

    print_header(f"{code} 分时成交明细 (最近 {count} 笔)")
    cols = ["时间", "价格", "手数", "方向", "金额", "大单"]
    display_cols = [c for c in cols if c in df.columns]
    print_table(df[display_cols], max_rows=count)

    # 大单统计
    if "金额" in df.columns:
        big_orders = df[df.get("大单", pd.Series()) == "🔥"]
        if not big_orders.empty:
            buy_big = big_orders[big_orders["方向"] == "买入"]["金额"].sum()
            sell_big = big_orders[big_orders["方向"] == "卖出"]["金额"].sum()
            print_section("大单统计 (>50万)")
            print_kv("大单买入", format_number(buy_big))
            print_kv("大单卖出", format_number(sell_big))
            net = buy_big - sell_big
            emoji = "🟢" if net >= 0 else "🔴"
            print_kv("净流入", f"{emoji} {format_number(net)}")


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="通达信行情数据（分钟级）")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    p_min = sub.add_parser("minute", help="分钟K线")
    p_min.add_argument("--symbol", required=True, help="股票代码")
    p_min.add_argument("--period", default="5min",
                       choices=["1min", "5min", "15min", "30min", "60min"])
    p_min.add_argument("--count", type=int, default=20, help="K线条数")

    p_ob = sub.add_parser("orderbook", help="五档盘口")
    p_ob.add_argument("--symbol", required=True, help="股票代码")

    p_tk = sub.add_parser("ticks", help="分时成交明细")
    p_tk.add_argument("--symbol", required=True, help="股票代码")
    p_tk.add_argument("--count", type=int, default=30, help="条数")

    p_bq = sub.add_parser("batch-quotes", help="批量实时行情")
    p_bq.add_argument("--symbols", required=True, help="逗号分隔的代码")

    args = parser.parse_args()

    if args.action == "minute":
        display_minute_kline(args.symbol, period=args.period, count=args.count)
    elif args.action == "orderbook":
        display_orderbook(args.symbol)
    elif args.action == "ticks":
        display_ticks(args.symbol, count=args.count)
    elif args.action == "batch-quotes":
        symbols = [s.strip() for s in args.symbols.split(",")]
        df = get_batch_quotes(symbols)
        print_header(f"批量实时行情 ({len(symbols)} 只)")
        print_table(df)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
