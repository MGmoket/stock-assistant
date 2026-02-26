"""
选股引擎模块 — A股交易助手
支持多条件组合筛选，内置短线预设策略。
数据源：Sina Finance API。
"""

import argparse
import sys

import akshare as ak
import pandas as pd
import numpy as np

from utils import (
    normalize_symbol, filter_stocks, is_main_board, is_st,
    sina_realtime_quote, sina_batch_realtime,
    format_number, format_percent, format_price,
    print_header, print_section, print_kv, print_table,
    get_cache, set_cache,
)


# ─── 预设策略 ────────────────────────────────────────────────────────────────────

PRESETS = {
    "short_term": {
        "name": "短线强势股",
        "description": "涨幅 1-7%、换手 3-20%，活跃的短线标的",
        "filters": {
            "涨跌幅_min": 1.0,
            "涨跌幅_max": 7.0,
        },
    },
    "oversold_bounce": {
        "name": "超跌反弹",
        "description": "跌幅较大后出现企稳信号，适合短线抢反弹",
        "filters": {
            "涨跌幅_min": -5.0,
            "涨跌幅_max": -1.0,
        },
    },
    "volume_breakout": {
        "name": "放量突破",
        "description": "涨幅较大 + 成交量活跃",
        "filters": {
            "涨跌幅_min": 3.0,
            "涨跌幅_max": 9.0,
        },
    },
    "leader_first_board": {
        "name": "龙头首板（基础版）",
        "description": "接近涨停 + 合理换手 + 价格区间过滤（降级版）",
        "advanced": True,
        "strategy": "leader_first_board",
        "filters": {
            "涨跌幅_min": 9.5,
            "换手率_min": 5.0,
            "换手率_max": 25.0,
            "price_min": 3.0,
            "price_max": 100.0,
        },
    },
    "trend_pullback": {
        "name": "趋势强股低吸（基础版）",
        "description": "趋势向上 + 回踩 MA10 附近 + RSI 适中",
        "advanced": True,
        "strategy": "trend_pullback",
        "filters": {
            "涨跌幅_min": -3.0,
            "涨跌幅_max": 5.0,
            "price_min": 3.0,
            "price_max": 100.0,
        },
    },
    "ice_reversal": {
        "name": "冰点反转（基础版）",
        "description": "仅在情绪冰点时启用：超跌 + 放量 + 接近下轨",
        "advanced": True,
        "strategy": "ice_reversal",
        "filters": {
            "涨跌幅_max": -2.0,
            "price_min": 2.0,
        },
    },
}


# ─── 选股逻辑 ────────────────────────────────────────────────────────────────────

def _get_all_via_akshare_sina() -> pd.DataFrame:
    """方案 A: AkShare stock_zh_a_spot (Sina 接口)。"""
    df = ak.stock_zh_a_spot()
    df["代码"] = df["代码"].astype(str).str.zfill(6)
    col_map = {
        "trade": "最新价", "changepercent": "涨跌幅",
        "open": "今开", "high": "最高", "low": "最低",
        "volume": "成交量", "amount": "成交额",
        "turnoverratio": "换手率", "settlement": "昨收",
        "name": "名称",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    return df


def _get_all_via_sina_batch() -> pd.DataFrame:
    """方案 B: 用 stock_info_a_code_name 获取代码列表 + sina_realtime_quote 批量获取行情。"""
    info = ak.stock_info_a_code_name()
    if info.empty:
        return pd.DataFrame()
    codes = info["code"].astype(str).str.zfill(6).tolist()
    # 只保留主板代码（0/3/6 开头），减少请求量
    codes = [c for c in codes if is_main_board(c)]
    print(f"  📡 Sina 批量获取行情 ({len(codes)} 只)...")
    df = sina_realtime_quote(codes)
    if df.empty:
        return pd.DataFrame()
    df["代码"] = df["代码"].astype(str).str.zfill(6)
    return df


def _get_all_via_em() -> pd.DataFrame:
    """方案 C: 东方财富 stock_zh_a_spot_em。"""
    df = ak.stock_zh_a_spot_em()
    if "代码" in df.columns:
        df["代码"] = df["代码"].astype(str).str.zfill(6)
    col_map = {
        "最新价": "最新价", "涨跌幅": "涨跌幅",
        "换手率": "换手率", "成交额": "成交额",
        "名称": "名称",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    return df


def get_all_stocks() -> pd.DataFrame:
    """获取全市场实时行情数据（三级降级：AkShare Sina → Sina 批量 → 东方财富）。"""
    cached = get_cache("all_stocks_spot_sina", ttl_minutes=3)
    if cached is not None:
        return pd.DataFrame(cached)

    sources = [
        ("AkShare/Sina", _get_all_via_akshare_sina),
        ("Sina 批量", _get_all_via_sina_batch),
        ("东方财富", _get_all_via_em),
    ]

    for name, func in sources:
        try:
            df = func()
            if not df.empty and len(df) > 100:
                df = filter_stocks(df)
                set_cache("all_stocks_spot_sina", df.to_dict(orient="records"))
                print(f"  ✅ 数据源: {name} ({len(df)} 只)")
                return df
        except Exception as e:
            print(f"  ⚠️ {name} 失败: {e}")

    print("  ❌ 所有数据源均不可用")
    return pd.DataFrame()


def screen_by_basic_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """基于基础行情数据筛选。"""
    result = df.copy()

    change_col = "涨跌幅" if "涨跌幅" in result.columns else "changepercent"
    price_col = "最新价" if "最新价" in result.columns else None

    if "涨跌幅_min" in filters and change_col in result.columns:
        result = result[pd.to_numeric(result[change_col], errors='coerce') >= filters["涨跌幅_min"]]
    if "涨跌幅_max" in filters and change_col in result.columns:
        result = result[pd.to_numeric(result[change_col], errors='coerce') <= filters["涨跌幅_max"]]

    if "换手率_min" in filters and "换手率" in result.columns:
        result = result[pd.to_numeric(result["换手率"], errors='coerce') >= filters["换手率_min"]]
    if "换手率_max" in filters and "换手率" in result.columns:
        result = result[pd.to_numeric(result["换手率"], errors='coerce') <= filters["换手率_max"]]

    if "pe_max" in filters and "市盈率" in result.columns:
        pe = pd.to_numeric(result["市盈率"], errors='coerce')
        result = result[(pe > 0) & (pe <= filters["pe_max"])]

    if price_col and "price_min" in filters:
        result = result[pd.to_numeric(result[price_col], errors='coerce') >= filters["price_min"]]
    if price_col and "price_max" in filters:
        result = result[pd.to_numeric(result[price_col], errors='coerce') <= filters["price_max"]]

    return result.reset_index(drop=True)


def screen_with_technical(df: pd.DataFrame, require_macd_golden: bool = False,
                          require_above_ma: int = None) -> pd.DataFrame:
    """附加技术面筛选（逐票计算，较慢）。"""
    if not require_macd_golden and require_above_ma is None:
        return df

    from technical import calc_macd, calc_ma, _get_hist

    qualified = []
    total = len(df)
    for idx, row in df.iterrows():
        code = row["代码"]
        try:
            hist = _get_hist(code, count=60)
            if hist.empty or len(hist) < 30:
                continue

            passed = True

            if require_macd_golden:
                macd = calc_macd(hist)
                if not macd.get("金叉") and macd.get("趋势") != "多头":
                    passed = False

            if require_above_ma and passed:
                ma = calc_ma(hist, periods=[require_above_ma])
                ma_key = f"MA{require_above_ma}"
                if ma_key in ma.get("均线", {}):
                    if ma["均线"][ma_key]["方向"] != "多头":
                        passed = False

            if passed:
                qualified.append(row)
        except Exception:
            continue

        if (idx + 1) % 20 == 0:
            print(f"  ⏳ 技术面筛选进度: {idx + 1}/{total}")

    if not qualified:
        return pd.DataFrame()
    return pd.DataFrame(qualified).reset_index(drop=True)


def _select_candidates(df: pd.DataFrame, max_candidates: int = 80) -> pd.DataFrame:
    """从基础筛选结果中挑选用于计算的候选集，避免全市场逐票计算过慢。"""
    if df.empty:
        return df
    if "成交额" in df.columns:
        return df.sort_values("成交额", ascending=False).head(max_candidates).reset_index(drop=True)
    change_col = "涨跌幅" if "涨跌幅" in df.columns else "changepercent"
    if change_col in df.columns:
        return df.sort_values(change_col, ascending=False).head(max_candidates).reset_index(drop=True)
    return df.head(max_candidates).reset_index(drop=True)


def run_leader_first_board(count: int = 10) -> pd.DataFrame:
    """龙头首板（基础版）：接近涨停 + 合理换手 + 价格区间。"""
    df = get_all_stocks()
    if df.empty:
        return df
    df = screen_by_basic_filters(df, PRESETS["leader_first_board"]["filters"])
    change_col = "涨跌幅" if "涨跌幅" in df.columns else "changepercent"
    if change_col in df.columns:
        df[change_col] = pd.to_numeric(df[change_col], errors='coerce')
        df = df.sort_values(change_col, ascending=False)
    return df.head(count).reset_index(drop=True)


def run_trend_pullback(count: int = 10) -> pd.DataFrame:
    """趋势强股低吸（基础版）。"""
    df = get_all_stocks()
    if df.empty:
        return df
    df = screen_by_basic_filters(df, PRESETS["trend_pullback"]["filters"])
    df = _select_candidates(df, max_candidates=80)

    from technical import _get_hist, calc_ma, calc_rsi, calc_candlestick

    qualified = []
    total = len(df)
    for idx, row in df.iterrows():
        code = row["代码"]
        try:
            hist = _get_hist(code, count=120)
            if hist.empty or len(hist) < 60:
                continue

            ma = calc_ma(hist, periods=[10, 20, 60])
            rsi = calc_rsi(hist, periods=[6])
            cur = ma.get("当前价", 0)
            ma10 = ma.get("均线", {}).get("MA10", {}).get("值", 0)
            ma20 = ma.get("均线", {}).get("MA20", {}).get("值", 0)
            ma60 = ma.get("均线", {}).get("MA60", {}).get("值", 0)

            if not (cur > ma20 and cur > ma60 and ma20 > ma60):
                continue
            if ma10 <= 0 or abs(cur - ma10) / ma10 > 0.02:
                continue

            rsi6 = rsi.get("RSI6", {}).get("值", 50)
            if not (30 <= rsi6 <= 60):
                continue

            close = hist["收盘"].astype(float)
            pct = close.pct_change() * 100
            if pct.tail(20).max() < 9.5:
                continue

            candles = calc_candlestick(hist)
            if candles is not None:
                bullish = [c for c in candles if c.get("方向") == "看涨"]
                if not bullish:
                    continue

            qualified.append(row)
        except Exception:
            continue

        if (idx + 1) % 20 == 0:
            print(f"  ⏳ 趋势强股筛选进度: {idx + 1}/{total}")

    if not qualified:
        return pd.DataFrame()
    return pd.DataFrame(qualified).head(count).reset_index(drop=True)


def run_ice_reversal(count: int = 10) -> pd.DataFrame:
    """冰点反转（基础版）。"""
    from market_sentiment import get_market_breadth, get_index_status, calc_sentiment_score
    breadth = get_market_breadth()
    indices = get_index_status()
    sentiment = calc_sentiment_score(breadth, indices)
    if sentiment.get("分数", 50) >= 25:
        print("  ⚠️ 当前非冰点情绪，冰点反转策略暂不启用")
        return pd.DataFrame()

    df = get_all_stocks()
    if df.empty:
        return df
    df = screen_by_basic_filters(df, PRESETS["ice_reversal"]["filters"])
    change_col = "涨跌幅" if "涨跌幅" in df.columns else "changepercent"
    if change_col in df.columns:
        df[change_col] = pd.to_numeric(df[change_col], errors='coerce')
        df = df.sort_values(change_col, ascending=True)
    df = _select_candidates(df, max_candidates=80)

    from technical import _get_hist, calc_boll, calc_candlestick

    qualified = []
    total = len(df)
    for idx, row in df.iterrows():
        code = row["代码"]
        try:
            hist = _get_hist(code, count=60)
            if hist.empty or len(hist) < 20:
                continue

            close = hist["收盘"].astype(float)
            vol = hist["成交量"].astype(float)
            if len(close) < 6:
                continue

            pct_5 = (close.iloc[-1] / close.iloc[-6] - 1) * 100
            if pct_5 > -10:
                continue

            if vol.iloc[-2] > 0 and vol.iloc[-1] <= vol.iloc[-2] * 1.3:
                continue

            boll = calc_boll(hist)
            if boll.get("位置百分比", 50) > 30:
                continue

            candles = calc_candlestick(hist)
            if candles is not None:
                bullish = [c for c in candles if c.get("方向") == "看涨"]
                if not bullish:
                    continue

            qualified.append(row)
        except Exception:
            continue

        if (idx + 1) % 20 == 0:
            print(f"  ⏳ 冰点反转筛选进度: {idx + 1}/{total}")

    if not qualified:
        return pd.DataFrame()
    return pd.DataFrame(qualified).head(count).reset_index(drop=True)


def run_preset(preset_name: str, count: int = 10) -> pd.DataFrame:
    """运行预设策略选股。"""
    if preset_name not in PRESETS:
        print(f"  ❌ 不存在的预设: {preset_name}")
        return pd.DataFrame()

    preset = PRESETS[preset_name]
    print(f"  📋 策略: {preset['name']}")
    print(f"  📝 {preset['description']}\n")

    if preset.get("advanced"):
        strategy = preset.get("strategy")
        if strategy == "leader_first_board":
            return run_leader_first_board(count=count)
        if strategy == "trend_pullback":
            return run_trend_pullback(count=count)
        if strategy == "ice_reversal":
            return run_ice_reversal(count=count)

    df = get_all_stocks()
    if df.empty:
        return df
    df = screen_by_basic_filters(df, preset["filters"])

    change_col = "涨跌幅" if "涨跌幅" in df.columns else "changepercent"
    if not df.empty:
        df[change_col] = pd.to_numeric(df[change_col], errors='coerce')
        df = df.sort_values(change_col, ascending=False)

    return df.head(count).reset_index(drop=True)


def run_custom(count: int = 10, pe_max: float = None,
               macd_golden_cross: bool = False,
               above_ma: int = None, **extra_filters) -> pd.DataFrame:
    """运行自定义条件选股。"""
    df = get_all_stocks()
    if df.empty:
        return df

    filters = {}
    if pe_max is not None:
        filters["pe_max"] = pe_max
    filters.update(extra_filters)
    df = screen_by_basic_filters(df, filters)

    if macd_golden_cross or above_ma:
        change_col = "涨跌幅" if "涨跌幅" in df.columns else "changepercent"
        df[change_col] = pd.to_numeric(df[change_col], errors='coerce')
        df = df.sort_values(change_col, ascending=False).head(50)
        df = screen_with_technical(df,
                                   require_macd_golden=macd_golden_cross,
                                   require_above_ma=above_ma)

    change_col = "涨跌幅" if "涨跌幅" in df.columns else "changepercent"
    if not df.empty:
        df[change_col] = pd.to_numeric(df[change_col], errors='coerce')
        df = df.sort_values(change_col, ascending=False)

    return df.head(count).reset_index(drop=True)


# ─── 输出 ────────────────────────────────────────────────────────────────────────

def display_results(df: pd.DataFrame, title: str = "选股结果"):
    """展示选股结果。"""
    print_header(title)
    if df.empty:
        print("  (无符合条件的股票)")
        return

    cols = ["代码", "名称", "最新价", "涨跌幅", "换手率", "成交额"]
    display_cols = [c for c in cols if c in df.columns]
    print_table(df[display_cols], max_rows=20)
    print(f"\n  共找到 {len(df)} 只股票")


def list_presets():
    """列出所有预设策略。"""
    print_header("可用预设策略")
    for key, preset in PRESETS.items():
        print(f"    📌 {key}: {preset['name']}")
        print(f"       {preset['description']}")
        print()


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="A股选股引擎")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    p_pre = sub.add_parser("preset", help="使用预设策略选股")
    p_pre.add_argument("--name", required=True, help="预设策略名称")
    p_pre.add_argument("--count", type=int, default=10)

    p_cus = sub.add_parser("custom", help="自定义条件选股")
    p_cus.add_argument("--pe-max", type=float, default=None)
    p_cus.add_argument("--macd-golden-cross", action="store_true")
    p_cus.add_argument("--above-ma", type=int, default=None)
    p_cus.add_argument("--count", type=int, default=10)

    sub.add_parser("list-presets", help="查看可用预设策略")

    args = parser.parse_args()

    if args.action == "preset":
        df = run_preset(args.name, count=args.count)
        display_results(df, title=f"预设策略: {PRESETS.get(args.name, {}).get('name', args.name)}")
    elif args.action == "custom":
        df = run_custom(
            count=args.count,
            pe_max=args.pe_max,
            macd_golden_cross=args.macd_golden_cross,
            above_ma=args.above_ma,
        )
        display_results(df, title="自定义条件选股结果")
    elif args.action == "list-presets":
        list_presets()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
