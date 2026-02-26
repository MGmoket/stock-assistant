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
RISK_PER_TRADE_PCT = 0.01        # 单笔风险占用资金比例（默认 1%）


def _round_lot(shares: int) -> int:
    """向下取整到 100 股的整数倍。"""
    return (shares // MIN_LOT) * MIN_LOT


# ─── 交易建议生成 ─────────────────────────────────────────────────────────────────

def generate_advice(symbol: str, capital: float = 30000,
                    existing_positions: int = 0,
                    risk_pct: float = RISK_PER_TRADE_PCT) -> dict:
    """为指定股票生成交易建议。"""
    from technical import (
        _get_hist, calc_ma, calc_macd, calc_kdj, calc_boll,
        calc_rsi, calc_volume_analysis, calc_score, calc_candlestick,
    )

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
    candles = calc_candlestick(hist)
    tech_score = calc_score(ma, macd, kdj, boll, rsi, vol, candles)

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
    if stop_loss >= current_price:
        stop_loss = current_price * 0.98
    stop_loss_pct = (stop_loss - current_price) / current_price * 100

    recent_high = hist["最高"].astype(float).tail(10).max()
    boll_upper = boll["上轨"]
    take_profit = min(boll_upper, recent_high * 1.02)
    take_profit = max(take_profit, current_price * 1.03)
    take_profit_pct = (take_profit - current_price) / current_price * 100

    # ─── 仓位计算 ─────────────────────────────────────────────────────────
    available_slots = MAX_HOLDINGS - existing_positions
    risk_amount = capital * risk_pct
    per_share_risk = current_price - stop_loss
    risk_note = ""
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
        shares_cap = _round_lot(int(max_amount / current_price)) if max_amount > 0 else 0
        if per_share_risk <= 0:
            shares = 0
            amount = 0
            risk_note = "止损价不合理，无法计算 R 倍数仓位"
        else:
            shares_risk = _round_lot(int(risk_amount / per_share_risk))
            shares = min(shares_cap, shares_risk) if shares_cap > 0 else 0
            amount = shares * current_price

        if shares < MIN_LOT and direction == "买入":
            shares = 0
            amount = 0
            position_pct = 0
            if risk_note == "":
                risk_note = "单笔风险不足以覆盖最小交易单位"
        if shares > 0:
            position_pct = amount / capital

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

    if candles:
        bullish = [c for c in candles if c.get("方向") == "看涨"]
        if bullish:
            buy_reasons.append("K线形态出现看涨信号")

    if not buy_reasons:
        buy_reasons.append("综合技术指标偏多" if score >= 50 else "当前无明显买入信号")

    r_multiple = None
    if per_share_risk > 0:
        r_multiple = round((take_profit - current_price) / per_share_risk, 2)

    return {
        "代码": code, "名称": name, "当前价": current_price,
        "方向": direction, "方向标识": direction_emoji,
        "建议价格": round(current_price * 0.998, 2),
        "止损价": round(stop_loss, 2), "止损幅度": round(stop_loss_pct, 1),
        "止盈价": round(take_profit, 2), "止盈幅度": round(take_profit_pct, 1),
        "建议仓位": round(position_pct * 100, 1),
        "买入股数": shares, "买入金额": round(amount, 2),
        "单笔最大亏损": round(risk_amount, 2),
        "R倍数": r_multiple,
        "风险说明": risk_note,
        "风险评级": risk_level, "技术评分": score, "技术评级": rating,
        "买入理由": buy_reasons,
        "风险提示": risk_factors if risk_factors else ["暂无明显风险"],
    }


# ─── 输出 ────────────────────────────────────────────────────────────────────────

def _print_condition_order(advice: dict):
    """输出条件单参数（可直接设到东方财富）。"""
    name = advice["名称"]
    code = advice["代码"]
    if advice["方向"] != "买入" or advice["买入股数"] <= 0:
        return
    print(f"  📌 {name}({code})")
    print(f"     买入条件单: 价格 ≤ {format_price(advice['建议价格'])} 时买入 {advice['买入股数']}股")
    print(f"     止损条件单: 价格 ≤ {format_price(advice['止损价'])} 时全部卖出 ({advice['止损幅度']:+.1f}%)")
    print(f"     止盈条件单: 价格 ≥ {format_price(advice['止盈价'])} 时全部卖出 ({advice['止盈幅度']:+.1f}%)")
    print(f"     金额 {format_price(advice['买入金额'])} | 最大亏损 {format_price(advice['单笔最大亏损'])} | R倍数 {advice.get('R倍数', '-')}")
    print()


def display_advice(advice: dict, brief: bool = False):
    """展示单只股票交易建议。brief=True 只输出条件单参数。"""
    if "error" in advice:
        print(f"  ❌ {advice['error']}")
        return

    if brief:
        _print_condition_order(advice)
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
    print_kv("单笔最大亏损", format_price(advice["单笔最大亏损"]))
    if advice.get("R倍数") is not None:
        print_kv("R倍数", str(advice["R倍数"]))
    if advice.get("风险说明"):
        print_kv("风控说明", advice["风险说明"])

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


def display_batch(symbols: list, capital: float = 30000, risk_pct: float = RISK_PER_TRADE_PCT):
    """批量生成交易建议。"""
    print_header(f"批量交易建议 (可用资金: {format_price(capital)})")
    advices = []
    for i, sym in enumerate(symbols):
        advice = generate_advice(sym, capital=capital, existing_positions=i, risk_pct=risk_pct)
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


def _check_positions(capital: float, risk_pct: float) -> list:
    """检查持仓健康状态。"""
    import json
    from utils import DATA_DIR, ensure_dirs
    ensure_dirs()
    portfolio_file = DATA_DIR / "portfolio.json"
    if not portfolio_file.exists():
        return []
    with open(portfolio_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    positions = data.get("positions", {})
    if not positions:
        return []

    from technical import _get_hist, calc_boll
    codes = list(positions.keys())
    quotes = sina_realtime_quote(codes)
    alerts = []
    for code, pos in positions.items():
        qty = pos["quantity"]
        avg_cost = pos["avg_cost"]
        current_price = avg_cost
        name = code
        if not quotes.empty:
            match = quotes[quotes["代码"] == code]
            if not match.empty:
                current_price = float(match.iloc[0].get("最新价", avg_cost))
                name = match.iloc[0].get("名称", code)
        pnl_pct = (current_price - avg_cost) / avg_cost * 100

        # 计算关键价位
        try:
            hist = _get_hist(code, count=30)
            boll = calc_boll(hist) if not hist.empty else {}
        except Exception:
            boll = {}

        stop_loss = max(boll.get("下轨", avg_cost * 0.95), avg_cost * 0.95)
        take_profit = min(boll.get("上轨", avg_cost * 1.1), avg_cost * 1.1)

        sl_dist = (current_price - stop_loss) / current_price * 100
        tp_dist = (take_profit - current_price) / current_price * 100

        if current_price >= take_profit:
            status = "🔴 已达止盈！建议设卖出条件单"
        elif current_price <= stop_loss:
            status = "🔴 已触止损！建议立即卖出"
        elif sl_dist < 2:
            status = f"⚠️ 接近止损 (距止损 {sl_dist:.1f}%)"
        elif pnl_pct > 5:
            status = f"✅ 盈利 {pnl_pct:+.1f}%，建议上移止损保护浮盈"
        else:
            status = f"✅ 正常 (距止损 {sl_dist:.1f}%, 距止盈 {tp_dist:.1f}%)"

        alerts.append({
            "代码": code, "名称": name, "数量": qty,
            "成本": avg_cost, "现价": current_price,
            "盈亏": pnl_pct, "状态": status,
            "止损": round(stop_loss, 2), "止盈": round(take_profit, 2),
        })
    return alerts


def display_plan(capital: float = 0, risk_pct: float = RISK_PER_TRADE_PCT,
                 extra_symbols: list = None, strategy: str = "short_term",
                 count: int = 3):
    """
    一键生成交易计划:
      Section 1: 条件单参数清单（在最前面）
      Section 2: 持仓健康检查
      Section 3: 详细分析报告
    """
    from stock_screener import run_preset

    # 自动读取总资金
    if capital <= 0:
        from portfolio import get_capital
        capital = get_capital()
    if capital <= 0:
        print("\n  ❌ 未设置总资金，无法计算仓位。")
        print("  请先运行: python3 scripts/portfolio.py set-capital --amount 金额")
        print("  或传入: python3 scripts/trading_strategy.py plan --capital 金额")
        return

    print(f"\n{'━' * 55}")
    print(f"  📋 交易计划 (资金: {format_price(capital)} | 风险: {risk_pct*100:.0f}%)")
    print(f"{'━' * 55}")

    # 获取情绪
    sentiment_score = 50
    sentiment_level = "中性"
    try:
        from market_sentiment import get_market_breadth, get_index_status, calc_sentiment_score
        breadth = get_market_breadth()
        indices = get_index_status()
        sentiment = calc_sentiment_score(breadth, indices)
        sentiment_score = sentiment.get("分数", 50)
        sentiment_level = sentiment.get("级别", "中性")
        position_advice = sentiment.get("建议仓位", "50%")
        print(f"\n  🌊 市场情绪: {sentiment_score} — {sentiment_level} | 建议总仓位 ≤ {position_advice}")
    except Exception:
        print("\n  🌊 市场情绪: (暂不可用)")

    # 选股
    symbols = []
    print(f"\n  ⏳ 正在选股 ({strategy})...")
    try:
        candidates = run_preset(strategy, count=count)
        if not candidates.empty:
            symbols = candidates["代码"].tolist()
    except Exception as e:
        print(f"  ⚠️ 选股失败: {e}")

    # 合并外部候选
    if extra_symbols:
        for s in extra_symbols:
            code = normalize_symbol(s)
            if code not in symbols:
                symbols.append(code)
        print(f"  📎 加入外部候选: {', '.join(extra_symbols)}")

    if not symbols:
        print("  今日暂无候选股票")
    else:
        print(f"  ✅ 共 {len(symbols)} 只候选")

    # 生成所有建议
    advices = []
    for i, sym in enumerate(symbols):
        advice = generate_advice(sym, capital=capital, existing_positions=i, risk_pct=risk_pct)
        advices.append(advice)

    buy_list = [a for a in advices if a.get("方向") == "买入" and a.get("买入股数", 0) > 0]

    # ═══ Section 1: 条件单参数清单 ═══
    print(f"\n{'━' * 55}")
    print(f"  🔔 条件单参数清单 — 可直接设到东方财富")
    print(f"{'━' * 55}\n")

    if buy_list:
        total_amount = 0
        for a in buy_list:
            _print_condition_order(a)
            total_amount += a["买入金额"]
        print(f"  {'─' * 45}")
        print(f"  📊 合计: {len(buy_list)} 只 | 总金额 {format_price(total_amount)} | 剩余 {format_price(capital - total_amount)}")
    else:
        print("  (今日无新建条件单建议)")

    # ═══ Section 2: 持仓健康检查 ═══
    print(f"\n{'━' * 55}")
    print(f"  📊 持仓健康检查")
    print(f"{'━' * 55}")

    alerts = _check_positions(capital, risk_pct)
    if alerts:
        for a in alerts:
            print(f"  {a['状态']}")
            print(f"     {a['名称']}({a['代码']}) {a['数量']}股 | 成本 {format_price(a['成本'])} → 现价 {format_price(a['现价'])} ({a['盈亏']:+.1f}%)")
            print(f"     止损 {format_price(a['止损'])} | 止盈 {format_price(a['止盈'])}")
            print()
    else:
        print("  📭 当前无持仓")

    # ═══ Section 3: 详细分析报告 ═══
    if advices:
        print(f"\n{'━' * 55}")
        print(f"  📝 详细分析报告")
        print(f"{'━' * 55}")
        for advice in advices:
            display_advice(advice)


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="A股交易策略与建议")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    p_adv = sub.add_parser("advise", help="对指定股票生成交易建议")
    p_adv.add_argument("--symbol", required=True)
    p_adv.add_argument("--capital", type=float, default=30000)
    p_adv.add_argument("--risk-pct", type=float, default=RISK_PER_TRADE_PCT,
                       help="单笔最大亏损占用资金比例，如 0.01 或 0.02")

    p_bat = sub.add_parser("batch", help="批量生成交易建议")
    p_bat.add_argument("--symbols", required=True, help="逗号分隔的代码")
    p_bat.add_argument("--capital", type=float, default=30000)
    p_bat.add_argument("--risk-pct", type=float, default=RISK_PER_TRADE_PCT)

    p_plan = sub.add_parser("plan", help="一键生成交易计划（条件单在前 + 持仓检查 + 详细报告）")
    p_plan.add_argument("--capital", type=float, default=0,
                        help="可用资金（不传则自动读取已配置的总资金）")
    p_plan.add_argument("--risk-pct", type=float, default=RISK_PER_TRADE_PCT)
    p_plan.add_argument("--strategy", default="short_term",
                        help="选股策略 (short_term/leader_first_board/trend_pullback)")
    p_plan.add_argument("--extra", default="",
                        help="外部候选代码，逗号分隔 (如 000858,600519)")
    p_plan.add_argument("--count", type=int, default=3, help="选股数量")

    # 兼容旧命令
    p_dp = sub.add_parser("daily-plan", help="(旧版) 等同于 plan")
    p_dp.add_argument("--capital", type=float, default=30000)
    p_dp.add_argument("--risk-pct", type=float, default=RISK_PER_TRADE_PCT)

    args = parser.parse_args()

    if args.action == "advise":
        advice = generate_advice(args.symbol, capital=args.capital, risk_pct=args.risk_pct)
        display_advice(advice)
    elif args.action == "batch":
        symbols = [s.strip() for s in args.symbols.split(",")]
        display_batch(symbols, capital=args.capital, risk_pct=args.risk_pct)
    elif args.action == "plan":
        extra = [s.strip() for s in args.extra.split(",") if s.strip()] if args.extra else None
        display_plan(capital=args.capital, risk_pct=args.risk_pct,
                     extra_symbols=extra, strategy=args.strategy, count=args.count)
    elif args.action == "daily-plan":
        display_plan(capital=args.capital, risk_pct=args.risk_pct)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
