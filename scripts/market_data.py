"""
行情查询模块 — A股交易助手
提供实时行情、K线数据、涨跌排行等功能。
数据源：Sina Finance（稳定免费，不依赖东方财富 push2 接口）。
"""

import argparse
import sys

import akshare as ak
import pandas as pd

from utils import (
    normalize_symbol, filter_stocks, sina_realtime_quote, _sina_symbol,
    format_number, format_percent, format_price,
    print_header, print_section, print_kv, print_table,
    get_cache, set_cache,
)


def get_realtime_quote(symbol: str) -> dict:
    """获取个股实时行情（Sina 接口）。"""
    code = normalize_symbol(symbol)
    df = sina_realtime_quote([code])
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


def get_kline(symbol: str, period: str = "daily", count: int = 30,
              adjust: str = "qfq") -> pd.DataFrame:
    """
    获取 K 线数据（Sina 接口）。
    period: daily
    adjust: qfq (前复权) / hfq (后复权) / '' (不复权)
    """
    code = normalize_symbol(symbol)
    sina_code = _sina_symbol(code)
    try:
        df = ak.stock_zh_a_daily(symbol=sina_code, adjust=adjust)
        if df.empty:
            return df
        # 统一列名
        col_map = {
            "date": "日期", "open": "开盘", "close": "收盘",
            "high": "最高", "low": "最低",
            "volume": "成交量", "amount": "成交额",
        }
        df = df.rename(columns=col_map)
        if "日期" in df.columns:
            df["日期"] = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d")
        # 计算涨跌幅
        if "收盘" in df.columns:
            df["涨跌幅"] = df["收盘"].pct_change() * 100
            df["涨跌幅"] = df["涨跌幅"].round(2)
        return df.tail(count).reset_index(drop=True)
    except Exception as e:
        print(f"  ⚠️ 获取 K 线数据失败: {e}")
        return pd.DataFrame()


def get_all_realtime() -> pd.DataFrame:
    """获取全市场实时行情（Sina 接口）。"""
    cached = get_cache("all_realtime", ttl_minutes=2)
    if cached is not None:
        return pd.DataFrame(cached)

    try:
        df = ak.stock_zh_a_spot()  # 使用 Sina 接口
        df["代码"] = df["代码"].astype(str).str.zfill(6)
        # 统一列名（Sina 接口列名可能不同）
        col_map = {
            "symbol": "代码", "code": "代码", "name": "名称",
            "trade": "最新价", "changepercent": "涨跌幅",
            "open": "今开", "high": "最高", "low": "最低",
            "volume": "成交量", "amount": "成交额",
            "turnoverratio": "换手率", "settlement": "昨收",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        set_cache("all_realtime", df.to_dict(orient="records"))
        return df
    except Exception as e:
        print(f"  ⚠️ 获取全市场行情失败: {e}")
        return pd.DataFrame()


def get_top_gainers(count: int = 10) -> pd.DataFrame:
    """获取涨幅排行。"""
    df = get_all_realtime()
    if df.empty:
        return df
    df = filter_stocks(df)
    change_col = "涨跌幅" if "涨跌幅" in df.columns else "changepercent"
    df = df.sort_values(change_col, ascending=False).head(count)
    cols = ["代码", "名称", "最新价", "涨跌幅", "成交量", "成交额", "换手率"]
    return df[[c for c in cols if c in df.columns]].reset_index(drop=True)


def get_top_losers(count: int = 10) -> pd.DataFrame:
    """获取跌幅排行。"""
    df = get_all_realtime()
    if df.empty:
        return df
    df = filter_stocks(df)
    change_col = "涨跌幅" if "涨跌幅" in df.columns else "changepercent"
    df = df.sort_values(change_col, ascending=True).head(count)
    cols = ["代码", "名称", "最新价", "涨跌幅", "成交量", "成交额", "换手率"]
    return df[[c for c in cols if c in df.columns]].reset_index(drop=True)


# ─── 输出 ────────────────────────────────────────────────────────────────────────

def display_realtime(symbol: str):
    """展示个股实时行情。"""
    data = get_realtime_quote(symbol)
    if not data:
        print(f"  ❌ 未找到股票: {symbol}")
        return

    name = data.get("名称", "")
    code = data.get("代码", symbol)
    print_header(f"{name} ({code}) 实时行情")

    print_kv("最新价", format_price(data.get("最新价")))
    print_kv("涨跌幅", format_percent(data.get("涨跌幅")))
    print_kv("涨跌额", format_price(data.get("涨跌额")))
    print_kv("今开", format_price(data.get("今开")))
    print_kv("最高", format_price(data.get("最高")))
    print_kv("最低", format_price(data.get("最低")))
    print_kv("昨收", format_price(data.get("昨收")))
    print_kv("成交量", format_number(data.get("成交量"), unit="股"))
    print_kv("成交额", format_number(data.get("成交额"), unit=""))


def display_kline(symbol: str, period: str = "daily", count: int = 30):
    """展示 K 线数据。"""
    code = normalize_symbol(symbol)
    df = get_kline(code, period=period, count=count)
    if df.empty:
        print(f"  ❌ 未找到 K 线数据: {symbol}")
        return

    period_name = {"daily": "日线", "weekly": "周线", "monthly": "月线"}.get(period, period)
    print_header(f"{code} {period_name} K 线 (最近 {count} 个)")
    cols = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "涨跌幅"]
    display_cols = [c for c in cols if c in df.columns]
    print_table(df[display_cols])


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="A股行情查询")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    # 实时行情
    p_rt = sub.add_parser("realtime", help="查询个股实时行情")
    p_rt.add_argument("--symbol", required=True, help="股票代码")

    # K 线
    p_kl = sub.add_parser("kline", help="查询 K 线数据")
    p_kl.add_argument("--symbol", required=True, help="股票代码")
    p_kl.add_argument("--period", default="daily", choices=["daily"])
    p_kl.add_argument("--count", type=int, default=30, help="K 线数量")

    # 涨幅排行
    p_tg = sub.add_parser("top_gainers", help="涨幅排行")
    p_tg.add_argument("--count", type=int, default=10)

    # 跌幅排行
    p_tl = sub.add_parser("top_losers", help="跌幅排行")
    p_tl.add_argument("--count", type=int, default=10)

    args = parser.parse_args()

    if args.action == "realtime":
        display_realtime(args.symbol)
    elif args.action == "kline":
        display_kline(args.symbol, period=args.period, count=args.count)
    elif args.action == "top_gainers":
        df = get_top_gainers(args.count)
        print_header(f"涨幅排行 Top {args.count}")
        print_table(df)
    elif args.action == "top_losers":
        df = get_top_losers(args.count)
        print_header(f"跌幅排行 Top {args.count}")
        print_table(df)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
