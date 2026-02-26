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
}


# ─── 选股逻辑 ────────────────────────────────────────────────────────────────────

def get_all_stocks() -> pd.DataFrame:
    """获取全市场实时行情数据（Sina 接口，已过滤 ST 和非主板）。"""
    cached = get_cache("all_stocks_spot_sina", ttl_minutes=3)
    if cached is not None:
        return pd.DataFrame(cached)

    try:
        df = ak.stock_zh_a_spot()  # Sina 接口
        df["代码"] = df["代码"].astype(str).str.zfill(6)
        # 统一列名
        col_map = {
            "trade": "最新价", "changepercent": "涨跌幅",
            "open": "今开", "high": "最高", "low": "最低",
            "volume": "成交量", "amount": "成交额",
            "turnoverratio": "换手率", "settlement": "昨收",
            "name": "名称",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df = filter_stocks(df)
        set_cache("all_stocks_spot_sina", df.to_dict(orient="records"))
        return df
    except Exception as e:
        print(f"  ⚠️ 获取全市场数据失败: {e}")
        return pd.DataFrame()


def screen_by_basic_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """基于基础行情数据筛选。"""
    result = df.copy()

    change_col = "涨跌幅" if "涨跌幅" in result.columns else "changepercent"

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


def run_preset(preset_name: str, count: int = 10) -> pd.DataFrame:
    """运行预设策略选股。"""
    if preset_name not in PRESETS:
        print(f"  ❌ 不存在的预设: {preset_name}")
        return pd.DataFrame()

    preset = PRESETS[preset_name]
    print(f"  📋 策略: {preset['name']}")
    print(f"  📝 {preset['description']}\n")

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
