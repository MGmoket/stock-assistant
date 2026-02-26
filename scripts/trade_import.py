"""
交割单导入模块 — A股交易助手
支持东方财富、通达信交割单 CSV 导入，自动同步到持仓管理。
"""

import argparse
import csv
import sys
from datetime import datetime

import pandas as pd

from utils import (
    normalize_symbol, format_price,
    print_header, print_section, print_kv, print_table,
)


# ─── 交割单格式定义 ──────────────────────────────────────────────────────────────

# 东方财富交割单列名映射（常见格式）
EASTMONEY_COLS = {
    "成交日期": "date",
    "证券代码": "code",
    "证券名称": "name",
    "买卖标志": "action",      # 买入 / 卖出
    "成交价格": "price",
    "成交数量": "quantity",
    "成交金额": "amount",
    "手续费": "commission",
    "印花税": "stamp_tax",
    "过户费": "transfer_fee",
    "发生金额": "net_amount",
    "备注": "note",
}

# 通达信交割单列名映射
TDX_COLS = {
    "成交日期": "date",
    "成交时间": "time",
    "证券代码": "code",
    "证券名称": "name",
    "买卖标志": "action",
    "成交价格": "price",
    "成交数量": "quantity",
    "成交金额": "amount",
    "手续费": "commission",
    "印花税": "stamp_tax",
    "其他费": "other_fee",
}

# 操作方向关键词
BUY_KEYWORDS = ["买入", "证券买入", "买", "融资买入", "担保品买入"]
SELL_KEYWORDS = ["卖出", "证券卖出", "卖", "融资卖出", "担保品卖出"]


# ─── 解析逻辑 ────────────────────────────────────────────────────────────────────

def _detect_encoding(filepath: str) -> str:
    """检测文件编码。"""
    for enc in ["utf-8", "gbk", "gb2312", "utf-8-sig", "gb18030"]:
        try:
            with open(filepath, "r", encoding=enc) as f:
                f.read(1000)
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return "utf-8"


def _normalize_action(action_str: str) -> str:
    """标准化买卖方向。"""
    action_str = str(action_str).strip()
    for kw in BUY_KEYWORDS:
        if kw in action_str:
            return "买入"
    for kw in SELL_KEYWORDS:
        if kw in action_str:
            return "卖出"
    return action_str


def parse_csv(filepath: str, fmt: str = "eastmoney") -> pd.DataFrame:
    """
    解析交割单 CSV 文件。
    fmt: eastmoney (东方财富) / tdx (通达信)
    返回标准化的 DataFrame。
    """
    col_map = EASTMONEY_COLS if fmt == "eastmoney" else TDX_COLS
    encoding = _detect_encoding(filepath)

    df = pd.read_csv(filepath, encoding=encoding, dtype=str)
    df.columns = df.columns.str.strip()

    # 列名映射
    rename_map = {}
    for cn, en in col_map.items():
        if cn in df.columns:
            rename_map[cn] = en
    df = df.rename(columns=rename_map)

    # 必需列检查
    required = ["code", "action", "price", "quantity"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        # 尝试模糊匹配
        for col in df.columns:
            col_lower = col.lower().strip()
            if "代码" in col and "code" in missing:
                df = df.rename(columns={col: "code"})
                missing.remove("code")
            elif ("买卖" in col or "操作" in col) and "action" in missing:
                df = df.rename(columns={col: "action"})
                missing.remove("action")
            elif "价格" in col and "price" in missing:
                df = df.rename(columns={col: "price"})
                missing.remove("price")
            elif "数量" in col and "quantity" in missing:
                df = df.rename(columns={col: "quantity"})
                missing.remove("quantity")

    if missing:
        raise ValueError(f"交割单缺少必需列: {missing}\n现有列: {list(df.columns)}")

    # 数据清洗
    df["code"] = df["code"].apply(lambda x: normalize_symbol(str(x).strip()))
    df["action"] = df["action"].apply(_normalize_action)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype(int)

    # 过滤无效行
    df = df[df["action"].isin(["买入", "卖出"])]
    df = df[df["price"] > 0]
    df = df[df["quantity"] > 0]

    # 可选列
    for col in ["amount", "commission", "stamp_tax", "transfer_fee", "other_fee"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "date" in df.columns:
        df["date"] = df["date"].astype(str).str.strip()
    else:
        df["date"] = datetime.now().strftime("%Y-%m-%d")

    return df.reset_index(drop=True)


def preview_import(filepath: str, fmt: str = "eastmoney"):
    """预览交割单内容（不写入）。"""
    df = parse_csv(filepath, fmt=fmt)
    print_header(f"交割单预览 ({len(df)} 条记录)")

    buys = df[df["action"] == "买入"]
    sells = df[df["action"] == "卖出"]
    print_kv("买入记录", f"{len(buys)} 条")
    print_kv("卖出记录", f"{len(sells)} 条")

    if "amount" in df.columns:
        total_buy = buys["amount"].sum()
        total_sell = sells["amount"].sum()
        print_kv("买入总额", format_price(total_buy))
        print_kv("卖出总额", format_price(total_sell))

    print_section("详细记录")
    cols = ["date", "code", "action", "price", "quantity"]
    if "name" in df.columns:
        cols.insert(2, "name")
    if "amount" in df.columns:
        cols.append("amount")
    display_cols = [c for c in cols if c in df.columns]
    print_table(df[display_cols], max_rows=30)

    return df


def do_import(filepath: str, fmt: str = "eastmoney"):
    """导入交割单到持仓管理。"""
    from portfolio import record_buy, record_sell, _load_portfolio

    df = parse_csv(filepath, fmt=fmt)
    if df.empty:
        print("  ❌ 交割单为空或格式不匹配")
        return

    # 去重检测
    portfolio = _load_portfolio()
    existing_times = {h.get("time", "") for h in portfolio.get("history", [])}

    imported = 0
    skipped = 0
    for _, row in df.iterrows():
        # 简单去重：用日期+代码+价格+数量生成唯一标识
        dedup_key = f"{row.get('date', '')}-{row['code']}-{row['price']}-{row['quantity']}"
        if dedup_key in existing_times:
            skipped += 1
            continue

        note = f"交割单导入 {row.get('date', '')}"
        if row["action"] == "买入":
            record_buy(row["code"], row["price"], row["quantity"], note=note)
        else:
            record_sell(row["code"], row["price"], row["quantity"], note=note)
        imported += 1

    print(f"\n  ✅ 导入完成: {imported} 条成功, {skipped} 条跳过(重复)")


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="交割单导入")
    sub = parser.add_subparsers(dest="action", help="操作类型")

    p_imp = sub.add_parser("import", help="导入交割单")
    p_imp.add_argument("--file", required=True, help="CSV 文件路径")
    p_imp.add_argument("--format", default="eastmoney",
                       choices=["eastmoney", "tdx"], help="交割单格式")

    p_pre = sub.add_parser("preview", help="预览交割单")
    p_pre.add_argument("--file", required=True, help="CSV 文件路径")
    p_pre.add_argument("--format", default="eastmoney",
                       choices=["eastmoney", "tdx"], help="交割单格式")

    args = parser.parse_args()

    if args.action == "import":
        do_import(args.file, fmt=args.format)
    elif args.action == "preview":
        preview_import(args.file, fmt=args.format)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
