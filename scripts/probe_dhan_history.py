"""
Probe DhanHQ historical 1-minute chart API availability.
Requests chart data backward month by month to determine maximum historical depth.
Outputs results to docs/DATA_AVAILABILITY.md.
"""

import os
import sys
import logging
from datetime import datetime, timedelta, date
import requests

# Add parent directory to path so config and auth_manager can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hermes.config import get_config
from hermes.clock import now_ist

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("probe_dhan_history")

PROBE_SYMBOLS = [
    {"symbol": "RELIANCE", "security_id": "11536"},
    {"symbol": "TCS", "security_id": "11532"},
    {"symbol": "INFY", "security_id": "1594"},
]

DHAN_CHARTS_URL = "https://api.dhan.co/v2/charts/intraday"


def probe_month(security_id: str, from_date: str, to_date: str, client_id: str, access_token: str) -> dict:
    headers = {
        "access-token": access_token,
        "client-id": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "securityId": security_id,
        "exchangeSegment": "NSE_EQ",
        "instrumentType": "EQUITY",
        "from": from_date,
        "to": to_date,
    }

    try:
        resp = requests.post(DHAN_CHARTS_URL, json=payload, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # Dhan chart data usually returns arrays: start_Time, open, high, low, close, volume
            timestamps = data.get("start_Time", [])
            if timestamps:
                min_ts = datetime.fromtimestamp(min(timestamps)).strftime("%Y-%m-%d %H:%M:%S")
                max_ts = datetime.fromtimestamp(max(timestamps)).strftime("%Y-%m-%d %H:%M:%S")
                return {"status": "SUCCESS", "count": len(timestamps), "min_ts": min_ts, "max_ts": max_ts}
            else:
                return {"status": "EMPTY", "count": 0, "error": data.get("remarks", "No data returned")}
        else:
            return {"status": f"HTTP_{resp.status_code}", "count": 0, "error": resp.text[:200]}
    except Exception as e:
        return {"status": "ERROR", "count": 0, "error": str(e)}


def run_probe():
    cfg = get_config()

    if not cfg.dhan_client_id:
        logger.error("Dhan Client ID missing in config/.env. Cannot run probe.")
        return

    try:
        from hermes.integrations.auth_manager import get_fresh_dhan_token
        access_token = get_fresh_dhan_token(cfg.dhan_client_id, cfg.dhan_pin, cfg.dhan_totp_secret)
    except Exception as e:
        logger.error(f"Failed to generate Dhan Access Token: {e}")
        return

    results = []
    today = now_ist().date()
    
    # Check last 6 months in 30-day chunks
    for sym_info in PROBE_SYMBOLS:
        sym = sym_info["symbol"]
        sec_id = sym_info["security_id"]
        logger.info(f"Probing historical data for {sym} (Security ID: {sec_id}) ...")

        for months_back in range(6):
            end_d = today - timedelta(days=months_back * 30)
            start_d = end_d - timedelta(days=30)
            from_str = start_d.strftime("%Y-%m-%d")
            to_str = end_d.strftime("%Y-%m-%d")

            res = probe_month(sec_id, from_str, to_str, cfg.dhan_client_id, access_token)
            logger.info(f"  {from_str} to {to_str}: status={res['status']}, candles={res['count']}")
            results.append({
                "symbol": sym,
                "security_id": sec_id,
                "from": from_str,
                "to": to_str,
                "res": res,
            })

    # Write findings to docs/DATA_AVAILABILITY.md
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    os.makedirs(docs_dir, exist_ok=True)
    out_file = os.path.join(docs_dir, "DATA_AVAILABILITY.md")

    with open(out_file, "w") as f:
        f.write("# DhanHQ Intraday Historical Data Availability Probe\n\n")
        f.write(f"**Probe Date:** {now_ist().strftime('%Y-%m-%d %H:%M:%S IST')}\n\n")
        f.write("| Symbol | Security ID | From Date | To Date | Status | Candle Count | Min Timestamp | Max Timestamp |\n")
        f.write("|--------|-------------|-----------|---------|--------|--------------|---------------|---------------|\n")
        for r in results:
            res = r["res"]
            min_ts = res.get("min_ts", "-")
            max_ts = res.get("max_ts", "-")
            f.write(f"| {r['symbol']} | {r['security_id']} | {r['from']} | {r['to']} | {res['status']} | {res['count']} | {min_ts} | {max_ts} |\n")

    logger.info(f"Probe complete. Findings saved to {out_file}")


if __name__ == "__main__":
    run_probe()
