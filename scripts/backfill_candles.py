"""
Backfill historical 1-minute candles from DhanHQ into CandleCache.
Checks existing coverage and fetches missing ranges in chunks.
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta, date
import pandas as pd
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hermes.config import get_config
from hermes.data.data_cache import CandleCache
from hermes.clock import now_ist

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("backfill_candles")

DHAN_CHARTS_URL = "https://api.dhan.co/v2/charts/intraday"


def fetch_dhan_candles(security_id: str, from_date: str, to_date: str, client_id: str, access_token: str) -> pd.DataFrame:
    headers = {
        "access-token": access_token,
        "client-id": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "securityId": str(security_id),
        "exchangeSegment": "NSE_EQ",
        "instrumentType": "EQUITY",
        "from": from_date,
        "to": to_date,
    }

    try:
        resp = requests.post(DHAN_CHARTS_URL, json=payload, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"Dhan API HTTP {resp.status_code} for sec_id={security_id}: {resp.text[:150]}")
            return pd.DataFrame()

        data = resp.json()
        timestamps = data.get("start_Time", [])
        if not timestamps:
            return pd.DataFrame()

        records = []
        for i in range(len(timestamps)):
            ts_str = datetime.fromtimestamp(timestamps[i]).strftime("%Y-%m-%d %H:%M:%S")
            records.append({
                "security_id": str(security_id),
                "timestamp": ts_str,
                "open": data["open"][i],
                "high": data["high"][i],
                "low": data["low"][i],
                "close": data["close"][i],
                "volume": int(data["volume"][i]),
            })

        return pd.DataFrame(records)
    except Exception as e:
        logger.error(f"Failed to fetch candles for sec_id={security_id}: {e}")
        return pd.DataFrame()


def backfill_universe(security_ids: list[str], days_back: int = 90, cache_dir: str = "data/candles"):
    cfg = get_config()
    cache = CandleCache(base_dir=cache_dir)

    try:
        from hermes.integrations.auth_manager import get_fresh_dhan_token
        access_token = get_fresh_dhan_token(cfg.dhan_client_id, cfg.dhan_pin, cfg.dhan_totp_secret)
    except Exception as e:
        logger.error(f"Failed to generate Dhan Access Token: {e}")
        return

    today = now_ist().date()
    start_date = today - timedelta(days=days_back)

    logger.info(f"Starting backfill for {len(security_ids)} symbols from {start_date} to {today} ...")

    for idx, sec_id in enumerate(security_ids, 1):
        sec_id_str = str(sec_id)
        coverage = cache.coverage(sec_id_str)
        logger.info(f"[{idx}/{len(security_ids)}] Processing Security ID: {sec_id_str} | Current coverage: {coverage}")

        # Fetch in 30-day chunks
        curr_start = start_date
        while curr_start < today:
            curr_end = min(curr_start + timedelta(days=30), today)
            from_str = curr_start.strftime("%Y-%m-%d")
            to_str = curr_end.strftime("%Y-%m-%d")

            df = fetch_dhan_candles(sec_id_str, from_str, to_str, cfg.dhan_client_id, access_token)
            if not df.empty:
                cache.write(sec_id_str, df)
                logger.info(f"  Wrote {len(df)} candles for {from_str} -> {to_str}")
            
            curr_start = curr_end + timedelta(days=1)
            time.sleep(0.3)  # Throttling to respect rate limits

    logger.info("Backfill completed.")


if __name__ == "__main__":
    cfg = get_config()
    sec_ids = cfg.security_ids or ["11536", "11532", "1594"]  # RELIANCE, TCS, INFY default
    backfill_universe(sec_ids)
