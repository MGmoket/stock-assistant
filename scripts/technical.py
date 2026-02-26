"""
技术面分析模块 — A股交易助手
计算 MA、MACD、KDJ、BOLL、RSI 等技术指标，并给出综合技术评分。
数据源：Sina Finance K 线数据。
"""

import argparse
import sys

import akshare as ak
import numpy as np
import pandas as pd

from utils import (
    normalize_symbol, _sina_symbol, format_price, format_percent,
    print_header, print_section, print_kv,
)


def _get_hist(symbol: str, count: int = 120) -> pd.DataFrame:
    """获取足够长度的历史数据用于指标计算（Sina 接口）。"""
    code = normalize_symbol(symbol)
    sina_code = _sina_symbol(code)
    try:
        df = ak.stock_zh_a_daily(symbol=sina_code, adjust="qfq")
        if df.empty:
            return df
        # 统一列名
        col_map = {
            "date": "日期", "open": "开盘", "close": "收盘",
            "high": "最高", "low": "最低",
            "volume": "成交量", "amount": "成交额",
        }
        df = df.rename(columns=col_map)
        return df.tail(count).reset_index(drop=True)
    except Exception as e:
        print(f"  ⚠️ 获取历史数据失败: {e}")
        return pd.DataFrame()


# ─── 指标计算 ────────────────────────────────────────────────────────────────────

def calc_ma(df: pd.DataFrame, periods: list = None) -> dict:
    """计算移动平均线。"""
    if periods is None:
        periods = [5, 10, 20, 60]
    close = df["收盘"].astype(float)
    current_price = close.iloc[-1]
    result = {"当前价": current_price, "均线": {}}
    for p in periods:
        if len(close) >= p:
            ma_val = close.rolling(p).mean().iloc[-1]
            result["均线"][f"MA{p}"] = {
                "值": round(ma_val, 2),
                "方向": "多头" if current_price > ma_val else "空头",
            }
    # 均线多头排列判断
    ma_vals = [result["均线"].get(f"MA{p}", {}).get("值", 0) for p in periods if f"MA{p}" in result["均线"]]
    if len(ma_vals) >= 3:
        result["多头排列"] = all(ma_vals[i] >= ma_vals[i + 1] for i in range(len(ma_vals) - 1))
    return result


def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """计算 MACD 指标。"""
    close = df["收盘"].astype(float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_hist = 2 * (dif - dea)

    cur_dif = round(dif.iloc[-1], 4)
    cur_dea = round(dea.iloc[-1], 4)
    cur_macd = round(macd_hist.iloc[-1], 4)
    prev_dif = dif.iloc[-2]
    prev_dea = dea.iloc[-2]

    golden_cross = prev_dif <= prev_dea and cur_dif > cur_dea
    death_cross = prev_dif >= prev_dea and cur_dif < cur_dea

    signal_text = "金叉 🟢" if golden_cross else ("死叉 🔴" if death_cross else "无信号")
    trend = "多头" if cur_dif > cur_dea else "空头"

    return {
        "DIF": cur_dif, "DEA": cur_dea, "MACD柱": cur_macd,
        "趋势": trend, "信号": signal_text,
        "金叉": golden_cross, "死叉": death_cross,
    }


def calc_kdj(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> dict:
    """计算 KDJ 指标。"""
    high = df["最高"].astype(float)
    low = df["最低"].astype(float)
    close = df["收盘"].astype(float)

    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    rsv = (close - low_n) / (high_n - low_n) * 100

    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d

    cur_k = round(k.iloc[-1], 2)
    cur_d = round(d.iloc[-1], 2)
    cur_j = round(j.iloc[-1], 2)
    prev_k = k.iloc[-2]
    prev_d = d.iloc[-2]

    golden_cross = prev_k <= prev_d and cur_k > cur_d
    death_cross = prev_k >= prev_d and cur_k < cur_d

    if cur_k > 80 and cur_d > 80:
        zone = "超买区 ⚠️"
    elif cur_k < 20 and cur_d < 20:
        zone = "超卖区 💡"
    else:
        zone = "中性区"

    if golden_cross and cur_k < 30:
        signal_text = "低位金叉 🟢"
    elif golden_cross:
        signal_text = "金叉 🟢"
    elif death_cross and cur_k > 70:
        signal_text = "高位死叉 🔴"
    elif death_cross:
        signal_text = "死叉 🔴"
    else:
        signal_text = "无信号"

    return {
        "K": cur_k, "D": cur_d, "J": cur_j,
        "区域": zone, "信号": signal_text, "金叉": golden_cross,
    }


def calc_boll(df: pd.DataFrame, n: int = 20, k: int = 2) -> dict:
    """计算布林带。"""
    close = df["收盘"].astype(float)
    mid = close.rolling(n).mean().iloc[-1]
    std = close.rolling(n).std().iloc[-1]
    upper = mid + k * std
    lower = mid - k * std
    current = close.iloc[-1]

    width = upper - lower
    position_pct = ((current - lower) / width * 100) if width > 0 else 50

    if current > upper:
        position = "上轨上方 (超买) ⚠️"
    elif current < lower:
        position = "下轨下方 (超卖) 💡"
    elif current > mid:
        position = "中轨与上轨之间 (偏强)"
    else:
        position = "下轨与中轨之间 (偏弱)"

    return {
        "上轨": round(upper, 2), "中轨": round(mid, 2), "下轨": round(lower, 2),
        "当前价": round(current, 2), "位置": position,
        "位置百分比": round(position_pct, 1),
    }


def calc_rsi(df: pd.DataFrame, periods: list = None) -> dict:
    """计算 RSI 指标。"""
    if periods is None:
        periods = [6, 12, 24]
    close = df["收盘"].astype(float)
    delta = close.diff()

    result = {}
    for p in periods:
        gain = delta.clip(lower=0).rolling(p).mean()
        loss = (-delta.clip(upper=0)).rolling(p).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        val = round(rsi.iloc[-1], 2)

        if val > 80:
            zone = "超买 ⚠️"
        elif val > 50:
            zone = "偏强"
        elif val > 20:
            zone = "偏弱"
        else:
            zone = "超卖 💡"

        result[f"RSI{p}"] = {"值": val, "状态": zone}
    return result


def calc_volume_analysis(df: pd.DataFrame) -> dict:
    """成交量分析。"""
    vol = df["成交量"].astype(float)
    close = df["收盘"].astype(float)

    cur_vol = vol.iloc[-1]
    ma5_vol = vol.rolling(5).mean().iloc[-1]
    ma20_vol = vol.rolling(20).mean().iloc[-1]

    vol_ratio = cur_vol / ma5_vol if ma5_vol > 0 else 0
    price_change = (close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100

    if vol_ratio > 2:
        status = "显著放量"
    elif vol_ratio > 1.3:
        status = "温和放量"
    elif vol_ratio < 0.7:
        status = "明显缩量"
    else:
        status = "量能平稳"

    if price_change > 0 and vol_ratio > 1.3:
        combo = "放量上涨 🟢"
    elif price_change < 0 and vol_ratio > 1.3:
        combo = "放量下跌 🔴"
    elif price_change > 0 and vol_ratio < 0.7:
        combo = "缩量上涨 (动能不足)"
    elif price_change < 0 and vol_ratio < 0.7:
        combo = "缩量回调 (抛压减轻) 💡"
    else:
        combo = "正常波动"

    return {
        "今日成交量": int(cur_vol),
        "5日均量": int(ma5_vol),
        "20日均量": int(ma20_vol),
        "量比": round(vol_ratio, 2),
        "量能状态": status,
        "量价配合": combo,
    }


# ─── 综合评分 ────────────────────────────────────────────────────────────────────

def calc_score(ma: dict, macd: dict, kdj: dict, boll: dict, rsi: dict, vol: dict) -> dict:
    """
    综合技术评分（满分 100）。
    > 80: 强烈买入, 60-80: 买入, 40-60: 中性, 20-40: 卖出, < 20: 强烈卖出
    """
    score = 50

    bullish_count = sum(1 for v in ma.get("均线", {}).values() if v.get("方向") == "多头")
    total_ma = len(ma.get("均线", {}))
    if total_ma > 0:
        score += (bullish_count / total_ma - 0.5) * 30
    if ma.get("多头排列"):
        score += 5

    if macd.get("金叉"):
        score += 15
    elif macd.get("死叉"):
        score -= 15
    elif macd.get("趋势") == "多头":
        score += 5
    else:
        score -= 5

    if kdj.get("金叉"):
        score += 10
    k_val = kdj.get("K", 50)
    if k_val < 20:
        score += 5
    elif k_val > 80:
        score -= 5

    boll_pct = boll.get("位置百分比", 50)
    if boll_pct < 20:
        score += 8
    elif boll_pct > 80:
        score -= 5

    rsi6 = rsi.get("RSI6", {}).get("值", 50)
    if rsi6 < 30:
        score += 8
    elif rsi6 > 70:
        score -= 8

    combo = vol.get("量价配合", "")
    if "放量上涨" in combo:
        score += 5
    elif "放量下跌" in combo:
        score -= 5
    elif "缩量回调" in combo:
        score += 3

    score = max(0, min(100, score))

    if score >= 80:
        rating = "强烈买入 🟢🟢"
    elif score >= 60:
        rating = "买入 🟢"
    elif score >= 40:
        rating = "中性 ⚪"
    elif score >= 20:
        rating = "卖出 🔴"
    else:
        rating = "强烈卖出 🔴🔴"

    return {"分数": round(score, 1), "评级": rating}


# ─── 输出 ────────────────────────────────────────────────────────────────────────

def display_full_analysis(symbol: str):
    """综合技术分析展示。"""
    code = normalize_symbol(symbol)
    df = _get_hist(code, count=120)
    if df.empty:
        print(f"  ❌ 未找到数据: {symbol}")
        return

    ma = calc_ma(df)
    macd = calc_macd(df)
    kdj = calc_kdj(df)
    boll = calc_boll(df)
    rsi = calc_rsi(df)
    vol = calc_volume_analysis(df)
    score = calc_score(ma, macd, kdj, boll, rsi, vol)

    print_header(f"{code} 综合技术分析")

    print_section(f"综合评分: {score['分数']} — {score['评级']}")

    print_section("均线系统 (MA)")
    print_kv("当前价", format_price(ma["当前价"]))
    for name, info in ma.get("均线", {}).items():
        print_kv(name, f"{format_price(info['值'])}  [{info['方向']}]")
    if "多头排列" in ma:
        print_kv("多头排列", "✅ 是" if ma["多头排列"] else "❌ 否")

    print_section("MACD")
    print_kv("DIF", str(macd["DIF"]))
    print_kv("DEA", str(macd["DEA"]))
    print_kv("MACD柱", str(macd["MACD柱"]))
    print_kv("趋势", macd["趋势"])
    print_kv("信号", macd["信号"])

    print_section("KDJ")
    print_kv("K", str(kdj["K"]))
    print_kv("D", str(kdj["D"]))
    print_kv("J", str(kdj["J"]))
    print_kv("区域", kdj["区域"])
    print_kv("信号", kdj["信号"])

    print_section("布林带 (BOLL)")
    print_kv("上轨", format_price(boll["上轨"]))
    print_kv("中轨", format_price(boll["中轨"]))
    print_kv("下轨", format_price(boll["下轨"]))
    print_kv("当前位置", boll["位置"])

    print_section("RSI")
    for name, info in rsi.items():
        print_kv(name, f"{info['值']}  [{info['状态']}]")

    print_section("成交量分析")
    print_kv("今日成交量", f"{vol['今日成交量']:,} 手")
    print_kv("5日均量", f"{vol['5日均量']:,} 手")
    print_kv("量比", str(vol["量比"]))
    print_kv("量能状态", vol["量能状态"])
    print_kv("量价配合", vol["量价配合"])


def display_single_indicator(symbol: str, indicator_name: str):
    """展示单个技术指标。"""
    code = normalize_symbol(symbol)
    df = _get_hist(code, count=120)
    if df.empty:
        print(f"  ❌ 未找到数据: {symbol}")
        return

    indicator_map = {
        "ma": ("均线系统", calc_ma),
        "macd": ("MACD", calc_macd),
        "kdj": ("KDJ", calc_kdj),
        "boll": ("布林带", calc_boll),
        "rsi": ("RSI", calc_rsi),
        "volume": ("成交量分析", calc_volume_analysis),
    }

    if indicator_name not in indicator_map:
        print(f"  ❌ 不支持的指标: {indicator_name}")
        print(f"  可选: {', '.join(indicator_map.keys())}")
        return

    title, func = indicator_map[indicator_name]
    result = func(df)
    print_header(f"{code} {title}")

    if isinstance(result, dict):
        for k, v in result.items():
            if isinstance(v, dict):
                for kk, vv in v.items():
                    if isinstance(vv, dict):
                        print_kv(kk, "  ".join(f"{kkk}: {vvv}" for kkk, vvv in vv.items()))
                    else:
                        print_kv(kk, str(vv))
            else:
                print_kv(k, str(v))


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="A股技术面分析")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    p_a = sub.add_parser("analyze", help="综合技术分析")
    p_a.add_argument("--symbol", required=True, help="股票代码")

    p_i = sub.add_parser("indicator", help="查询特定指标")
    p_i.add_argument("--symbol", required=True, help="股票代码")
    p_i.add_argument("--name", required=True,
                     choices=["ma", "macd", "kdj", "boll", "rsi", "volume"],
                     help="指标名称")

    args = parser.parse_args()

    if args.action == "analyze":
        display_full_analysis(args.symbol)
    elif args.action == "indicator":
        display_single_indicator(args.symbol, args.name)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
