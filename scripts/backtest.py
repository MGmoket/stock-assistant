"""
策略回测模块 — A股交易助手
用历史数据验证选股策略，输出胜率、盈亏比、最大回撤等指标。
"""

import argparse
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
import numpy as np

from utils import (
    normalize_symbol, format_number, format_percent, format_price,
    print_header, print_section, print_kv,
)


# ─── 回测引擎 ────────────────────────────────────────────────────────────────────

class BacktestResult:
    """回测结果。"""
    def __init__(self):
        self.trades = []
        self.initial_capital = 0
        self.final_capital = 0
        self.max_drawdown = 0
        self.peak_capital = 0

    @property
    def total_return(self):
        if self.initial_capital <= 0:
            return 0
        return (self.final_capital - self.initial_capital) / self.initial_capital * 100

    @property
    def win_trades(self):
        return [t for t in self.trades if t.get("profit", 0) > 0]

    @property
    def lose_trades(self):
        return [t for t in self.trades if t.get("profit", 0) <= 0]

    @property
    def win_rate(self):
        if not self.trades:
            return 0
        return len(self.win_trades) / len(self.trades) * 100

    @property
    def profit_loss_ratio(self):
        avg_win = np.mean([t["profit"] for t in self.win_trades]) if self.win_trades else 0
        avg_loss = abs(np.mean([t["profit"] for t in self.lose_trades])) if self.lose_trades else 1
        return avg_win / avg_loss if avg_loss > 0 else float("inf")

    def display(self, strategy_name: str):
        """展示回测报告。"""
        print_header(f"📊 策略回测报告 — {strategy_name}")

        print_section("绩效概览")
        emoji = "🟢" if self.total_return >= 0 else "🔴"
        print_kv("初始资金", format_price(self.initial_capital))
        print_kv("最终资金", format_price(self.final_capital))
        print_kv("总收益率", f"{emoji} {format_percent(self.total_return)}")
        print_kv("最大回撤", f"🔴 {format_percent(self.max_drawdown)}")

        print_section("交易统计")
        print_kv("总交易次数", f"{len(self.trades)} 次")
        print_kv("盈利次数", f"{len(self.win_trades)} 次")
        print_kv("亏损次数", f"{len(self.lose_trades)} 次")
        print_kv("胜率", format_percent(self.win_rate))
        print_kv("盈亏比", f"{self.profit_loss_ratio:.2f}")

        if self.win_trades:
            avg_win = np.mean([t["profit_pct"] for t in self.win_trades])
            max_win = max(t["profit_pct"] for t in self.win_trades)
            print_kv("平均盈利", format_percent(avg_win))
            print_kv("最大单笔盈利", format_percent(max_win))

        if self.lose_trades:
            avg_loss = np.mean([t["profit_pct"] for t in self.lose_trades])
            max_loss = min(t["profit_pct"] for t in self.lose_trades)
            print_kv("平均亏损", format_percent(avg_loss))
            print_kv("最大单笔亏损", format_percent(max_loss))

        if self.trades:
            print_section("交易明细 (最近 10 笔)")
            for t in self.trades[-10:]:
                emoji = "🟢" if t["profit"] >= 0 else "🔴"
                print(f"    {t['date']} {t['code']} {emoji} "
                      f"买 {format_price(t['buy_price'])} → 卖 {format_price(t['sell_price'])} "
                      f"盈亏 {format_percent(t['profit_pct'])}")


def _get_hist_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取历史日线数据。"""
    code = normalize_symbol(symbol)
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    sina_code = f"{prefix}{code}"
    try:
        df = ak.stock_zh_a_daily(symbol=sina_code, adjust="qfq")
        df["date"] = pd.to_datetime(df["date"])
        mask = (df["date"] >= start_date) & (df["date"] <= end_date)
        return df[mask].reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


# ─── 内置策略 ────────────────────────────────────────────────────────────────────

def strategy_ma_cross(df: pd.DataFrame, short_period: int = 5, long_period: int = 20) -> list:
    """
    均线金叉/死叉策略。
    金叉买入，死叉卖出。
    """
    if len(df) < long_period + 5:
        return []

    df = df.copy()
    df["ma_short"] = df["close"].rolling(short_period).mean()
    df["ma_long"] = df["close"].rolling(long_period).mean()
    df = df.dropna().reset_index(drop=True)

    signals = []
    holding = False
    buy_price = 0
    buy_date = ""

    for i in range(1, len(df)):
        prev_short = df.iloc[i - 1]["ma_short"]
        prev_long = df.iloc[i - 1]["ma_long"]
        curr_short = df.iloc[i]["ma_short"]
        curr_long = df.iloc[i]["ma_long"]

        # 金叉: 短均线上穿长均线
        if prev_short <= prev_long and curr_short > curr_long and not holding:
            buy_price = df.iloc[i]["close"]
            buy_date = str(df.iloc[i]["date"])[:10]
            holding = True

        # 死叉: 短均线下穿长均线
        elif prev_short >= prev_long and curr_short < curr_long and holding:
            sell_price = df.iloc[i]["close"]
            sell_date = str(df.iloc[i]["date"])[:10]
            profit = sell_price - buy_price
            profit_pct = profit / buy_price * 100
            signals.append({
                "date": f"{buy_date} → {sell_date}",
                "buy_price": round(buy_price, 2),
                "sell_price": round(sell_price, 2),
                "profit": round(profit, 2),
                "profit_pct": round(profit_pct, 2),
            })
            holding = False

    return signals


def strategy_macd_cross(df: pd.DataFrame) -> list:
    """MACD 金叉/死叉策略。"""
    if len(df) < 35:
        return []

    df = df.copy()
    exp1 = df["close"].ewm(span=12, adjust=False).mean()
    exp2 = df["close"].ewm(span=26, adjust=False).mean()
    df["dif"] = exp1 - exp2
    df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
    df = df.iloc[33:].reset_index(drop=True)  # 跳过不可靠的前期数据

    signals = []
    holding = False
    buy_price = 0
    buy_date = ""

    for i in range(1, len(df)):
        prev_dif = df.iloc[i - 1]["dif"]
        prev_dea = df.iloc[i - 1]["dea"]
        curr_dif = df.iloc[i]["dif"]
        curr_dea = df.iloc[i]["dea"]

        if prev_dif <= prev_dea and curr_dif > curr_dea and not holding:
            buy_price = df.iloc[i]["close"]
            buy_date = str(df.iloc[i]["date"])[:10]
            holding = True
        elif prev_dif >= prev_dea and curr_dif < curr_dea and holding:
            sell_price = df.iloc[i]["close"]
            sell_date = str(df.iloc[i]["date"])[:10]
            profit = sell_price - buy_price
            profit_pct = profit / buy_price * 100
            signals.append({
                "date": f"{buy_date} → {sell_date}",
                "buy_price": round(buy_price, 2),
                "sell_price": round(sell_price, 2),
                "profit": round(profit, 2),
                "profit_pct": round(profit_pct, 2),
            })
            holding = False

    return signals


# ─── 回测入口 ────────────────────────────────────────────────────────────────────

STRATEGIES = {
    "ma_cross": ("均线金叉死叉", strategy_ma_cross),
    "macd_cross": ("MACD金叉死叉", strategy_macd_cross),
}


def run_backtest(symbol: str, strategy_name: str = "ma_cross",
                 start_date: str = None, end_date: str = None,
                 capital: float = 30000) -> BacktestResult:
    """运行策略回测。"""
    code = normalize_symbol(symbol)

    if not start_date:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    if strategy_name not in STRATEGIES:
        print(f"  ❌ 不支持的策略: {strategy_name}")
        print(f"     可选: {list(STRATEGIES.keys())}")
        return BacktestResult()

    strategy_label, strategy_func = STRATEGIES[strategy_name]
    print(f"  ⏳ 正在回测 {code} [{strategy_label}] {start_date} ~ {end_date}")

    df = _get_hist_data(code, start_date, end_date)
    if df.empty or len(df) < 30:
        print(f"  ❌ 历史数据不足: {code}")
        return BacktestResult()

    trades = strategy_func(df)

    result = BacktestResult()
    result.initial_capital = capital
    running_capital = capital
    peak = capital

    for t in trades:
        shares = int(running_capital * 0.8 / t["buy_price"] // 100) * 100
        if shares < 100:
            continue

        cost = shares * t["buy_price"]
        revenue = shares * t["sell_price"]
        profit = revenue - cost

        running_capital += profit
        peak = max(peak, running_capital)
        drawdown = (peak - running_capital) / peak * 100
        result.max_drawdown = max(result.max_drawdown, drawdown)

        t["code"] = code
        t["shares"] = shares
        t["profit"] = round(profit, 2)
        result.trades.append(t)

    result.final_capital = round(running_capital, 2)
    result.peak_capital = peak
    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="策略回测")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    p_run = sub.add_parser("run", help="运行回测")
    p_run.add_argument("--symbol", required=True, help="股票代码")
    p_run.add_argument("--strategy", default="ma_cross",
                       choices=list(STRATEGIES.keys()), help="策略名称")
    p_run.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD")
    p_run.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    p_run.add_argument("--capital", type=float, default=30000)

    sub.add_parser("list", help="列出可用策略")

    args = parser.parse_args()

    if args.action == "run":
        result = run_backtest(args.symbol, strategy_name=args.strategy,
                              start_date=args.start, end_date=args.end,
                              capital=args.capital)
        strategy_label = STRATEGIES.get(args.strategy, ("", None))[0]
        result.display(f"{args.symbol} {strategy_label}")
    elif args.action == "list":
        print_header("可用回测策略")
        for key, (label, _) in STRATEGIES.items():
            print(f"    📌 {key}: {label}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
