"""
Backtesting module — replays historical intraday candles through the
ORB strategy and reports simulated P&L with full Indian transaction cost modeling.

Uses the SAME ORBBreakoutStrategy class as live mode for logic parity.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, time as dt_time
import numpy as np
import pandas as pd

from hermes.config import get_config
from hermes.domain.models import Candle
from hermes.domain.strategy import ORBBreakoutStrategy, ORBConfig
from hermes.domain.costs import CostModel, Side, ChargeBreakdown

logger = logging.getLogger(__name__)


class ORBBacktester:
    """
    Replays candles through ORBBreakoutStrategy and simulates multi-symbol intraday trades.
    Incorporates next-bar open fill execution, itemized Indian transaction charges,
    and sample sufficiency statistics with bootstrap confidence intervals.
    """

    def __init__(
        self,
        cfg: ORBConfig,
        cost_model: CostModel | None = None,
        intrabar_mode: str = "pessimistic",
        max_concurrent_trades: int = 5,
    ) -> None:
        self._cfg = cfg
        self._cost_model = cost_model or CostModel()
        self._intrabar_mode = intrabar_mode
        self._max_concurrent_trades = max_concurrent_trades

        self._strategy = ORBBreakoutStrategy(cfg)
        self._trades: list[dict] = []
        self._active_trades: dict[str, dict] = {}  # symbol -> trade state
        self._pending_entries: dict[str, dict] = {}  # symbol -> pending order for next bar

    def run(self, df_dict: dict[str, pd.DataFrame]) -> dict:
        """
        Run universe backtest on a dictionary of DataFrames: {symbol: df_candles}.
        Concurrently steps through timestamps across symbols.
        """
        logger.info("Running multi-symbol backtest on %d symbols ...", len(df_dict))

        # Merge all symbols into a single timeline sorted by timestamp
        combined_rows = []
        for symbol, df in df_dict.items():
            if df.empty:
                continue
            df_copy = df.copy()
            df_copy["symbol"] = symbol
            combined_rows.append(df_copy)

        if not combined_rows:
            logger.warning("No candle data available for backtest.")
            return {}

        universe_df = pd.concat(combined_rows, ignore_index=True)
        universe_df["timestamp"] = pd.to_datetime(universe_df["timestamp"])
        universe_df.sort_values(by="timestamp", inplace=True)
        universe_df.reset_index(drop=True, inplace=True)

        prev_date: str | None = None

        for _, row in universe_df.iterrows():
            symbol = str(row["symbol"])
            ts: datetime = row["timestamp"]
            timestamp_str = ts.strftime("%Y-%m-%d %H:%M:%S")
            date_str = ts.strftime("%Y-%m-%d")
            time_obj = ts.time()

            # EOD check on date change
            if prev_date is not None and date_str != prev_date:
                self._close_all_active_trades(timestamp_str, "End of Day Exit", row["close"])
                self._pending_entries.clear()
            prev_date = date_str

            candle = Candle(
                symbol=symbol,
                timestamp=timestamp_str,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
            )

            # 1. Execute pending next-bar entry if available
            if symbol in self._pending_entries:
                pending = self._pending_entries.pop(symbol)
                if len(self._active_trades) < self._max_concurrent_trades:
                    # Fill at next bar open with slippage
                    side = Side.BUY if pending["direction"] == "LONG" else Side.SELL
                    fill_price = self._cost_model.apply_slippage(candle.open, side, is_entry=True)
                    
                    # Recompute TP based on actual fill price to preserve RR ratio
                    risk = abs(fill_price - pending["sl"])
                    if pending["direction"] == "LONG":
                        tp = fill_price + (risk * self._cfg.rr_ratio)
                    else:
                        tp = fill_price - (risk * self._cfg.rr_ratio)

                    self._active_trades[symbol] = {
                        "symbol": symbol,
                        "direction": pending["direction"],
                        "entry_time": timestamp_str,
                        "entry_price": fill_price,
                        "sl": pending["sl"],
                        "tp": round(tp, 2),
                        "reason": pending["reason"],
                    }

            # 2. Manage active trade for symbol
            if symbol in self._active_trades:
                self._manage_trade(symbol, candle, time_obj)
            else:
                # 3. Process candle for new signals if under trade capacity limit
                if len(self._active_trades) + len(self._pending_entries) < self._max_concurrent_trades:
                    sig = self._strategy.on_candle(candle)
                    if sig and sig.direction in ("LONG", "SHORT"):
                        self._pending_entries[symbol] = {
                            "direction": sig.direction,
                            "sl": sig.sl,
                            "reason": sig.reason,
                        }

        # Force-close any open trades at end of dataset
        self._close_all_active_trades(prev_date or "End of Data", "End of Data Exit", 0.0)

        metrics = self._calculate_metrics()
        self._print_summary(metrics)
        self._export_results()
        return metrics

    def _manage_trade(self, symbol: str, candle: Candle, time_obj: dt_time) -> None:
        tr = self._active_trades[symbol]
        exit_price: float | None = None
        exit_reason = ""

        is_long = tr["direction"] == "LONG"

        sl_hit = (candle.low <= tr["sl"]) if is_long else (candle.high >= tr["sl"])
        tp_hit = (candle.high >= tr["tp"]) if is_long else (candle.low <= tr["tp"])

        if sl_hit and tp_hit:
            # Intrabar collision: pessimistic assumes SL hit first
            if self._intrabar_mode == "pessimistic":
                exit_price, exit_reason = tr["sl"], "SL Hit (Pessimistic)"
            else:
                exit_price, exit_reason = tr["tp"], "TP Hit (Optimistic)"
        elif sl_hit:
            exit_price, exit_reason = tr["sl"], "SL Hit"
        elif tp_hit:
            exit_price, exit_reason = tr["tp"], "TP Hit"
        elif time_obj >= self._cfg.exit_time:
            exit_price, exit_reason = candle.close, "Time Exit"

        if exit_price is not None:
            self._close_trade(symbol, exit_price, candle.timestamp, exit_reason)

    def _close_trade(self, symbol: str, exit_price: float, exit_time: str, exit_reason: str) -> None:
        tr = self._active_trades.pop(symbol, None)
        if not tr:
            return

        entry_side = Side.BUY if tr["direction"] == "LONG" else Side.SELL
        exit_side = Side.SELL if entry_side == Side.BUY else Side.BUY

        # Apply exit slippage
        realized_exit_price = self._cost_model.apply_slippage(exit_price, exit_side, is_entry=False)
        tr["exit_time"] = exit_time
        tr["exit_price"] = realized_exit_price
        tr["exit_reason"] = exit_reason

        # Quantity assuming ₹100,000 capital per trade
        trade_capital = 100_000.0
        qty = max(1, int(trade_capital / tr["entry_price"]))
        tr["quantity"] = qty

        # Compute costs & itemized charges
        entry_ch, exit_ch, gross_pnl, net_pnl = self._cost_model.round_trip(
            tr["entry_price"], realized_exit_price, qty, entry_side
        )

        tr["gross_pnl"] = gross_pnl
        tr["total_charges"] = entry_ch.total_charges + exit_ch.total_charges
        tr["net_pnl"] = net_pnl

        # Expectancy in R
        risk_per_share = abs(tr["entry_price"] - tr["sl"])
        total_risk_rs = max(1.0, risk_per_share * qty)
        tr["net_r"] = round(net_pnl / total_risk_rs, 3)

        self._trades.append(tr)

    def _close_all_active_trades(self, timestamp: str, reason: str, fallback_price: float) -> None:
        active_symbols = list(self._active_trades.keys())
        for sym in active_symbols:
            px = self._active_trades[sym].get("sl", fallback_price)
            self._close_trade(sym, px, timestamp, reason)

    def _calculate_metrics(self) -> dict:
        if not self._trades:
            return {"total_trades": 0, "sample_sufficient": False}

        df_t = pd.DataFrame(self._trades)
        total = len(df_t)
        net_pnls = df_t["net_pnl"].values
        net_r_vals = df_t["net_r"].values

        wins = (net_pnls > 0).sum()
        win_rate = (wins / total) * 100

        gross_gains = df_t[df_t["gross_pnl"] > 0]["gross_pnl"].sum()
        gross_losses = abs(df_t[df_t["gross_pnl"] < 0]["gross_pnl"].sum())
        profit_factor = round(gross_gains / gross_losses, 2) if gross_losses > 0 else 999.0

        mean_net_r = float(np.mean(net_r_vals))

        # Bootstrap 95% Confidence Interval for Net Expectancy R
        np.random.seed(42)
        boot_means = [np.mean(np.random.choice(net_r_vals, size=total, replace=True)) for _ in range(1000)]
        ci_lower = float(np.percentile(boot_means, 2.5))
        ci_upper = float(np.percentile(boot_means, 97.5))

        # Sample sufficiency check: need at least 50 trades and CI lower > 0
        sample_sufficient = (total >= 50) and (ci_lower > 0.0)

        # Max Drawdown %
        cum_pnl = np.cumsum(net_pnls)
        peak = np.maximum.accumulate(cum_pnl)
        drawdown = peak - cum_pnl
        max_dd = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

        return {
            "total_trades": total,
            "win_rate_pct": round(win_rate, 2),
            "total_net_pnl": round(float(np.sum(net_pnls)), 2),
            "net_expectancy_r": round(mean_net_r, 3),
            "ci_95_lower_r": round(ci_lower, 3),
            "ci_95_upper_r": round(ci_upper, 3),
            "profit_factor": profit_factor,
            "max_drawdown_rs": round(max_dd, 2),
            "sample_sufficient": sample_sufficient,
        }

    def _print_summary(self, metrics: dict) -> None:
        print("\n" + "=" * 55)
        print("           ORB BACKTEST PERFORMANCE REPORT           ")
        print("=" * 55)

        if not metrics or metrics.get("total_trades", 0) == 0:
            print("  No trades taken during the backtest period.")
            print("=" * 55 + "\n")
            return

        print(f"  Total Trades:         {metrics['total_trades']}")
        print(f"  Win Rate:             {metrics['win_rate_pct']}%")
        print(f"  Net Expectancy (R):   {metrics['net_expectancy_r']} R / trade")
        print(f"  95% Bootstrap CI (R): [{metrics['ci_95_lower_r']} R, {metrics['ci_95_upper_r']} R]")
        print(f"  Profit Factor:        {metrics['profit_factor']}")
        print(f"  Max Drawdown:        ₹{metrics['max_drawdown_rs']}")
        print(f"  Total Net P&L:       ₹{metrics['total_net_pnl']}")
        print("-" * 55)

        if metrics["sample_sufficient"]:
            print("  STATUS: [GREEN] Statistical edge confirmed (CI > 0, N >= 50).")
        elif metrics["ci_95_lower_r"] <= 0 < metrics["ci_95_upper_r"]:
            print("  STATUS: [AMBER] Inconclusive. Need more historical data.")
        else:
            print("  STATUS: [RED] Negative expectancy net-of-costs.")

        print("=" * 55 + "\n")

    def _export_results(self) -> None:
        if self._trades:
            df_t = pd.DataFrame(self._trades)
            df_t.to_csv("backtest_results.csv", index=False)
            logger.info("Results exported to backtest_results.csv")
