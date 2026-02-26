"""
每日复盘模块 — A股交易助手
盘后生成结构化复盘报告：5 问框架。
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
    if target_date:
        return target_date
    return datetime.now().strftime("%Y-%m-%d")


def _get_current_price(code: str, quotes_df: pd.DataFrame) -> float:
    if quotes_df.empty:
        return 0
    match = quotes_df[quotes_df["代码"] == code]
    if match.empty:
        return 0
    return float(match.iloc[0].get("最新价", 0))


# ─── 复盘报告（5 问框架）─────────────────────────────────────────────────────────

def generate_review(target_date: str = None):
    """生成结构化复盘报告。"""
    today = _get_today(target_date)
    data = _load_portfolio()

    print(f"\n{'━' * 55}")
    print(f"  📋 每日复盘报告 — {today}")
    print(f"{'━' * 55}")

    # ─── Q1: 今日市场环境 ─────────────────────────────────────
    print_section("❶ 今日市场环境")
    try:
        market_codes = ["000001", "399001", "399006"]
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

    # 尝试获取情绪周期
    try:
        from market_sentiment import get_market_breadth, get_index_status, calc_sentiment_score
        breadth = get_market_breadth()
        indices = get_index_status()
        sentiment = calc_sentiment_score(breadth, indices)
        print(f"    🌊 情绪评分: {sentiment['分数']} — {sentiment['级别']}")
        if breadth:
            print(f"    📊 涨停 {breadth.get('涨停', '?')} 家 / 跌停 {breadth.get('跌停', '?')} 家 / 连板高度 {breadth.get('连板高度', '?')} 板")
    except Exception:
        print("    (情绪数据暂不可用)")

    # ─── Q2: 盘前计划执行 ─────────────────────────────────────
    print_section("❷ 盘前计划执行")
    history = data.get("history", [])
    today_trades = [h for h in history if h.get("time", "").startswith(today)]
    if today_trades:
        buy_count = sum(1 for t in today_trades if t["action"] == "买入")
        sell_count = sum(1 for t in today_trades if t["action"] == "卖出")
        print(f"    今日操作: 买入 {buy_count} 次, 卖出 {sell_count} 次")
        print("    ⚡ 请自评: 是否按计划执行？偏差在哪？")
    else:
        print("    今日无交易操作")

    # ─── Q3: 个股操作回顾 ─────────────────────────────────────
    print_section("❸ 个股操作回顾")
    if today_trades:
        total_profit = 0
        win_count = 0
        for t in today_trades:
            action = t["action"]
            emoji = "🟢 买入" if action == "买入" else "🔴 卖出"
            line = f"    {emoji} {t['symbol']} × {t['quantity']} 股 @ {format_price(t['price'])}"
            if "profit" in t:
                p_emoji = "📈" if t["profit"] >= 0 else "📉"
                line += f" | {p_emoji} 盈亏 {format_price(t['profit'])}"
                total_profit += t["profit"]
                if t["profit"] > 0:
                    win_count += 1
            print(line)
            if t.get("note"):
                print(f"      理由: {t['note']}")
        sell_trades = [t for t in today_trades if t["action"] == "卖出" and "profit" in t]
        if sell_trades:
            print(f"\n    {'─' * 40}")
            print(f"    今日实现盈亏: {'🟢' if total_profit >= 0 else '🔴'} {format_price(total_profit)}")
    else:
        print("    今日无操作")

    # ─── Q4: 持仓表现 + 胜率统计 ─────────────────────────────
    positions = data.get("positions", {})
    print_section("❹ 持仓表现 & 策略胜率")
    if positions:
        codes = list(positions.keys())
        quotes = sina_realtime_quote(codes) if codes else pd.DataFrame()
        total_cost = 0
        total_value = 0
        win = 0
        for code, pos in positions.items():
            qty = pos["quantity"]
            avg_cost = pos["avg_cost"]
            cost = avg_cost * qty
            total_cost += cost
            current_price = _get_current_price(code, quotes) if not quotes.empty else avg_cost
            if current_price <= 0:
                current_price = avg_cost
            value = current_price * qty
            total_value += value
            profit = value - cost
            profit_pct = (current_price - avg_cost) / avg_cost * 100
            if profit > 0:
                win += 1
            p_emoji = "🟢" if profit >= 0 else "🔴"
            name = code
            change_pct = 0
            if not quotes.empty:
                match = quotes[quotes["代码"] == code]
                if not match.empty:
                    name = match.iloc[0].get("名称", code)
                    change_pct = float(match.iloc[0].get("涨跌幅", 0))
            d_emoji = "📈" if change_pct >= 0 else "📉"
            print(f"    {name}({code}) {d_emoji}{format_percent(change_pct)} | "
                  f"{p_emoji}盈亏 {format_price(profit)} ({format_percent(profit_pct)})")

        total_profit = total_value - total_cost
        total_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0
        print(f"\n    {'─' * 40}")
        print(f"    持仓 {len(positions)} 只，盈利 {win} 只，亏损 {len(positions) - win} 只")
        print(f"    组合市值: {format_price(total_value)} | 总盈亏: {'🟢' if total_profit >= 0 else '🔴'} {format_price(total_profit)} ({format_percent(total_pct)})")
    else:
        print("    📭 当前无持仓")

    # 历史胜率统计
    all_sells = [h for h in history if h.get("action") == "卖出" and "profit" in h]
    if all_sells:
        wins = sum(1 for h in all_sells if h["profit"] > 0)
        total = len(all_sells)
        avg_win = sum(h["profit"] for h in all_sells if h["profit"] > 0) / max(wins, 1)
        avg_loss = abs(sum(h["profit"] for h in all_sells if h["profit"] <= 0)) / max(total - wins, 1)
        pnl_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")
        print(f"\n    📊 历史卖出 {total} 次 | 胜率 {format_percent(wins / total * 100)} | 盈亏比 {pnl_ratio:.2f}")

    # ─── Q5: 明日计划草案 ─────────────────────────────────────
    print_section("❺ 明日计划草案")
    print("    📌 请思考以下问题:")
    print("      1. 明日持仓股有无关键价位需要关注？")
    print("      2. 是否需要止盈/止损/加仓？")
    print("      3. 有无新的关注票？买入条件是什么？")
    print("      4. 明日整体仓位计划？")
    # 如有持仓，给出关键价位提示
    if positions:
        try:
            from technical import _get_hist, calc_boll
            print(f"\n    {'─' * 40}")
            print("    📍 持仓关键价位:")
            for code in list(positions.keys())[:5]:
                hist = _get_hist(code, count=30)
                if hist.empty:
                    continue
                boll = calc_boll(hist)
                print(f"      {code}: 上轨 {format_price(boll['上轨'])} | "
                      f"中轨 {format_price(boll['中轨'])} | "
                      f"下轨 {format_price(boll['下轨'])}")
        except Exception:
            pass
    print()


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="每日复盘（5问框架）")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    p_rev = sub.add_parser("review", help="生成结构化复盘报告")
    p_rev.add_argument("--date", default=None, help="指定日期 (YYYY-MM-DD)")

    args = parser.parse_args()

    if args.action == "review":
        generate_review(target_date=args.date)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
