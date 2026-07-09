"""
Market feed producer — connects to DhanHQ WebSocket and builds 1-min candles.

Uses the DhanHQ v2 SDK (DhanContext + MarketFeed).

TODO: Migrate to asyncio-based WebSocket client if tick throughput
      requires lower latency than the threading model provides.
TODO: Add a monitoring dashboard endpoint that exposes feed health
      (ticks/sec, last-seen timestamp per symbol, queue depths).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from queue import Full, Queue

from models import Candle

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Candle Aggregator
# ═══════════════════════════════════════════════════════════════════════

class CandleAggregator:
    """Converts a stream of ticks into 1-minute OHLCV candles.

    Volume tracking:
        DhanHQ Quote packets include a cumulative `volume` field.
        We store the last-seen cumulative volume and compute the delta
        per tick to derive per-candle volume.  If the data source only
        provides LTQ (last-trade-quantity) instead, set
        `cumulative_volume=False` in the constructor.
    """

    def __init__(self, *, cumulative_volume: bool = True) -> None:
        self._cumulative = cumulative_volume
        # symbol → partial candle dict
        self._candles: dict[str, dict] = {}
        # symbol → last-seen cumulative volume (only when cumulative_volume=True)
        self._last_cum_vol: dict[str, int] = {}

    # ── Public API ───────────────────────────────────────────────────

    def process_tick(
        self,
        symbol: str,
        tick_time: datetime,
        ltp: float,
        volume_field: int,
    ) -> Candle | None:
        """Feed a tick; returns a finalized Candle when a minute boundary is crossed."""

        minute_str = tick_time.strftime("%Y-%m-%d %H:%M:00")

        # Compute tick-level volume contribution
        if self._cumulative:
            prev = self._last_cum_vol.get(symbol, volume_field)
            tick_vol = max(volume_field - prev, 0)
            self._last_cum_vol[symbol] = volume_field
        else:
            tick_vol = volume_field

        if symbol not in self._candles:
            self._start_new(symbol, minute_str, ltp, tick_vol)
            return None

        current = self._candles[symbol]

        if current["timestamp"] == minute_str:
            # Same minute — update running OHLCV
            current["high"] = max(current["high"], ltp)
            current["low"] = min(current["low"], ltp)
            current["close"] = ltp
            current["volume"] += tick_vol
            return None

        # Minute boundary crossed — finalize & start new
        finalized = Candle(
            symbol=symbol,
            timestamp=current["timestamp"],
            open=current["open"],
            high=current["high"],
            low=current["low"],
            close=current["close"],
            volume=current["volume"],
        )
        self._start_new(symbol, minute_str, ltp, tick_vol)
        return finalized

    @property
    def current_candles(self) -> dict[str, dict]:
        """Expose internal state for testing."""
        return self._candles

    # ── Private ──────────────────────────────────────────────────────

    def _start_new(self, symbol: str, ts: str, ltp: float, vol: int) -> None:
        self._candles[symbol] = {
            "timestamp": ts,
            "open": ltp,
            "high": ltp,
            "low": ltp,
            "close": ltp,
            "volume": vol,
        }


# ═══════════════════════════════════════════════════════════════════════
# MarketFeed Producer (DhanHQ v2 SDK)
# ═══════════════════════════════════════════════════════════════════════

class MarketFeedProducer:
    """Connects to DhanHQ live feed and pushes finalized 1-min candles
    into a fan-out list of bounded queues (one per strategy worker).

    Uses the DhanHQ v2 SDK classes: DhanContext + MarketFeed.
    """

    # Reconnect parameters
    MAX_BACKOFF_SECS = 60
    INITIAL_BACKOFF_SECS = 2

    def __init__(
        self,
        client_id: str,
        access_token: str,
        security_ids: list[str],
        strategy_queues: list[Queue],
        security_id_to_name: dict[str, str] | None = None,
    ) -> None:
        self._client_id = client_id
        self._access_token = access_token
        self._security_ids = security_ids
        self._queues = strategy_queues
        self._id_to_name = security_id_to_name or {}

        self._aggregator = CandleAggregator(cumulative_volume=True)
        self._is_running = False
        self._backoff = self.INITIAL_BACKOFF_SECS

    # ── Public API ───────────────────────────────────────────────────

    def start(self) -> None:
        """Blocking call — run inside a dedicated thread."""
        # Lazy import so the rest of the codebase isn't blocked if
        # dhanhq is not installed (e.g., during unit tests).
        try:
            from dhanhq import DhanFeed
            from dhanhq.marketfeed import NSE, Quote
        except Exception as e:
            logger.error(f"dhanhq import failed: {e}")
            return

        self._is_running = True

        # Build instrument list: (ExchangeSegment, SecurityId, SubscriptionType)
        instruments = [
            (NSE, str(sid), Quote)
            for sid in self._security_ids
        ]

        while self._is_running:
            try:
                logger.info(
                    "Connecting to DhanHQ WebSocket for %d instruments …",
                    len(instruments),
                )
                
                # New v2 DhanFeed SDK usage
                feed = DhanFeed(self._client_id, self._access_token, instruments, version='v2')
                
                # Override the internal callback to route ticks to our aggregator
                feed.on_ticks = lambda msg: self._on_message(None, msg)
                
                # We can also mock on_connect / on_close if the SDK supports them or just call them manually
                self._on_connect()
                
                self._backoff = self.INITIAL_BACKOFF_SECS  # reset on success
                feed.run_forever()  # blocks until disconnect
                
                self._on_close(None)
            except Exception:
                logger.exception("MarketFeed connection error")

            if not self._is_running:
                break

            # Exponential back-off reconnect (capped)
            logger.warning("Reconnecting in %d s …", self._backoff)
            time.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, self.MAX_BACKOFF_SECS)

        logger.info("MarketFeedProducer stopped.")

    def stop(self) -> None:
        self._is_running = False
        logger.info("MarketFeedProducer stop requested.")

    # ── Callbacks ────────────────────────────────────────────────────

    def _on_connect(self) -> None:
        logger.info("Connected to DhanHQ WebSocket.")

    def _on_message(self, ws, message) -> None:  # noqa: ANN001
        if not isinstance(message, dict):
            return

        try:
            sec_id = str(message.get("security_id", ""))
            if not sec_id:
                return

            ltp = float(message.get("LTP", message.get("last_price", 0.0)))
            # Prefer cumulative volume; fall back to LTQ
            volume = int(
                message.get("volume", message.get("LTQ", message.get("last_trade_quantity", 0)))
            )

            tick_time = datetime.now()
            finalized = self._aggregator.process_tick(sec_id, tick_time, ltp, volume)

            if finalized:
                # Replace raw security_id with human name if available
                name = self._id_to_name.get(finalized.symbol, finalized.symbol)
                finalized = Candle(
                    symbol=name,
                    timestamp=finalized.timestamp,
                    open=finalized.open,
                    high=finalized.high,
                    low=finalized.low,
                    close=finalized.close,
                    volume=finalized.volume,
                )
                self._broadcast(finalized)
        except Exception:
            logger.exception("Error processing tick")

    def _on_close(self, ws, *args) -> None:  # noqa: ANN001
        logger.warning("WebSocket closed: %s", args)

    # ── Fan-out to strategy queues ───────────────────────────────────

    def _broadcast(self, candle: Candle) -> None:
        for q in self._queues:
            try:
                q.put(candle, block=False)
            except Full:
                logger.warning(
                    "Queue full — dropped candle for %s @ %s",
                    candle.symbol,
                    candle.timestamp,
                )
