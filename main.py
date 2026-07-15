"""
Live entry-point — wires up producer, strategy worker, notifier and logger.

Supports both Large/Mid Cap and Small Cap universes simultaneously.
"""

from __future__ import annotations

import logging
import queue
import signal
import sys
import threading
import os
import json
from datetime import datetime, time as dt_time

from config import get_config
from logger import init_logger, log_signal
from market_feed import MarketFeedProducer
from notifier import send_webex_alert
from strategy import ORBBreakoutStrategy, ORBConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

def get_market_regime() -> str:
    if os.path.exists("market_regime.txt"):
        with open("market_regime.txt", "r") as f:
            return f.read().strip()
    return "UNKNOWN"

def strategy_worker(q: queue.Queue, stop_event: threading.Event, bot_token: str, room_id: str, symbol_univ_map: dict) -> None:
    cfg = get_config()
    regime = get_market_regime()
    rr_ratio_large = 1.0 if "BEAR" in regime or "NEUTRAL" in regime else cfg.risk_reward_ratio
    
    # Large Cap Config (15m ORB, Standard Volume Filter)
    orb_cfg_large = ORBConfig(
        orb_start=cfg.orb_start_time_parsed,
        orb_end=cfg.orb_end_time_parsed,
        min_volume=cfg.min_volume_threshold,
        rr_ratio=rr_ratio_large,
        exit_time=cfg.time_based_exit_parsed,
    )
    strategy_large = ORBBreakoutStrategy(orb_cfg_large)
    
    # Small Cap Config (Strict Rules: 30 min ORB, 3.0x Volume)
    orb_cfg_small = ORBConfig(
        orb_start=cfg.orb_start_time_parsed,
        orb_end=dt_time(9, 45),  # 30 min ORB
        min_volume=cfg.min_volume_threshold * 2,  # Stricter volume
        rr_ratio=1.0,  # Always 1.0 for small caps to lock in quick profits
        exit_time=cfg.time_based_exit_parsed,
    )
    strategy_small = ORBBreakoutStrategy(orb_cfg_small)

    logger.info(f"Strategy worker started. Large RR: {rr_ratio_large}, Small RR: 1.0")

    while not stop_event.is_set():
        try:
            candle = q.get(timeout=1.0)
        except queue.Empty:
            continue

        try:
            univ = symbol_univ_map.get(candle.symbol, "large")
            strategy = strategy_small if univ == "small" else strategy_large
            
            sig = strategy.on_candle(candle)
            if sig:
                logger.info(
                    "[SIGNAL] %s %s on %s | entry=%.2f sl=%.2f tp=%.2f",
                    sig.direction, sig.symbol, sig.timestamp, sig.entry, sig.sl, sig.tp
                )
                log_signal(sig)
                send_webex_alert(sig, bot_token, room_id)
        except Exception:
            logger.exception("Error in strategy worker processing candle")
        finally:
            q.task_done()

    logger.info("Strategy worker stopped.")


def main() -> None:
    logger.info("Initializing NSE Intraday Signal System …")
    cfg = get_config()
    init_logger()

    # Load both trade plans
    trade_plan = {}
    symbol_univ_map = {}
    
    if os.path.exists("trade_plan.json"):
        with open("trade_plan.json", "r") as f:
            plan = json.load(f)
            trade_plan.update(plan)
            for sym in plan:
                symbol_univ_map[sym] = "large"
                
    if os.path.exists("trade_plan_smallcap.json"):
        with open("trade_plan_smallcap.json", "r") as f:
            plan = json.load(f)
            trade_plan.update(plan)
            for sym in plan:
                symbol_univ_map[sym] = "small"
                
    if not trade_plan:
        logger.error("No stocks found in trade_plan.json or trade_plan_smallcap.json.")
        sys.exit(1)

    security_ids = list(trade_plan.values())
    security_id_to_name = {v: k for k, v in trade_plan.items()}
    
    logger.info(f"Loaded {len(trade_plan)} total stocks for monitoring.")

    try:
        from auth_manager import get_fresh_dhan_token
        access_token = get_fresh_dhan_token(cfg.dhan_client_id, cfg.dhan_pin, cfg.dhan_totp_secret)
    except Exception as e:
        logger.error(f"Failed to generate Dhan Access Token: {e}")
        sys.exit(1)

    strategy_queue: queue.Queue = queue.Queue(maxsize=2000)
    stop_event = threading.Event()

    producer = MarketFeedProducer(
        client_id=cfg.dhan_client_id,
        access_token=access_token,
        security_ids=security_ids,
        strategy_queues=[strategy_queue],
        security_id_to_name=security_id_to_name,
    )

    worker = threading.Thread(
        target=strategy_worker,
        args=(strategy_queue, stop_event, cfg.webex_token, cfg.webex_room_id, symbol_univ_map),
        daemon=True,
        name="orb-worker",
    )

    def graceful_exit(signum, frame):  # noqa: ANN001
        logger.info("Graceful shutdown requested.")
        stop_event.set()
        producer.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    worker.start()
    try:
        producer.start()
    except Exception:
        logger.exception("Producer thread crashed.")
    finally:
        graceful_exit(None, None)


if __name__ == "__main__":
    main()
