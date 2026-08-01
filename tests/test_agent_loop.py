import queue
import threading
import time
import pytest
from hermes.domain.models import Candle
from hermes.live.agent import agent_loop_worker
from hermes.data.analytics_mongo import InMemoryAnalyticsStore

def test_agent_loop_synthetic_day():
    q = queue.Queue()
    stop_event = threading.Event()

    symbol_univ_map = {"RELIANCE": "large"}
    sec_name_to_id = {"RELIANCE": "11536"}

    worker = threading.Thread(
        target=agent_loop_worker,
        args=(q, stop_event, "", "", symbol_univ_map, sec_name_to_id, "paper", None),
        daemon=True,
    )
    worker.start()

    # Feed ORB formation candles: high=2510, low=2490
    q.put(Candle("RELIANCE", "2026-07-31 09:15:00", 2500, 2505, 2490, 2500, 500))
    q.put(Candle("RELIANCE", "2026-07-31 09:30:00", 2500, 2510, 2495, 2505, 500))

    # Breakout candle: close 2515 (> ORB High 2510, volume 20000)
    q.put(Candle("RELIANCE", "2026-07-31 09:35:00", 2508, 2520, 2505, 2515, 20000))

    time.sleep(0.5)
    stop_event.set()
    worker.join(timeout=2.0)

    assert not worker.is_alive()
