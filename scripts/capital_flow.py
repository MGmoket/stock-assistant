"""
资金流向模块 — A股交易助手
提供个股主力资金、板块资金、北向资金、融资融券等资金流向数据。
"""

import argparse
import sys

import akshare as ak
import pandas as pd

from utils import (
    normalize_symbol, filter_stocks, format_number, format_percent,
    print_header, print_section, print_kv, print_table,
    get_cache, set_cache,
)


def get_stock_capital_flow(symbol: str) -> dict:
    """获取个股主力资金流向。"""
    code = normalize_symbol(symbol)
    try:
        df = ak.stock_individual_fund_flow(stock=code, market="sh" if code.startswith("6") else "sz")
        if df.empty:
            return {}
        latest = df.iloc[-1].to_dict()
        recent = df.tail(5)
        return {"最新": latest, "近5日": recent}
    except Exception as e:
        print(f"  ⚠️ 获取资金流向失败: {e}")
        return {}


def get_stock_capital_flow_rank() -> pd.DataFrame:
    """获取主力资金流向排行。"""
    try:
        df = ak.stock_individual_fund_flow_rank(indicator="今日")
        df["代码"] = df["代码"].astype(str).str.zfill(6)
        df = filter_stocks(df)
        return df.head(20)
    except Exception as e:
        print(f"  ⚠️ 获取资金流向排行失败: {e}")
        return pd.DataFrame()


def get_sector_capital_flow() -> pd.DataFrame:
    """获取板块资金流向排行。"""
    try:
        df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
        return df.head(20)
    except Exception as e:
        print(f"  ⚠️ 获取板块资金流向失败: {e}")
        return pd.DataFrame()


def get_northbound_flow() -> dict:
    """获取北向资金数据。"""
    try:
        # 沪股通
        df_sh = ak.stock_hsgt_north_net_flow_in_em(symbol="沪股通")
        # 深股通
        df_sz = ak.stock_hsgt_north_net_flow_in_em(symbol="深股通")
        result = {}
        if not df_sh.empty:
            latest_sh = df_sh.iloc[-1].to_dict()
            result["沪股通"] = latest_sh
        if not df_sz.empty:
            latest_sz = df_sz.iloc[-1].to_dict()
            result["深股通"] = latest_sz
        return result
    except Exception as e:
        print(f"  ⚠️ 获取北向资金数据失败: {e}")
        return {}


def get_margin_data(symbol: str) -> pd.DataFrame:
    """获取融资融券数据。"""
    code = normalize_symbol(symbol)
    try:
        df = ak.stock_margin_detail_sse(code)  # 沪市
        return df.tail(10)
    except Exception:
        try:
            df = ak.stock_margin_detail_szse(code)  # 深市
            return df.tail(10)
        except Exception as e:
            print(f"  ⚠️ 获取融资融券数据失败: {e}")
            return pd.DataFrame()


# ─── 输出 ────────────────────────────────────────────────────────────────────────

def display_stock_flow(symbol: str):
    """展示个股资金流向。"""
    code = normalize_symbol(symbol)
    data = get_stock_capital_flow(code)
    if not data:
        print(f"  ❌ 未找到资金流向数据: {symbol}")
        return

    print_header(f"{code} 主力资金流向")

    latest = data.get("最新", {})
    if latest:
        print_section("最新数据")
        for k, v in latest.items():
            if "主力" in str(k) or "净" in str(k) or "日期" in str(k):
                print_kv(str(k), str(v))

    recent = data.get("近5日", pd.DataFrame())
    if not recent.empty:
        print_section("近 5 日走势")
        print_table(recent)


def display_sector_flow():
    """展示板块资金流向。"""
    df = get_sector_capital_flow()
    print_header("板块资金流向排行 (今日)")
    if df.empty:
        print("  (无数据)")
    else:
        print_table(df, max_rows=20)


def display_northbound():
    """展示北向资金。"""
    data = get_northbound_flow()
    print_header("北向资金 (沪深股通)")
    if not data:
        print("  (无数据)")
        return
    for channel, info in data.items():
        print_section(channel)
        for k, v in info.items():
            print_kv(str(k), str(v))


def display_margin(symbol: str):
    """展示融资融券数据。"""
    code = normalize_symbol(symbol)
    df = get_margin_data(code)
    print_header(f"{code} 融资融券数据 (近 10 日)")
    if df.empty:
        print("  (无数据)")
    else:
        print_table(df)


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="A股资金流向")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    p_s = sub.add_parser("stock", help="个股资金流向")
    p_s.add_argument("--symbol", required=True, help="股票代码")

    sub.add_parser("sector", help="板块资金流向排行")
    sub.add_parser("northbound", help="北向资金")

    p_m = sub.add_parser("margin", help="融资融券数据")
    p_m.add_argument("--symbol", required=True, help="股票代码")

    args = parser.parse_args()

    if args.action == "stock":
        display_stock_flow(args.symbol)
    elif args.action == "sector":
        display_sector_flow()
    elif args.action == "northbound":
        display_northbound()
    elif args.action == "margin":
        display_margin(args.symbol)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
