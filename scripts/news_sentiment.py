"""
消息面/舆情模块 — A股交易助手
提供个股公告、财经新闻、研报等消息面数据。
"""

import argparse
import sys

import akshare as ak
import pandas as pd

from utils import (
    normalize_symbol, print_header, print_section, print_kv, print_table,
    get_cache, set_cache,
)


def get_announcements(symbol: str, count: int = 10) -> pd.DataFrame:
    """获取个股公告。"""
    code = normalize_symbol(symbol)
    try:
        df = ak.stock_notice_report(symbol=code)
        if df.empty:
            return df
        return df.head(count)
    except Exception as e:
        print(f"  ⚠️ 获取公告失败: {e}")
        return pd.DataFrame()


def get_financial_news(count: int = 20) -> pd.DataFrame:
    """获取最新财经新闻。"""
    try:
        df = ak.stock_news_em(symbol="财经导读")
        if df.empty:
            return df
        return df.head(count)
    except Exception:
        try:
            # 备用：股票要闻
            df = ak.news_cctv(date=pd.Timestamp.now().strftime("%Y%m%d"))
            return df.head(count)
        except Exception as e:
            print(f"  ⚠️ 获取新闻失败: {e}")
            return pd.DataFrame()


def get_stock_news(symbol: str, count: int = 10) -> pd.DataFrame:
    """获取个股相关新闻。"""
    code = normalize_symbol(symbol)
    try:
        df = ak.stock_news_em(symbol=code)
        if df.empty:
            return df
        return df.head(count)
    except Exception as e:
        print(f"  ⚠️ 获取个股新闻失败: {e}")
        return pd.DataFrame()


def get_research_reports(symbol: str = None, count: int = 10) -> pd.DataFrame:
    """获取研报。"""
    try:
        if symbol:
            code = normalize_symbol(symbol)
            df = ak.stock_research_report_em(symbol=code)
        else:
            df = ak.stock_research_report_em(symbol="")
        if df.empty:
            return df
        return df.head(count)
    except Exception as e:
        print(f"  ⚠️ 获取研报失败: {e}")
        return pd.DataFrame()


# ─── 输出 ────────────────────────────────────────────────────────────────────────

def display_announcements(symbol: str, count: int = 10):
    """展示个股公告。"""
    code = normalize_symbol(symbol)
    df = get_announcements(code, count=count)
    print_header(f"{code} 最新公告")
    if df.empty:
        print("  (无数据)")
    else:
        for idx, row in df.iterrows():
            title = row.get("公告标题", row.get("title", ""))
            date = row.get("公告日期", row.get("date", ""))
            print(f"    [{date}] {title}")
            if idx >= count - 1:
                break


def display_news():
    """展示最新财经新闻。"""
    df = get_financial_news()
    print_header("最新财经新闻")
    if df.empty:
        print("  (无数据)")
    else:
        for idx, row in df.iterrows():
            title = row.get("新闻标题", row.get("title", str(row.iloc[0]) if len(row) > 0 else ""))
            date = row.get("发布时间", row.get("date", ""))
            source = row.get("新闻来源", row.get("source", ""))
            src_str = f" [{source}]" if source else ""
            print(f"    {date}{src_str} {title}")


def display_stock_news(symbol: str, count: int = 10):
    """展示个股新闻。"""
    code = normalize_symbol(symbol)
    df = get_stock_news(code, count=count)
    print_header(f"{code} 相关新闻")
    if df.empty:
        print("  (无数据)")
    else:
        for idx, row in df.iterrows():
            title = row.get("新闻标题", row.get("title", str(row.iloc[0]) if len(row) > 0 else ""))
            date = row.get("发布时间", row.get("date", ""))
            print(f"    [{date}] {title}")
            if idx >= count - 1:
                break


def display_research(symbol: str = None, count: int = 10):
    """展示研报。"""
    df = get_research_reports(symbol, count=count)
    title = f"{normalize_symbol(symbol)} 研报" if symbol else "最新研报"
    print_header(title)
    if df.empty:
        print("  (无数据)")
    else:
        print_table(df, max_rows=count)


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="A股消息面/舆情")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    p_ann = sub.add_parser("announcement", help="个股公告")
    p_ann.add_argument("--symbol", required=True, help="股票代码")
    p_ann.add_argument("--count", type=int, default=10)

    p_news = sub.add_parser("news", help="最新财经新闻")
    p_news.add_argument("--symbol", default=None, help="个股代码（可选，不填则查询财经要闻）")
    p_news.add_argument("--count", type=int, default=20)

    p_res = sub.add_parser("research", help="研报")
    p_res.add_argument("--symbol", default=None, help="股票代码（可选）")
    p_res.add_argument("--count", type=int, default=10)

    args = parser.parse_args()

    if args.action == "announcement":
        display_announcements(args.symbol, count=args.count)
    elif args.action == "news":
        if args.symbol:
            display_stock_news(args.symbol, count=args.count)
        else:
            display_news()
    elif args.action == "research":
        display_research(args.symbol, count=args.count)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
