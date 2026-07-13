"""
Backtesting module — replays historical intraday candles through the
ORB strategy and reports simulated P&L.

Uses the SAME ORBBreakoutStrategy class as live mode for logic parity.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, time as dt_time

import pandas as pd

from config import get_config
from models import Candle
from strategy import ORBBreakoutStrategy, ORBConfig

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Historical Data Loader
# ═══════════════════════════════════════════════════════════════════════

class HistoricalDataLoader:
    """Fetches intraday 1-min candles from the DhanHQ REST API (v2)."""

    def __init__(self, client_id: str, access_token: str) -> None:
        from dhanhq import dhanhq, DhanContext  # lazy import
        context = DhanContext(client_id, access_token)
        self._dhan = dhanhq(context)

    def fetch_intraday_data(
        self,
        security_id: str,
        from_date: str,
        to_date: str,
    ) -> pd.DataFrame:
        """
        Fetch 1-minute OHLCV candles.

        Parameters
        ----------
        security_id : NSE security ID (e.g. "11536")
        from_date, to_date : "YYYY-MM-DD"

        Returns
        -------
        DataFrame with columns: timestamp, open, high, low, close, volume
        """
        logger.info("Fetching data for %s  %s → %s …", security_id, from_date, to_date)
        try:
            response = self._dhan.intraday_minute_data(
                security_id=security_id,
                exchange_segment="NSE_EQ",
                instrument_type="EQUITY",
                from_date=from_date,
                to_date=to_date,
            )

            if response.get("status") == "success" and "data" in response:
                data = response["data"]
                df = pd.DataFrame({
                    "timestamp": pd.to_datetime(data["start_Time"]),
                    "open": data["open"],
                    "high": data["high"],
                    "low": data["low"],
                    "close": data["close"],
                    "volume": data["volume"],
                })
                df.sort_values("timestamp", inplace=True)
                df.reset_index(drop=True, inplace=True)
                return df

            logger.error("API error: %s", response)
            return pd.DataFrame()

        except Exception:
            logger.exception("Failed to fetch historical data")
            return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════
# ORB Backtester
# ═══════════════════════════════════════════════════════════════════════

class ORBBacktester:
    """Replays candles through ORBBreakoutStrategy and simulates trades.

    On signal → open a virtual trade.
    On each subsequent candle → check SL hit, TP hit, or time-based exit.
    """

    def __init__(self, cfg: ORBConfig) -> None:
        self._cfg = cfg
        self._strategy = ORBBreakoutStrategy(cfg)
        self._trades: list[dict] = []
        self._active_trade: dict | None = None

    def run(self, df: pd.DataFrame, symbol: str) -> None:
        logger.info("Backtesting %s on %d candles …", symbol, len(df))

        prev_date: str | None = None

        for _, row in df.iterrows():
            ts: datetime = row["timestamp"]
            timestamp_str = ts.strftime("%Y-%m-%d %H:%M:%S")
            date_str = ts.strftime("%Y-%m-%d")
            time_obj = ts.time()

            # ── Day boundary — force-close any open trade ────────────
            if prev_date is not None and date_str != prev_date and self._active_trade:
                self._close_trade(
                    exit_price=row["close"],
                    exit_time=timestamp_str,
                    exit_reason="End of Day Exit",
                )
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

            if not self._active_trade:
                sig = self._strategy.on_candle(candle)
                if sig:
                    self._active_trade = {
                        "symbol": sig.symbol,
                        "direction": sig.direction,
                        "entry_time": sig.timestamp,
                        "entry_price": sig.entry,
                        "sl": sig.sl,
                        "tp": sig.tp,
                        "reason": sig.reason,
                    }
            else:
                self._manage_trade(candle, time_obj)

        # Close any remaining open trade
        if self._active_trade and not df.empty:
            last = df.iloc[-1]
            self._close_trade(
                exit_price=float(last["close"]),
                exit_time=last["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                exit_reason="End of Data Exit",
            )

        self._print_summary()
        self._export_results()

    # ── Trade management ─────────────────────────────────────────────

    def _manage_trade(self, candle: Candle, time_obj: dt_time) -> None:
        tr = self._active_trade
        assert tr is not None
        exit_price: float | None = None
        exit_reason = ""

        if tr["direction"] == "LONG":
            if candle.low <= tr["sl"]:
                exit_price, exit_reason = tr["sl"], "SL Hit"
            elif candle.high >= tr["tp"]:
                exit_price, exit_reason = tr["tp"], "TP Hit"
        else:  # SHORT
            if candle.high >= tr["sl"]:
                exit_price, exit_reason = tr["sl"], "SL Hit"
            elif candle.low <= tr["tp"]:
                exit_price, exit_reason = tr["tp"], "TP Hit"

        if not exit_price and time_obj >= self._cfg.exit_time:
            exit_price = candle.close
            exit_reason = "Time Exit"

        if exit_price is not None:
            self._close_trade(exit_price, candle.timestamp, exit_reason)

    def _close_trade(self, exit_price: float, exit_time: str, exit_reason: str) -> None:
        tr = self._active_trade
        assert tr is not None
        tr["exit_time"] = exit_time
        tr["exit_price"] = exit_price
        tr["exit_reason"] = exit_reason

        if tr["direction"] == "LONG":
            tr["pnl_pct"] = (exit_price - tr["entry_price"]) / tr["entry_price"] * 100
        else:
            tr["pnl_pct"] = (tr["entry_price"] - exit_price) / tr["entry_price"] * 100

        self._trades.append(tr)
        self._active_trade = None

    # ── Reporting ────────────────────────────────────────────────────

    def _print_summary(self) -> None:
        if not self._trades:
            logger.info("No trades taken during the backtest period.")
            return

        df_t = pd.DataFrame(self._trades)
        total = len(df_t)
        wins = (df_t["pnl_pct"] > 0).sum()

        summary = {
            "total_trades": total,
            "win_rate_pct": round(wins / total * 100, 2),
            "avg_pnl_pct": round(df_t["pnl_pct"].mean(), 2),
            "total_pnl_pct": round(df_t["pnl_pct"].sum(), 2),
            "max_win_pct": round(df_t["pnl_pct"].max(), 2),
            "max_loss_pct": round(df_t["pnl_pct"].min(), 2),
        }

        print("\n=== BACKTEST SUMMARY ===")
        for k, v in summary.items():
            label = k.replace("_", " ").title()
            print(f"  {label}: {v}")
        print("========================\n")

    def _export_results(self) -> None:
        if self._trades:
            df_t = pd.DataFrame(self._trades)
            df_t.to_csv("backtest_results.csv", index=False)
            logger.info("Results exported to backtest_results.csv")


# ═══════════════════════════════════════════════════════════════════════
# CLI entry-point
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )

    cfg = get_config()

    if not cfg.security_ids:
        logger.error("No security IDs configured in .env.")
    else:
        orb_cfg = ORBConfig(
            orb_start=cfg.orb_start_time_parsed,
            orb_end=cfg.orb_end_time_parsed,
            min_volume=cfg.min_volume_threshold,
            rr_ratio=cfg.risk_reward_ratio,
            exit_time=cfg.time_based_exit_parsed,
        )

        loader = HistoricalDataLoader(cfg.dhan_client_id, cfg.dhan_access_token)

        symbol = cfg.security_ids[0]
        end_date = datetime.now()
        start_date = end_date - timedelta(days=5)

        df = loader.fetch_intraday_data(
            security_id=symbol,
            from_date=start_date.strftime("%Y-%m-%d"),
            to_date=end_date.strftime("%Y-%m-%d"),
        )

        if not df.empty:
            bt = ORBBacktester(orb_cfg)
            bt.run(df, cfg.security_id_to_name.get(symbol, symbol))
        else:
            logger.error("Could not run backtest — empty data.")
