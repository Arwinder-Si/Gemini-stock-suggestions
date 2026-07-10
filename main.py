"""
Live entry-point — wires up producer, strategy worker, notifier and logger.

IMPORTANT: This system ONLY generates alerts and logs signals.
It does NOT place real trades via any broker API.
This is intentional to comply with SEBI's 2026 retail algo trading
requirements (static IP whitelisting, Algo-ID tagging, registration).

TODO: Add a monitoring dashboard (e.g., a lightweight FastAPI server)
      that exposes feed health, queue depths, and today's signals.
TODO: Support multiple strategy workers with different strategy classes.
TODO: Evaluate migration to asyncio or multiprocessing if thread-based
      performance becomes a bottleneck at scale.
"""

from __future__ import annotations

import logging
import queue
import signal
import sys
import threading

from config import get_config
from logger import init_logger, log_signal
from market_feed import MarketFeedProducer
from notifier import send_webex_alert
from strategy import ORBBreakoutStrategy, ORBConfig

# ── Logging setup ────────────────────────────────────────────────────

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


# ── Strategy worker thread ───────────────────────────────────────────

def strategy_worker(
    q: queue.Queue,
    stop_event: threading.Event,
    bot_token: str,
    room_id: str,
) -> None:
    """Consumes candles from the queue and runs ORB strategy logic."""

    cfg = get_config()
    orb_cfg = ORBConfig(
        orb_start=cfg.orb_start_time_parsed,
        orb_end=cfg.orb_end_time_parsed,
        min_volume=cfg.min_volume_threshold,
        rr_ratio=cfg.risk_reward_ratio,
        exit_time=cfg.time_based_exit_parsed,
    )
    strategy = ORBBreakoutStrategy(orb_cfg)
    logger.info("Strategy worker started (ORB %s–%s).", cfg.orb_start_time, cfg.orb_end_time)

    while not stop_event.is_set():
        try:
            candle = q.get(timeout=1.0)
        except queue.Empty:
            continue

        try:
            sig = strategy.on_candle(candle)
            if sig:
                logger.info(
                    "[SIGNAL] %s %s on %s | entry=%.2f sl=%.2f tp=%.2f",
                    sig.direction, sig.symbol, sig.timestamp,
                    sig.entry, sig.sl, sig.tp,
                )
                log_signal(sig)
                send_webex_alert(sig, bot_token, room_id)
        except Exception:
            logger.exception("Error in strategy worker processing candle")
        finally:
            q.task_done()

    logger.info("Strategy worker stopped.")


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("Initializing NSE Intraday Signal System …")
    cfg = get_config()

    if not cfg.security_ids:
        logger.error("No security IDs configured in .env — exiting.")
        sys.exit(1)

    init_logger()

    # Log the loaded stocks so the user can see what the plan is
    loaded_stocks = list(cfg.security_id_map.keys())
    logger.info(f"Loaded Trade Plan with {len(loaded_stocks)} stocks: {', '.join(loaded_stocks)}")
    logger.info("Attempting to connect to Dhan live feed...")

    try:
        from auth_manager import get_fresh_dhan_token
        access_token = get_fresh_dhan_token(cfg.dhan_client_id, cfg.dhan_pin, cfg.dhan_totp_secret)
    except Exception as e:
        logger.error(f"Failed to generate Dhan Access Token via TOTP: {e}")
        sys.exit(1)

    # Bounded queue — prevents unbounded memory growth
    strategy_queue: queue.Queue = queue.Queue(maxsize=1000)
    stop_event = threading.Event()

    producer = MarketFeedProducer(
        client_id=cfg.dhan_client_id,
        access_token=access_token,
        security_ids=cfg.security_ids,
        strategy_queues=[strategy_queue],
        security_id_to_name=cfg.security_id_to_name,
    )

    worker = threading.Thread(
        target=strategy_worker,
        args=(strategy_queue, stop_event, cfg.webex_token, cfg.webex_room_id),
        daemon=True,
        name="orb-worker",
    )

    def graceful_exit(signum, frame):  # noqa: ANN001
        logger.info("Graceful shutdown requested (signal=%s).", signum)
        stop_event.set()
        producer.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    worker.start()

    try:
        # Blocks until stop or crash
        producer.start()
    except Exception:
        logger.exception("Producer thread crashed.")
    finally:
        graceful_exit(None, None)


if __name__ == "__main__":
    main()
