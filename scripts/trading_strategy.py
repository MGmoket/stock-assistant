"""
交易策略与建议模块 — A股交易助手
针对每只股票生成结构化交易建议，包含仓位、止损、止盈、风险评级。
"""

import argparse
import sys
import math

import pandas as pd
import numpy as np

from utils import (
    normalize_symbol, sina_realtime_quote,
    format_number, format_percent, format_price,
    print_header, print_section, print_kv,
)


# ─── 策略参数 ────────────────────────────────────────────────────────────────────

MAX_SINGLE_POSITION_PCT = 0.50   # 单只最大仓位 50%
MAX_TOTAL_POSITION_PCT = 0.80    # 最大总仓位 80%
MAX_HOLDINGS = 3                 # 最多同时持有 3 只
MIN_LOT = 100                    # 最小交易单位


def _round_lot(shares: int) -> int:
    """向下取整到 100 股的整数倍。"""
    return (shares // MIN_LOT) * MIN_LOT


# ─── 交易建议生成 ─────────────────────────────────────────────────────────────────

def generate_advice(symbol: str, capital: float = 30000,
                    existing_positions: int = 0) -> dict:
    """为指定股票生成交易建议。"""
    from technical import _get_hist, calc_ma, calc_macd, calc_kdj, calc_boll, calc_rsi, calc_volume_analysis, calc_score

    code = normalize_symbol(symbol)

    # 获取实时行情
    quote_df = sina_realtime_quote([code])
    if quote_df.empty:
        return {"error": f"未找到股票: {code}"}

    quote = quote_df.iloc[0].to_dict()
    name = quote.get("名称", "")
    current_price = float(quote.get("最新价", 0))
    if current_price <= 0:
        return {"error": f"无法获取有效价格: {code}"}

    # 获取历史数据与技术分析
    hist = _get_hist(code, count=120)
    if hist.empty or len(hist) < 30:
        return {"error": f"历史数据不足: {code}"}

    ma = calc_ma(hist)
    macd = calc_macd(hist)
    kdj = calc_kdj(hist)
    boll = calc_boll(hist)
    rsi = calc_rsi(hist)
    vol = calc_volume_analysis(hist)
    tech_score = calc_score(ma, macd, kdj, boll, rsi, vol)

    score = tech_score["分数"]
    rating = tech_score["评级"]

    # ─── 方向判断 ─────────────────────────────────────────────────────────
    if score >= 60:
        direction = "买入"
        direction_emoji = "🟢"
    elif score >= 40:
        direction = "观望"
        direction_emoji = "⚪"
    else:
        direction = "回避"
        direction_emoji = "🔴"

    # ─── 止损止盈 ─────────────────────────────────────────────────────────
    close_prices = hist["收盘"].astype(float)
    low_prices = hist["最低"].astype(float)
    recent_low = low_prices.tail(10).min()
    boll_lower = boll["下轨"]

    stop_loss = max(boll_lower, recent_low)
    stop_loss = max(stop_loss, current_price * 0.95)
    stop_loss_pct = (stop_loss - current_price) / current_price * 100

    recent_high = hist["最高"].astype(float).tail(10).max()
    boll_upper = boll["上轨"]
    take_profit = min(boll_upper, recent_high * 1.02)
    take_profit = max(take_profit, current_price * 1.03)
    take_profit_pct = (take_profit - current_price) / current_price * 100

    # ─── 仓位计算 ─────────────────────────────────────────────────────────
    available_slots = MAX_HOLDINGS - existing_positions
    if available_slots <= 0 or direction != "买入":
        position_pct = 0
        shares = 0
        amount = 0
    else:
        if score >= 80:
            position_pct = MAX_SINGLE_POSITION_PCT
        elif score >= 70:
            position_pct = 0.35
        elif score >= 60:
            position_pct = 0.25
        else:
            position_pct = 0

        max_amount = capital * position_pct
        shares = _round_lot(int(max_amount / current_price))
        amount = shares * current_price

        if shares < MIN_LOT and direction == "买入":
            if capital >= current_price * MIN_LOT:
                shares = MIN_LOT
                amount = shares * current_price
                position_pct = amount / capital
            else:
                shares = 0
                amount = 0
                position_pct = 0

    # ─── 风险评级 ─────────────────────────────────────────────────────────
    risk_factors = []
    risk_score = 0

    daily_returns = close_prices.pct_change().dropna()
    volatility = daily_returns.std() * 100
    if volatility > 4:
        risk_factors.append("高波动性")
        risk_score += 2
    elif volatility > 2.5:
        risk_factors.append("中等波动性")
        risk_score += 1

    change_pct = float(quote.get("涨跌幅", 0))
    if change_pct > 5:
        risk_factors.append("当日涨幅已大，追高风险")
        risk_score += 2

    rsi6_val = rsi.get("RSI6", {}).get("值", 50)
    if rsi6_val > 70:
        risk_factors.append("RSI 指标超买")
        risk_score += 1

    if risk_score >= 4:
        risk_level = "⭐⭐⭐⭐ 高"
    elif risk_score >= 2:
        risk_level = "⭐⭐⭐ 中等"
    else:
        risk_level = "⭐⭐ 较低"

    # ─── 买入理由 ─────────────────────────────────────────────────────────
    buy_reasons = []
    if macd.get("金叉"):
        buy_reasons.append("MACD 日线金叉，短线动能转强")
    elif macd.get("趋势") == "多头":
        buy_reasons.append("MACD 多头趋势")
    if kdj.get("金叉"):
        buy_reasons.append("KDJ 金叉信号")
    if ma.get("多头排列"):
        buy_reasons.append("均线多头排列，趋势向好")
    if "放量上涨" in vol.get("量价配合", ""):
        buy_reasons.append("放量上涨，资金积极介入")
    if "缩量回调" in vol.get("量价配合", ""):
        buy_reasons.append("缩量回调，抛压减轻")
    if boll.get("位置百分比", 50) < 30:
        buy_reasons.append("股价接近布林带下轨，有支撑")
    if rsi6_val < 30:
        buy_reasons.append("RSI 超卖，有反弹动能")

    if not buy_reasons:
        buy_reasons.append("综合技术指标偏多" if score >= 50 else "当前无明显买入信号")

    return {
        "代码": code, "名称": name, "当前价": current_price,
        "方向": direction, "方向标识": direction_emoji,
        "建议价格": round(current_price * 0.998, 2),
        "止损价": round(stop_loss, 2), "止损幅度": round(stop_loss_pct, 1),
        "止盈价": round(take_profit, 2), "止盈幅度": round(take_profit_pct, 1),
        "建议仓位": round(position_pct * 100, 1),
        "买入股数": shares, "买入金额": round(amount, 2),
        "风险评级": risk_level, "技术评分": score, "技术评级": rating,
        "买入理由": buy_reasons,
        "风险提示": risk_factors if risk_factors else ["暂无明显风险"],
    }


# ─── 输出 ────────────────────────────────────────────────────────────────────────

def display_advice(advice: dict):
    """展示单只股票交易建议。"""
    if "error" in advice:
        print(f"  ❌ {advice['error']}")
        return

    name = advice["名称"]
    code = advice["代码"]
    emoji = advice["方向标识"]

    print(f"\n{'━' * 50}")
    print(f"  📊 交易建议 — {name} ({code})")
    print(f"{'━' * 50}")

    print_kv("方向", f"{emoji} {advice['方向']}")
    print_kv("当前价", format_price(advice["当前价"]))
    print_kv("建议价格", format_price(advice["建议价格"]))
    print_kv("止损价", f"{format_price(advice['止损价'])} ({advice['止损幅度']:+.1f}%)")
    print_kv("止盈价", f"{format_price(advice['止盈价'])} ({advice['止盈幅度']:+.1f}%)")

    if advice["买入股数"] > 0:
        print_kv("建议仓位", f"{advice['建议仓位']:.0f}%")
        print_kv("买入股数", f"{advice['买入股数']} 股")
        print_kv("买入金额", format_price(advice['买入金额']))

    print_kv("风险评级", advice["风险评级"])
    print_kv("技术评分", f"{advice['技术评分']} — {advice['技术评级']}")

    print(f"\n    {'─' * 40}")
    print(f"    买入理由:")
    for i, reason in enumerate(advice["买入理由"], 1):
        print(f"      {i}. {reason}")

    print(f"\n    风险提示:")
    for i, risk in enumerate(advice["风险提示"], 1):
        print(f"      {i}. {risk}")

    if advice["方向"] == "买入" and advice["买入股数"] > 0:
        print(f"\n{'─' * 50}")
        print(f"  🔔 操作指令 — 请在东方财富执行:")
        print(f"    股票: {name} ({code})")
        print(f"    方向: 买入")
        print(f"    价格: 限价 {format_price(advice['建议价格'])}")
        print(f"    数量: {advice['买入股数']} 股")
        print(f"    金额: {format_price(advice['买入金额'])}")
        print(f"{'─' * 50}")


def display_batch(symbols: list, capital: float = 30000):
    """批量生成交易建议。"""
    print_header(f"批量交易建议 (可用资金: {format_price(capital)})")
    advices = []
    for i, sym in enumerate(symbols):
        advice = generate_advice(sym, capital=capital, existing_positions=i)
        advices.append(advice)
        display_advice(advice)

    buy_list = [a for a in advices if a.get("方向") == "买入" and a.get("买入股数", 0) > 0]
    if buy_list:
        total_amount = sum(a["买入金额"] for a in buy_list)
        print(f"\n{'━' * 50}")
        print(f"  📋 汇总")
        print(f"{'━' * 50}")
        print_kv("建议买入", f"{len(buy_list)} 只")
        print_kv("总金额", format_price(total_amount))
        print_kv("剩余现金", format_price(capital - total_amount))


def display_daily_plan(capital: float = 30000):
    """生成每日交易计划。"""
    from stock_screener import run_preset
    print_header(f"📅 每日交易计划 (资金: {format_price(capital)})")
    print("\n  ⏳ 正在选股...")
    candidates = run_preset("short_term", count=5)
    if candidates.empty:
        print("  今日暂无推荐股票")
        return
    symbols = candidates["代码"].tolist()
    print(f"  ✅ 选出 {len(symbols)} 只候选股票\n")
    display_batch(symbols, capital=capital)


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="A股交易策略与建议")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    p_adv = sub.add_parser("advise", help="对指定股票生成交易建议")
    p_adv.add_argument("--symbol", required=True)
    p_adv.add_argument("--capital", type=float, default=30000)

    p_bat = sub.add_parser("batch", help="批量生成交易建议")
    p_bat.add_argument("--symbols", required=True, help="逗号分隔的代码")
    p_bat.add_argument("--capital", type=float, default=30000)

    p_dp = sub.add_parser("daily-plan", help="生成每日交易计划")
    p_dp.add_argument("--capital", type=float, default=30000)

    args = parser.parse_args()

    if args.action == "advise":
        advice = generate_advice(args.symbol, capital=args.capital)
        display_advice(advice)
    elif args.action == "batch":
        symbols = [s.strip() for s in args.symbols.split(",")]
        display_batch(symbols, capital=args.capital)
    elif args.action == "daily-plan":
        display_daily_plan(capital=args.capital)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
