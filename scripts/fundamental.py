"""
基本面分析模块 — A股交易助手
提供财务报表查询、估值指标分析等基本面分析功能。
数据源：Sina Finance（稳定免费）。
"""

import argparse
import sys

import akshare as ak
import pandas as pd

from utils import (
    normalize_symbol, sina_realtime_quote,
    format_number, format_percent, format_price,
    print_header, print_section, print_kv, print_table,
    get_cache, set_cache,
)


def get_stock_info(symbol: str) -> dict:
    """获取个股基本信息（通过 Sina 实时行情 + 财务指标）。"""
    code = normalize_symbol(symbol)
    cached = get_cache("stock_info", ttl_minutes=60, symbol=code)
    if cached:
        return cached

    result = {}
    # 从实时行情获取基本信息
    quote_df = sina_realtime_quote([code])
    if not quote_df.empty:
        row = quote_df.iloc[0]
        result["股票代码"] = code
        result["股票简称"] = row.get("名称", "")
        result["最新价"] = row.get("最新价", 0)

    if result:
        set_cache("stock_info", result, symbol=code)
    return result


def get_valuation(symbol: str) -> dict:
    """获取估值指标（从 Sina 实时行情提取）。"""
    code = normalize_symbol(symbol)
    quote_df = sina_realtime_quote([code])
    if quote_df.empty:
        return {}
    row = quote_df.iloc[0]
    return {
        "代码": code,
        "名称": row.get("名称", ""),
        "最新价": row.get("最新价"),
        "涨跌幅": row.get("涨跌幅"),
        "成交量": row.get("成交量"),
        "成交额": row.get("成交额"),
    }


def get_financial_income(symbol: str) -> pd.DataFrame:
    """获取利润表。"""
    code = normalize_symbol(symbol)
    try:
        df = ak.stock_financial_report_sina(stock=code, symbol="利润表")
        return df.head(4)  # 最近 4 期
    except Exception as e:
        print(f"  ⚠️ 获取利润表失败: {e}")
        return pd.DataFrame()


def get_financial_balance(symbol: str) -> pd.DataFrame:
    """获取资产负债表。"""
    code = normalize_symbol(symbol)
    try:
        df = ak.stock_financial_report_sina(stock=code, symbol="资产负债表")
        return df.head(4)
    except Exception as e:
        print(f"  ⚠️ 获取资产负债表失败: {e}")
        return pd.DataFrame()


def get_financial_cashflow(symbol: str) -> pd.DataFrame:
    """获取现金流量表。"""
    code = normalize_symbol(symbol)
    try:
        df = ak.stock_financial_report_sina(stock=code, symbol="现金流量表")
        return df.head(4)
    except Exception as e:
        print(f"  ⚠️ 获取现金流量表失败: {e}")
        return pd.DataFrame()


def get_financial_indicators(symbol: str) -> pd.DataFrame:
    """获取主要财务指标。"""
    code = normalize_symbol(symbol)
    try:
        df = ak.stock_financial_abstract_ths(symbol=code)
        return df
    except Exception:
        try:
            df = ak.stock_financial_analysis_indicator(symbol=code)
            return df.head(8)
        except Exception as e:
            print(f"  ⚠️ 获取财务指标失败: {e}")
            return pd.DataFrame()


# ─── 输出 ────────────────────────────────────────────────────────────────────────

def display_analyze(symbol: str):
    """综合基本面分析展示。"""
    code = normalize_symbol(symbol)

    # 基本信息
    info = get_stock_info(code)
    name = info.get("股票简称", code)
    print_header(f"{name} ({code}) 基本面分析")

    if info:
        print_section("基本信息")
        for k in ["股票简称", "股票代码", "最新价"]:
            if k in info:
                print_kv(k, str(info[k]))

    # 估值指标
    val = get_valuation(code)
    if val:
        print_section("行情指标")
        print_kv("最新价", format_price(val.get("最新价")))
        print_kv("涨跌幅", format_percent(val.get("涨跌幅")))
        print_kv("成交量", format_number(val.get("成交量"), unit="股"))
        print_kv("成交额", format_number(val.get("成交额")))

    # 财务指标
    fi = get_financial_indicators(code)
    if not fi.empty:
        print_section("主要财务指标")
        print_table(fi, max_rows=8)

    # 利润表摘要
    income = get_financial_income(code)
    if not income.empty:
        print_section("利润表 (最近 4 期)")
        key_cols = ["报告日", "营业总收入", "营业收入", "净利润"]
        display_cols = [c for c in key_cols if c in income.columns]
        if display_cols:
            print_table(income[display_cols])
        else:
            print_table(income)


def display_valuation(symbol: str):
    """仅展示估值指标。"""
    code = normalize_symbol(symbol)
    val = get_valuation(code)
    if not val:
        print(f"  ❌ 未找到估值数据: {symbol}")
        return

    name = val.get("名称", code)
    print_header(f"{name} ({code}) 行情指标")
    print_kv("最新价", format_price(val.get("最新价")))
    print_kv("涨跌幅", format_percent(val.get("涨跌幅")))
    print_kv("成交量", format_number(val.get("成交量"), unit="股"))
    print_kv("成交额", format_number(val.get("成交额")))


def display_financial(symbol: str, report: str = "income"):
    """展示财务报表。"""
    code = normalize_symbol(symbol)
    report_map = {
        "income": ("利润表", get_financial_income),
        "balance": ("资产负债表", get_financial_balance),
        "cashflow": ("现金流量表", get_financial_cashflow),
    }
    if report not in report_map:
        print(f"  ❌ 不支持的报表类型: {report}")
        return

    title, func = report_map[report]
    df = func(code)
    print_header(f"{code} {title}")
    if df.empty:
        print("  (无数据)")
    else:
        print_table(df)


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="A股基本面分析")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    p_a = sub.add_parser("analyze", help="综合基本面分析")
    p_a.add_argument("--symbol", required=True, help="股票代码")

    p_v = sub.add_parser("valuation", help="估值指标")
    p_v.add_argument("--symbol", required=True, help="股票代码")

    p_f = sub.add_parser("financial", help="财务报表")
    p_f.add_argument("--symbol", required=True, help="股票代码")
    p_f.add_argument("--report", default="income",
                     choices=["income", "balance", "cashflow"])

    args = parser.parse_args()

    if args.action == "analyze":
        display_analyze(args.symbol)
    elif args.action == "valuation":
        display_valuation(args.symbol)
    elif args.action == "financial":
        display_financial(args.symbol, args.report)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
