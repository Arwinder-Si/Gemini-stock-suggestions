"""
Candle Recorder Consumer Thread.
Subscribes to strategy queues in main.py / live feed and appends finalized 1-min candles to CandleCache (Parquet store).
"""

import logging
import queue
import threading
import pandas as pd
from hermes.data.data_cache import CandleCache
from hermes.domain.models import Candle

logger = logging.getLogger(__name__)


def candle_recorder_worker(
    q: queue.Queue,
    stop_event: threading.Event,
    security_name_to_id: dict[str, str],
    cache_dir: str = "data/candles",
) -> None:
    """
    Worker function to record incoming Candle objects to CandleCache.
    """
    cache = CandleCache(base_dir=cache_dir)
    batch: list[dict] = []
    logger.info("Candle recorder worker started.")

    while not stop_event.is_set():
        try:
            candle: Candle = q.get(timeout=1.0)
        except queue.Empty:
            if batch:
                _flush_batch(cache, batch, security_name_to_id)
                batch.clear()
            continue

        try:
            sec_id = security_name_to_id.get(candle.symbol, candle.symbol)
            batch.append({
                "symbol": candle.symbol,
                "security_id": str(sec_id),
                "timestamp": candle.timestamp,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
            })

            # Flush when batch reaches size 50 or on timeout
            if len(batch) >= 50:
                _flush_batch(cache, batch, security_name_to_id)
                batch.clear()
        except Exception:
            logger.exception("Error recording candle")
        finally:
            q.task_done()

    if batch:
        _flush_batch(cache, batch, security_name_to_id)
        batch.clear()

    logger.info("Candle recorder worker stopped.")


def _flush_batch(cache: CandleCache, batch: list[dict], security_name_to_id: dict[str, str]) -> None:
    df = pd.DataFrame(batch)
    for sec_id, group_df in df.groupby("security_id"):
        cache.write(str(sec_id), group_df)
