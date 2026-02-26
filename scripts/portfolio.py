"""
持仓管理模块 — A股交易助手
记录买入/卖出操作，实时计算持仓盈亏，提供持仓汇总和交易历史。
"""

import argparse
import sys
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from utils import (
    normalize_symbol, format_number, format_percent, format_price,
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


def _save_portfolio(data: dict):
    """保存持仓数据。"""
    ensure_dirs()
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def record_buy(symbol: str, price: float, quantity: int, note: str = ""):
    """记录买入操作。"""
    code = normalize_symbol(symbol)
    data = _load_portfolio()

    if code in data["positions"]:
        pos = data["positions"][code]
        old_qty = pos["quantity"]
        old_cost = pos["avg_cost"]
        new_qty = old_qty + quantity
        new_cost = (old_cost * old_qty + price * quantity) / new_qty
        pos["quantity"] = new_qty
        pos["avg_cost"] = round(new_cost, 4)
    else:
        data["positions"][code] = {
            "symbol": code,
            "quantity": quantity,
            "avg_cost": round(price, 4),
            "first_buy_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    # 记录交易历史
    data["history"].append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": code,
        "action": "买入",
        "price": price,
        "quantity": quantity,
        "amount": round(price * quantity, 2),
        "note": note,
    })

    _save_portfolio(data)
    print(f"  ✅ 已记录买入: {code} × {quantity} 股 @ {format_price(price)}")
    print(f"     金额: {format_price(price * quantity)}")


def record_sell(symbol: str, price: float, quantity: int, note: str = ""):
    """记录卖出操作。"""
    code = normalize_symbol(symbol)
    data = _load_portfolio()

    if code not in data["positions"]:
        print(f"  ❌ 当前未持有 {code}")
        return

    pos = data["positions"][code]
    if quantity > pos["quantity"]:
        print(f"  ❌ 卖出数量 ({quantity}) 超过持有数量 ({pos['quantity']})")
        return

    # 计算盈亏
    profit = (price - pos["avg_cost"]) * quantity
    profit_pct = (price - pos["avg_cost"]) / pos["avg_cost"] * 100

    pos["quantity"] -= quantity
    if pos["quantity"] == 0:
        del data["positions"][code]

    # 记录交易历史
    data["history"].append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": code,
        "action": "卖出",
        "price": price,
        "quantity": quantity,
        "amount": round(price * quantity, 2),
        "profit": round(profit, 2),
        "profit_pct": round(profit_pct, 2),
        "note": note,
    })

    _save_portfolio(data)
    profit_str = format_price(profit)
    pct_str = format_percent(profit_pct)
    emoji = "🟢" if profit >= 0 else "🔴"
    print(f"  ✅ 已记录卖出: {code} × {quantity} 股 @ {format_price(price)}")
    print(f"     金额: {format_price(price * quantity)}")
    print(f"     盈亏: {emoji} {profit_str} ({pct_str})")


def get_portfolio_summary() -> dict:
    """获取持仓汇总（含实时盈亏）。"""
    from market_data import get_realtime_quote

    data = _load_portfolio()
    positions = data.get("positions", {})

    if not positions:
        return {"total_cost": 0, "total_value": 0, "total_profit": 0,
                "total_profit_pct": 0, "holdings": []}

    holdings = []
    total_cost = 0
    total_value = 0

    for code, pos in positions.items():
        qty = pos["quantity"]
        avg_cost = pos["avg_cost"]
        cost = avg_cost * qty
        total_cost += cost

        # 获取实时价格
        quote = get_realtime_quote(code)
        current_price = float(quote.get("最新价", avg_cost)) if quote else avg_cost
        name = quote.get("名称", code) if quote else code
        change_pct = float(quote.get("涨跌幅", 0)) if quote else 0

        value = current_price * qty
        total_value += value
        profit = value - cost
        profit_pct = (current_price - avg_cost) / avg_cost * 100

        holdings.append({
            "代码": code,
            "名称": name,
            "持有数量": qty,
            "成本价": avg_cost,
            "现价": current_price,
            "今日涨跌": change_pct,
            "持仓成本": round(cost, 2),
            "市值": round(value, 2),
            "浮动盈亏": round(profit, 2),
            "盈亏比例": round(profit_pct, 2),
        })

    total_profit = total_value - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0

    return {
        "total_cost": round(total_cost, 2),
        "total_value": round(total_value, 2),
        "total_profit": round(total_profit, 2),
        "total_profit_pct": round(total_profit_pct, 2),
        "holdings": holdings,
    }


# ─── 输出 ────────────────────────────────────────────────────────────────────────

def display_summary():
    """展示持仓汇总。"""
    summary = get_portfolio_summary()

    print_header("持仓汇总")

    if not summary["holdings"]:
        print("  📭 当前无持仓")
        return

    # 总览
    emoji = "🟢" if summary["total_profit"] >= 0 else "🔴"
    print_section("总览")
    print_kv("持仓成本", format_price(summary["total_cost"]))
    print_kv("持仓市值", format_price(summary["total_value"]))
    print_kv("浮动盈亏", f"{emoji} {format_price(summary['total_profit'])} ({format_percent(summary['total_profit_pct'])})")
    print_kv("持股数量", f"{len(summary['holdings'])} 只")

    # 逐只展示
    print_section("持仓明细")
    for h in summary["holdings"]:
        emoji = "🟢" if h["浮动盈亏"] >= 0 else "🔴"
        print(f"\n    {h['名称']} ({h['代码']})")
        print(f"      持有: {h['持有数量']} 股  |  成本: {format_price(h['成本价'])}  |  现价: {format_price(h['现价'])}")
        print(f"      今日: {format_percent(h['今日涨跌'])}  |  盈亏: {emoji} {format_price(h['浮动盈亏'])} ({format_percent(h['盈亏比例'])})")


def display_history(count: int = 20):
    """展示交易历史。"""
    data = _load_portfolio()
    history = data.get("history", [])

    print_header(f"交易历史 (最近 {count} 条)")

    if not history:
        print("  📭 暂无交易记录")
        return

    for record in reversed(history[-count:]):
        action = record["action"]
        emoji = "🟢 买入" if action == "买入" else "🔴 卖出"
        line = f"    [{record['time']}] {emoji} {record['symbol']} × {record['quantity']} 股 @ {format_price(record['price'])}"

        if "profit" in record:
            p_emoji = "📈" if record["profit"] >= 0 else "📉"
            line += f"  |  {p_emoji} 盈亏: {format_price(record['profit'])} ({format_percent(record.get('profit_pct', 0))})"

        print(line)
        if record.get("note"):
            print(f"           备注: {record['note']}")


def display_pnl():
    """展示盈亏分析。"""
    data = _load_portfolio()
    history = data.get("history", [])

    print_header("盈亏分析")

    sells = [h for h in history if h["action"] == "卖出" and "profit" in h]

    if not sells:
        print("  📭 暂无已了结交易")
        # 展示浮动盈亏
        summary = get_portfolio_summary()
        if summary["holdings"]:
            print_section("当前浮动盈亏")
            for h in summary["holdings"]:
                emoji = "🟢" if h["浮动盈亏"] >= 0 else "🔴"
                print(f"    {h['名称']} ({h['代码']}): {emoji} {format_price(h['浮动盈亏'])} ({format_percent(h['盈亏比例'])})")
        return

    # 已了结盈亏统计
    total_profit = sum(s["profit"] for s in sells)
    win_trades = [s for s in sells if s["profit"] > 0]
    lose_trades = [s for s in sells if s["profit"] <= 0]
    win_rate = len(win_trades) / len(sells) * 100 if sells else 0

    print_section("已了结交易统计")
    print_kv("总交易次数", f"{len(sells)} 次")
    print_kv("盈利次数", f"{len(win_trades)} 次")
    print_kv("亏损次数", f"{len(lose_trades)} 次")
    print_kv("胜率", format_percent(win_rate))
    print_kv("累计盈亏", f"{'🟢' if total_profit >= 0 else '🔴'} {format_price(total_profit)}")

    if win_trades:
        avg_win = sum(s["profit"] for s in win_trades) / len(win_trades)
        max_win = max(s["profit"] for s in win_trades)
        print_kv("平均盈利", format_price(avg_win))
        print_kv("最大单笔盈利", format_price(max_win))

    if lose_trades:
        avg_loss = sum(s["profit"] for s in lose_trades) / len(lose_trades)
        max_loss = min(s["profit"] for s in lose_trades)
        print_kv("平均亏损", format_price(avg_loss))
        print_kv("最大单笔亏损", format_price(max_loss))

    # 盈亏比
    if win_trades and lose_trades:
        avg_win = sum(s["profit"] for s in win_trades) / len(win_trades)
        avg_loss = abs(sum(s["profit"] for s in lose_trades) / len(lose_trades))
        if avg_loss > 0:
            print_kv("盈亏比", f"{avg_win / avg_loss:.2f}")


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="A股持仓管理")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    sub.add_parser("summary", help="持仓汇总")

    p_buy = sub.add_parser("buy", help="记录买入")
    p_buy.add_argument("--symbol", required=True, help="股票代码")
    p_buy.add_argument("--price", type=float, required=True, help="买入价格")
    p_buy.add_argument("--quantity", type=int, required=True, help="买入数量(股)")
    p_buy.add_argument("--note", default="", help="备注")

    p_sell = sub.add_parser("sell", help="记录卖出")
    p_sell.add_argument("--symbol", required=True, help="股票代码")
    p_sell.add_argument("--price", type=float, required=True, help="卖出价格")
    p_sell.add_argument("--quantity", type=int, required=True, help="卖出数量(股)")
    p_sell.add_argument("--note", default="", help="备注")

    sub.add_parser("history", help="交易历史")
    sub.add_parser("pnl", help="盈亏分析")

    args = parser.parse_args()

    if args.action == "summary":
        display_summary()
    elif args.action == "buy":
        record_buy(args.symbol, args.price, args.quantity, args.note)
    elif args.action == "sell":
        record_sell(args.symbol, args.price, args.quantity, args.note)
    elif args.action == "history":
        display_history()
    elif args.action == "pnl":
        display_pnl()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
