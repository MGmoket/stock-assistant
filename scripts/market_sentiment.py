"""
市场情绪面板模块 — A股交易助手
提供涨跌停统计、市场赚钱效应、情绪周期判断等功能。
"""

import argparse

import akshare as ak
import pandas as pd

from utils import (
    format_number, format_percent, format_price,
    print_header, print_section, print_kv,
    get_cache, set_cache,
    normalize_symbol, is_st, _sina_symbol,
)


# ─── 涨跌停辅助 ────────────────────────────────────────────────────────────────

def _limit_up_pct(code: str, name: str = "") -> float:
    """按板块估算涨跌停幅度（降级版，近似口径）。"""
    code = normalize_symbol(code)
    if is_st(name):
        return 5.0
    if code.startswith(("300", "301", "688", "689")):
        return 20.0
    if code.startswith(("8", "4")):
        return 30.0
    return 10.0


def _limit_threshold(code: str, name: str = "", tolerance: float = 0.2) -> float:
    """涨跌停阈值，加入容错空间。"""
    return _limit_up_pct(code, name) - tolerance


def _is_limit_up(pct: float, code: str, name: str = "") -> bool:
    if pct is None or pd.isna(pct):
        return False
    return pct >= _limit_threshold(code, name)


def _is_limit_down(pct: float, code: str, name: str = "") -> bool:
    if pct is None or pd.isna(pct):
        return False
    return pct <= -_limit_threshold(code, name)


def _calc_limit_up_streak(code: str, name: str, lookback_days: int = 10) -> int:
    """计算单只股票连续涨停天数（从最新交易日向前）。"""
    try:
        sina_code = _sina_symbol(code)
        df = ak.stock_zh_a_daily(symbol=sina_code, adjust="qfq")
        if df is None or df.empty or len(df) < 2:
            return 0
        df = df.tail(lookback_days + 1).reset_index(drop=True)
        if "close" not in df.columns:
            return 0
        close = pd.to_numeric(df["close"], errors="coerce")
        pct = close.pct_change() * 100
        threshold = _limit_threshold(code, name)
        count = 0
        for i in range(len(pct) - 1, 0, -1):
            if pct.iloc[i] >= threshold:
                count += 1
            else:
                break
        return count
    except Exception:
        return 0


def get_limit_up_height(lookback_days: int = 10, spot_df: pd.DataFrame | None = None) -> int:
    """
    计算全市场连板高度（降级版）：
    - 仅统计今日涨停股
    - 用日线连续涨停近似
    """
    cached = get_cache("limit_up_height", ttl_minutes=10, lookback_days=lookback_days)
    if cached is not None:
        return cached

    try:
        df = spot_df if spot_df is not None else ak.stock_zh_a_spot()
        if df is None or df.empty:
            return 0
        change_col = None
        for c in ["changepercent", "涨跌幅", "change_percent"]:
            if c in df.columns:
                change_col = c
                break
        if change_col is None:
            return 0
        df[change_col] = pd.to_numeric(df[change_col], errors="coerce")

        max_height = 0
        if "名称" not in df.columns:
            df["名称"] = ""
        if "代码" not in df.columns:
            return 0
        for code, name, pct in df[["代码", "名称", change_col]].itertuples(index=False, name=None):
            if not code:
                continue
            if _is_limit_up(pct, code, name):
                height = _calc_limit_up_streak(code, name, lookback_days=lookback_days)
                if height > max_height:
                    max_height = height
        set_cache("limit_up_height", max_height, lookback_days=lookback_days)
        return max_height
    except Exception:
        return 0


# ─── 市场情绪指标 ────────────────────────────────────────────────────────────────

def get_market_breadth() -> dict:
    """获取市场宽度（涨跌家数、涨跌比）。"""
    cached = get_cache("market_breadth", ttl_minutes=3)
    if cached:
        return cached

    try:
        df = ak.stock_zh_a_spot()
        # Sina 接口列名可能是 changepercent 或 涨跌幅
        change_col = None
        for c in ["changepercent", "涨跌幅", "change_percent"]:
            if c in df.columns:
                change_col = c
                break
        if change_col is None:
            print(f"  ⚠️ 无法识别涨跌幅列，现有列: {list(df.columns)[:10]}")
            return {}
        df[change_col] = pd.to_numeric(df[change_col], errors="coerce")

        total = len(df)
        up_count = len(df[df[change_col] > 0])
        down_count = len(df[df[change_col] < 0])
        flat_count = total - up_count - down_count
        limit_up = 0
        limit_down = 0
        if "名称" not in df.columns:
            df["名称"] = ""
        for code, name, pct in df[["代码", "名称", change_col]].itertuples(index=False, name=None):
            if _is_limit_up(pct, code, name):
                limit_up += 1
            if _is_limit_down(pct, code, name):
                limit_down += 1

        breadth = up_count / total * 100 if total > 0 else 50

        limit_up_height = get_limit_up_height(lookback_days=10, spot_df=df)

        result = {
            "总数": total,
            "上涨": up_count,
            "下跌": down_count,
            "平盘": flat_count,
            "涨停": limit_up,
            "跌停": limit_down,
            "连板高度": limit_up_height,
            "涨跌比": round(up_count / max(down_count, 1), 2),
            "赚钱效应": round(breadth, 1),
        }
        set_cache("market_breadth", result)
        return result
    except Exception as e:
        print(f"  ⚠️ 获取市场宽度失败: {e}")
        return {}


def get_index_status() -> list:
    """获取主要指数行情。"""
    from utils import sina_realtime_quote
    codes = ["000001", "399001", "399006", "000688"]
    names = {
        "000001": "上证指数", "399001": "深证成指",
        "399006": "创业板指", "000688": "科创50",
    }
    try:
        df = sina_realtime_quote(codes)
        result = []
        for _, row in df.iterrows():
            code = row.get("代码", "")
            result.append({
                "名称": names.get(code, code),
                "代码": code,
                "最新价": row.get("最新价", 0),
                "涨跌幅": row.get("涨跌幅", 0),
            })
        return result
    except Exception:
        return []


def get_sector_hot() -> pd.DataFrame:
    """获取板块涨幅排行。"""
    try:
        # 尝试 Sina 板块接口（避开 push2）
        df = ak.stock_board_industry_summary_ths()
        if df.empty:
            return df
        col_map = {"板块名称": "板块", "涨跌幅": "涨跌幅"}
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        if "涨跌幅" in df.columns:
            df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce")
            df = df.sort_values("涨跌幅", ascending=False)
        return df.head(10)
    except Exception:
        try:
            # 备用：东方财富概念板
            df = ak.stock_board_concept_name_em()
            if not df.empty:
                col_map = {"板块名称": "板块", "涨跌幅": "涨跌幅"}
                df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
                if "涨跌幅" in df.columns:
                    df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce")
                    df = df.sort_values("涨跌幅", ascending=False)
                return df.head(10)
        except Exception as e:
            print(f"  ⚠️ 获取板块数据失败: {e}")
        return pd.DataFrame()


def calc_sentiment_score(breadth: dict, indices: list) -> dict:
    """
    综合情绪评分（0-100）。
    0-20: 冰点   20-40: 退潮   40-60: 中性
    60-80: 修复   80-100: 亢奋
    """
    score = 50  # 基准

    # 赚钱效应权重 40%
    money_effect = breadth.get("赚钱效应", 50)
    if money_effect > 70:
        score += 20
    elif money_effect > 55:
        score += 10
    elif money_effect < 30:
        score -= 20
    elif money_effect < 45:
        score -= 10

    # 涨跌比权重 20%
    ratio = breadth.get("涨跌比", 1)
    if ratio > 3:
        score += 15
    elif ratio > 1.5:
        score += 8
    elif ratio < 0.3:
        score -= 15
    elif ratio < 0.7:
        score -= 8

    # 涨停数权重 20%
    limit_up = breadth.get("涨停", 0)
    if limit_up > 80:
        score += 10
    elif limit_up > 30:
        score += 5
    elif limit_up < 5:
        score -= 10

    # 跌停数（负面）
    limit_down = breadth.get("跌停", 0)
    if limit_down > 30:
        score -= 10
    elif limit_down > 10:
        score -= 5

    # 连板高度（短线活跃度）
    height = breadth.get("连板高度", 0)
    if height >= 6:
        score += 10
    elif height >= 4:
        score += 5
    elif height <= 2:
        score -= 5

    # 指数涨跌 20%
    if indices:
        avg_change = sum(float(idx.get("涨跌幅", 0)) for idx in indices) / len(indices)
        if avg_change > 1:
            score += 10
        elif avg_change > 0:
            score += 5
        elif avg_change < -1:
            score -= 10
        elif avg_change < 0:
            score -= 5

    score = max(0, min(100, score))

    if score >= 80:
        level = "🔥 亢奋"
        advice = "注意追高风险，适当减仓"
        position_pct = 50
    elif score >= 60:
        level = "🟢 修复"
        advice = "适当参与，控制仓位"
        position_pct = 60
    elif score >= 40:
        level = "⚪ 中性"
        advice = "精选个股，半仓操作"
        position_pct = 50
    elif score >= 20:
        level = "🟡 退潮"
        advice = "谨慎操作，轻仓观望"
        position_pct = 30
    else:
        level = "❄️ 冰点"
        advice = "耐心等待，可少量试探"
        position_pct = 20

    return {
        "分数": score,
        "级别": level,
        "建议": advice,
        "建议仓位": position_pct,
    }


# ─── 输出 ────────────────────────────────────────────────────────────────────────

def display_dashboard():
    """展示市场情绪面板。"""
    print_header("📊 市场情绪面板")

    # 主要指数
    indices = get_index_status()
    if indices:
        print_section("主要指数")
        for idx in indices:
            emoji = "📈" if float(idx["涨跌幅"]) >= 0 else "📉"
            print(f"    {emoji} {idx['名称']}: {format_price(idx['最新价'])} ({format_percent(idx['涨跌幅'])})")

    # 市场宽度
    breadth = get_market_breadth()
    if breadth:
        print_section("市场宽度")
        print_kv("上涨", f"{breadth['上涨']} 家")
        print_kv("下跌", f"{breadth['下跌']} 家")
        print_kv("平盘", f"{breadth['平盘']} 家")
        print_kv("涨停", f"🔴 {breadth['涨停']} 家")
        print_kv("跌停", f"🟢 {breadth['跌停']} 家")
        print_kv("连板高度", f"{breadth['连板高度']} 板")
        print_kv("涨跌比", f"{breadth['涨跌比']}")
        print_kv("赚钱效应", f"{breadth['赚钱效应']}%")

    # 情绪评分
    sentiment = calc_sentiment_score(breadth, indices)
    print_section("综合情绪")
    print_kv("情绪评分", f"{sentiment['分数']}")
    print_kv("情绪级别", sentiment["级别"])
    print_kv("操作建议", sentiment["建议"])
    print_kv("建议仓位", f"{sentiment['建议仓位']}%")

    # 热门板块
    hot = get_sector_hot()
    if not hot.empty:
        print_section("板块涨幅 Top 10")
        cols = ["板块", "涨跌幅"]
        display_cols = [c for c in cols if c in hot.columns]
        if display_cols:
            for _, row in hot.iterrows():
                pct = row.get("涨跌幅", 0)
                emoji = "🟢" if pct >= 0 else "🔴"
                print(f"    {emoji} {row.get('板块', '')}: {format_percent(pct)}")


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="市场情绪面板")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    sub.add_parser("dashboard", help="展示市场情绪面板")
    sub.add_parser("breadth", help="仅查看市场宽度")
    sub.add_parser("sentiment", help="仅查看情绪评分")

    args = parser.parse_args()

    if args.action == "dashboard":
        display_dashboard()
    elif args.action == "breadth":
        breadth = get_market_breadth()
        print_header("市场宽度")
        if breadth:
            for k, v in breadth.items():
                print_kv(k, str(v))
    elif args.action == "sentiment":
        breadth = get_market_breadth()
        indices = get_index_status()
        s = calc_sentiment_score(breadth, indices)
        print_header("情绪评分")
        print_kv("评分", f"{s['分数']}")
        print_kv("级别", s["级别"])
        print_kv("建议", s["建议"])
        print_kv("仓位", f"{s['建议仓位']}%")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
