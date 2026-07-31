# Pre-Registered Out-of-Sample Strategy Research Protocol

**Project:** Autonomous Trading Agent (Hermes / Gemini Stock Suggestions)  
**Date:** July 2026  
**Status:** Active  

This protocol governs the backtesting, parameter tuning, and evaluation of trading strategies (specifically Intraday ORB and Screener Breakouts) to prevent overfitting and ensure real-world statistical edge before paper/live deployment.

---

## 1. Data Split (Fixed in Advance)

Historical data stored in `CandleCache` (`data/candles/`) is strictly partitioned:

- **In-Sample / Training Set (65%):** Used for strategy parameter exploration, indicator tuning, and cost sensitivity analysis.
- **Out-of-Sample / Holdout Set (35%):** **Sealed until final validation.**

> [!CAUTION]
> The Holdout Set must be evaluated **exactly ONCE**. Retuning parameters after inspecting holdout results invalidates the holdout and requires accumulating newly recorded live history.

---

## 2. Parameter Grid Definition

The following parameter search space is pre-registered prior to running optimization:

| Parameter | Allowed Range / Values | Step / Default |
|-----------|------------------------|----------------|
| ORB Window | 15 min, 30 min | 15 min |
| Min Volume Threshold | 10,000, 25,000, 50,000 | 10,000 |
| Risk-Reward Ratio (RR) | 1.0, 1.5, 2.0 | 1.0 |
| Max Daily Trades | 3, 4, 5 | 5 |
| Intrabar Exit Assumption | Pessimistic (SL checked first) | Pessimistic |

Total parameter combinations: **18**.

---

## 3. Mandatory Research Log (`research_log.csv`)

Every optimization run must append a row to `docs/research_log.csv` capturing:

- `timestamp`: Run datetime (IST)
- `parameters`: JSON string of parameters evaluated
- `dataset_span`: In-sample vs Out-of-sample date range
- `total_trades`: Number of simulated trades
- `win_rate_pct`: Realized win percentage
- `gross_expectancy_r`: Gross profit/loss in R per trade
- `net_expectancy_r`: Net-of-cost profit/loss in R per trade
- `profit_factor`: Gross Profits / Gross Losses
- `max_drawdown_pct`: Peak-to-trough equity drawdown
- `bootstrap_ci_95`: 95% Confidence Interval of net expectancy

---

## 4. Exit Criteria & Decision Gate

The out-of-sample holdout test is deemed **SUCCESSFUL** only if:

1. **Net Expectancy > 0.05R** per trade (after full Indian transaction charges & slippage).
2. **Bootstrap 95% Confidence Interval** excludes zero (statistically significant edge).
3. **Sample Size:** Minimum 100 out-of-sample trades recorded.
