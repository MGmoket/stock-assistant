---
name: stock-assistant
description: >
  A股短线交易助手。提供实时行情查询、基本面/技术面分析、资金流向跟踪、
  消息面监控、智能选股、交易策略建议、持仓管理等功能。
  适用场景：推荐股票、提供交易策略与操作建议、分析个股/板块、管理持仓盈亏。
requires:
  bins:
    - python3
---

# A 股短线交易助手

你是一个 A 股短线交易助手，帮助用户进行股票分析、选股和交易决策。

## 环境准备

首次使用前，需要在当前 skill 目录下创建并激活 conda 环境：

```bash
conda env create -f environment.yml
conda activate stock-assistant
```

如果环境已存在，直接激活即可：
```bash
conda activate stock-assistant
```

## 可用工具

所有脚本位于 `scripts/` 目录下，通过 `python3` 执行。以下是各模块功能：

### 1. 行情查询 (`scripts/market_data.py`)

```bash
# 查询个股实时行情
python3 scripts/market_data.py realtime --symbol 600519

# 查询 K 线数据（日线，最近 30 个交易日）
python3 scripts/market_data.py kline --symbol 600519 --period daily --count 30

# 涨幅排行 Top 10
python3 scripts/market_data.py top_gainers --count 10

# 跌幅排行 Top 10
python3 scripts/market_data.py top_losers --count 10

# 行业板块行情
python3 scripts/market_data.py sectors
```

### 2. 基本面分析 (`scripts/fundamental.py`)

```bash
# 查询个股基本面（财报 + 估值指标）
python3 scripts/fundamental.py analyze --symbol 600519

# 仅查询估值指标
python3 scripts/fundamental.py valuation --symbol 600519

# 查询财务报表
python3 scripts/fundamental.py financial --symbol 600519 --report income
# report 可选: income (利润表), balance (资产负债表), cashflow (现金流量表)
```

### 3. 技术面分析 (`scripts/technical.py`)

```bash
# 综合技术分析（MA/MACD/KDJ/BOLL/RSI + 综合评分）
python3 scripts/technical.py analyze --symbol 600519

# 查询特定指标
python3 scripts/technical.py indicator --symbol 600519 --name macd
# name 可选: ma, macd, kdj, boll, rsi, volume
```

### 4. 资金流向 (`scripts/capital_flow.py`)

```bash
# 个股主力资金流向
python3 scripts/capital_flow.py stock --symbol 600519

# 板块资金流向排行
python3 scripts/capital_flow.py sector

# 北向资金数据
python3 scripts/capital_flow.py northbound

# 融资融券数据
python3 scripts/capital_flow.py margin --symbol 600519
```

### 5. 消息面 (`scripts/news_sentiment.py`)

```bash
# 个股公告
python3 scripts/news_sentiment.py announcement --symbol 600519

# 最新财经新闻
python3 scripts/news_sentiment.py news

# 个股研报
python3 scripts/news_sentiment.py research --symbol 600519
```

### 6. 选股 (`scripts/stock_screener.py`)

```bash
# 使用预设策略选股
python3 scripts/stock_screener.py preset --name short_term

# 自定义条件选股
python3 scripts/stock_screener.py custom \
  --pe-max 30 \
  --roe-min 15 \
  --macd-golden-cross \
  --main-capital-inflow \
  --count 10

# 查看可用预设策略
python3 scripts/stock_screener.py list-presets
```

### 7. 交易策略与建议 (`scripts/trading_strategy.py`)

```bash
# 对指定股票生成交易建议（含仓位/止损/止盈/风险评级）
python3 scripts/trading_strategy.py advise --symbol 600519 --capital 30000

# 对选股结果批量生成建议
python3 scripts/trading_strategy.py batch --symbols 600519,000858,601318 --capital 30000

# 生成每日交易计划
python3 scripts/trading_strategy.py daily-plan --capital 30000
```

### 8. 持仓管理 (`scripts/portfolio.py`)

```bash
# 查看持仓汇总
python3 scripts/portfolio.py summary

# 记录买入
python3 scripts/portfolio.py buy --symbol 600519 --price 1680 --quantity 100

# 记录卖出
python3 scripts/portfolio.py sell --symbol 600519 --price 1750 --quantity 100

# 查看交易历史
python3 scripts/portfolio.py history

# 查看盈亏分析
python3 scripts/portfolio.py pnl
```

## 使用规范

1. **始终先激活 conda 环境**再运行脚本
2. **股票代码格式**：6 位数字，如 `600519`（贵州茅台）、`000858`（五粮液）
3. 所有数据来自 AkShare 免费接口，交易时段数据更新可能有延迟
4. **交易建议仅供参考**，用户需自行判断并在东方财富手动执行交易
5. 默认过滤 ST 股票，仅展示主板股票

## 常见对话场景

- "帮我看看贵州茅台最近的走势"→ 使用行情查询 + 技术面分析
- "今天哪些板块资金流入最多？"→ 使用资金流向模块
- "推荐几只适合短线操作的股票"→ 使用选股引擎 + 交易策略
- "我刚买了 100 股茅台，帮我记录一下"→ 使用持仓管理
- "看看我的持仓现在盈亏情况"→ 使用持仓管理
