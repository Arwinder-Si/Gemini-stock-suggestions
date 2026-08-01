"""
Universe-wide backtest runner against Parquet CandleCache data.
"""

import os
import sys
import argparse
import logging
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hermes.config import get_config
from hermes.data.data_cache import CandleCache
from hermes.research.backtest import ORBBacktester
from hermes.domain.strategy import ORBConfig
from hermes.domain.costs import CostModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("run_backtest")


def main():
    parser = argparse.ArgumentParser(description="Run universe backtest on cached candle history.")
    parser.add_argument("--days", type=int, default=30, help="Days of history to backtest.")
    parser.add_argument("--intrabar", choices=["pessimistic", "optimistic"], default="pessimistic", help="Intrabar SL/TP hit assumption.")
    parser.add_argument("--slippage", type=float, default=5.0, help="Slippage in basis points.")
    args = parser.parse_args()

    cfg = get_config()
    cache = CandleCache(base_dir="data/candles")

    end_d = date.today()
    start_d = end_d - timedelta(days=args.days)

    security_ids = cfg.security_ids or ["11536", "11532", "1594"]
    sec_id_to_name = cfg.security_id_to_name

    logger.info(f"Loading candle data for {len(security_ids)} symbols from {start_d} to {end_d}...")

    df_dict = {}
    for sec_id in security_ids:
        df = cache.read(str(sec_id), start=start_d, end=end_d)
        if not df.empty:
            sym_name = sec_id_to_name.get(str(sec_id), str(sec_id))
            df_dict[sym_name] = df

    if not df_dict:
        logger.error("No cached candle data found! Run scripts/backfill_candles.py first.")
        return

    orb_cfg = ORBConfig(
        orb_start=cfg.orb_start_time_parsed,
        orb_end=cfg.orb_end_time_parsed,
        min_volume=cfg.min_volume_threshold,
        rr_ratio=cfg.risk_reward_ratio,
        exit_time=cfg.time_based_exit_parsed,
    )

    cost_model = CostModel(slippage_bps=args.slippage)

    bt = ORBBacktester(
        cfg=orb_cfg,
        cost_model=cost_model,
        intrabar_mode=args.intrabar,
        max_concurrent_trades=5,
    )

    bt.run(df_dict)


if __name__ == "__main__":
    main()
