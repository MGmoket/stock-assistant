"""
每日复盘模块 — A股交易助手
盘后生成当日复盘报告：持仓表现、操作回顾、市场概况。
"""

import argparse
import json
from datetime import datetime, date

import pandas as pd

from utils import (
    normalize_symbol, sina_realtime_quote,
    format_number, format_percent, format_price,
    print_header, print_section, print_kv, print_table,
    ensure_dirs, DATA_DIR,
)


PORTFOLIO_FILE = DATA_DIR / "portfolio.json"


def _load_portfolio() -> dict:
    """加载持仓数据。"""
    ensure_dirs()
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"positions": {}, "history": [], "cash_record": []}


def _get_today(target_date: str = None) -> str:
    """返回目标日期字符串。"""
    if target_date:
        return target_date
    return datetime.now().strftime("%Y-%m-%d")


# ─── 复盘报告 ────────────────────────────────────────────────────────────────────

def generate_review(target_date: str = None):
    """生成每日复盘报告。"""
    today = _get_today(target_date)
    data = _load_portfolio()

    print(f"\n{'━' * 55}")
    print(f"  📋 每日复盘报告 — {today}")
    print(f"{'━' * 55}")

    # ─── 1. 持仓表现 ─────────────────────────────────────────
    positions = data.get("positions", {})
    if positions:
        print_section("📈 持仓表现")

        codes = list(positions.keys())
        quotes = sina_realtime_quote(codes) if codes else pd.DataFrame()

        total_cost = 0
        total_value = 0

        for code, pos in positions.items():
            qty = pos["quantity"]
            avg_cost = pos["avg_cost"]
            cost = avg_cost * qty
            total_cost += cost

            # 获取实时价格
            current_price = avg_cost
            name = code
            change_pct = 0
            if not quotes.empty:
                match = quotes[quotes["代码"] == code]
                if not match.empty:
                    row = match.iloc[0]
                    current_price = float(row.get("最新价", avg_cost))
                    name = row.get("名称", code)
                    change_pct = float(row.get("涨跌幅", 0))

            value = current_price * qty
            total_value += value
            profit = value - cost
            profit_pct = (current_price - avg_cost) / avg_cost * 100

            p_emoji = "🟢" if profit >= 0 else "🔴"
            d_emoji = "📈" if change_pct >= 0 else "📉"

            print(f"\n    {name} ({code})")
            print(f"      持有 {qty} 股 | 成本 {format_price(avg_cost)} | 现价 {format_price(current_price)}")
            print(f"      {d_emoji} 今日 {format_percent(change_pct)} | {p_emoji} 盈亏 {format_price(profit)} ({format_percent(profit_pct)})")

        # 组合总绩效
        total_profit = total_value - total_cost
        total_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0
        emoji = "🟢" if total_profit >= 0 else "🔴"
        print(f"\n    {'─' * 45}")
        print(f"    组合总市值: {format_price(total_value)}")
        print(f"    总盈亏: {emoji} {format_price(total_profit)} ({format_percent(total_pct)})")
    else:
        print_section("📈 持仓表现")
        print("    📭 当前无持仓")

    # ─── 2. 今日操作 ─────────────────────────────────────────
    history = data.get("history", [])
    today_trades = [h for h in history if h.get("time", "").startswith(today)]

    print_section("📝 今日操作")
    if today_trades:
        for t in today_trades:
            action = t["action"]
            emoji = "🟢 买入" if action == "买入" else "🔴 卖出"
            line = f"    {emoji} {t['symbol']} × {t['quantity']} 股 @ {format_price(t['price'])}"
            if "profit" in t:
                p_emoji = "📈" if t["profit"] >= 0 else "📉"
                line += f" | {p_emoji} 盈亏 {format_price(t['profit'])}"
            print(line)
            if t.get("note"):
                print(f"      备注: {t['note']}")
    else:
        print("    今日无交易操作")

    # ─── 3. 市场概况 ─────────────────────────────────────────
    print_section("🌐 市场概况")
    try:
        market_codes = ["000001", "399001", "399006"]  # 上证/深证/创业板
        market_names = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指"}
        mq = sina_realtime_quote(market_codes)
        if not mq.empty:
            for _, row in mq.iterrows():
                code = row.get("代码", "")
                name = market_names.get(code, code)
                price = row.get("最新价", 0)
                change = row.get("涨跌幅", 0)
                emoji = "📈" if change >= 0 else "📉"
                print(f"    {emoji} {name}: {format_price(price)} ({format_percent(change)})")
        else:
            print("    (无法获取指数数据)")
    except Exception as e:
        print(f"    ⚠️ 获取市场数据失败: {e}")

    # ─── 4. 小结 ─────────────────────────────────────────────
    print_section("💡 复盘小结")
    if positions:
        win_count = sum(1 for code, pos in positions.items()
                       if _get_current_price(code, quotes if 'quotes' in dir() else pd.DataFrame()) > pos["avg_cost"])
        total_count = len(positions)
        print(f"    持仓 {total_count} 只，盈利 {win_count} 只，亏损 {total_count - win_count} 只")
    if today_trades:
        buy_count = sum(1 for t in today_trades if t["action"] == "买入")
        sell_count = sum(1 for t in today_trades if t["action"] == "卖出")
        print(f"    今日操作: 买入 {buy_count} 次, 卖出 {sell_count} 次")
    print()


def _get_current_price(code: str, quotes_df: pd.DataFrame) -> float:
    """从已有行情 DataFrame 获取当前价。"""
    if quotes_df.empty:
        return 0
    match = quotes_df[quotes_df["代码"] == code]
    if match.empty:
        return 0
    return float(match.iloc[0].get("最新价", 0))


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="每日复盘")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    p_rev = sub.add_parser("review", help="生成今日复盘报告")
    p_rev.add_argument("--date", default=None, help="指定日期 (YYYY-MM-DD)")

    args = parser.parse_args()

    if args.action == "review":
        generate_review(target_date=args.date)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
