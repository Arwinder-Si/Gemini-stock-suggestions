"""
Live entry-point — Autonomous Trading Agent loop.
Wires MarketFeedProducer -> Strategy -> RiskEngine -> PaperBroker -> Portfolio -> PositionManager -> TradeJournal -> AnalyticsStore.
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

from hermes.config import get_config
from hermes.data.logger import init_logger, log_signal
from hermes.live.feed import MarketFeedProducer
from hermes.integrations.notifier import send_webex_alert
from hermes.domain.strategy import ORBBreakoutStrategy, ORBConfig
from hermes.clock import trading_date_ist, now_ist
from hermes.domain.universe import SECTOR_MAP

from hermes.domain.orders import Order, OrderSide, OrderType, OrderState
from hermes.execution.portfolio import Portfolio
from hermes.domain.risk import RiskEngine, RiskConfig
from hermes.execution.paper_broker import PaperBroker
from hermes.domain.position_manager import PositionManager
from hermes.data.analytics_models import Recommendation, PaperTrade
from hermes.data.analytics_mongo import MongoAnalyticsStore, InMemoryAnalyticsStore
from hermes.analytics.trade_journal import build_trade_journal_entry
from hermes.live.recorder import candle_recorder_worker
from hermes import artifacts

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


def agent_loop_worker(
    q: queue.Queue,
    stop_event: threading.Event,
    bot_token: str,
    room_id: str,
    symbol_univ_map: dict[str, str],
    sec_name_to_id: dict[str, str],
    trading_mode: str = "paper",
    mongo_uri: str | None = None,
) -> None:
    cfg = get_config()
    regime = get_market_regime()
    rr_ratio_large = 1.0 if "BEAR" in regime or "NEUTRAL" in regime else cfg.risk_reward_ratio

    # Strategies
    orb_cfg_large = ORBConfig(
        orb_start=cfg.orb_start_time_parsed,
        orb_end=cfg.orb_end_time_parsed,
        min_volume=cfg.min_volume_threshold,
        rr_ratio=rr_ratio_large,
        exit_time=cfg.time_based_exit_parsed,
    )
    strategy_large = ORBBreakoutStrategy(orb_cfg_large)

    orb_cfg_small = ORBConfig(
        orb_start=cfg.orb_start_time_parsed,
        orb_end=dt_time(9, 45),
        min_volume=max(50000, cfg.min_volume_threshold * 2),
        rr_ratio=1.0,
        exit_time=cfg.time_based_exit_parsed,
    )
    strategy_small = ORBBreakoutStrategy(orb_cfg_small)

    # Agent components — use .env-configurable paper trading params
    portfolio = Portfolio(starting_capital=cfg.paper_starting_capital)
    risk_engine = RiskEngine(RiskConfig(
        max_daily_trades=cfg.max_daily_trades,
        max_daily_loss_rupees=cfg.max_daily_loss_rupees,
        risk_per_trade_pct=cfg.risk_per_trade_pct,
        max_sector_exposure_pct=cfg.max_sector_exposure_pct,
    ))
    broker = PaperBroker(portfolio=portfolio)
    position_manager = PositionManager(time_exit=cfg.time_based_exit_parsed)

    # Analytics Store
    if mongo_uri:
        try:
            store = MongoAnalyticsStore(mongo_uri, tls_insecure=cfg.mongodb_tls_insecure)
            logger.info("Connected to MongoDB Atlas analytics store.")
        except Exception as e:
            logger.warning(f"Failed to connect to MongoDB Atlas ({e}). Falling back to InMemoryAnalyticsStore.")
            store = InMemoryAnalyticsStore()
    else:
        store = InMemoryAnalyticsStore()

    recommendations_by_symbol: dict[str, Recommendation] = {}

    logger.info(f"Agent loop started in [{trading_mode.upper()}] mode. Large RR: {rr_ratio_large}, Small RR: 1.0")

    while not stop_event.is_set():
        # Kill switch — file sentinel check (var/state first, repo root fallback)
        if artifacts.kill_switch_active():
            logger.warning("KILL_SWITCH file detected! Flattening positions and halting.")
            for sym, pos in list(portfolio.positions.items()):
                exit_side = OrderSide.SELL if pos["side"] == "BUY" else OrderSide.BUY
                order = Order(
                    symbol=sym,
                    security_id=sec_name_to_id.get(sym, sym),
                    side=exit_side,
                    order_type=OrderType.MARKET,
                    quantity=pos["quantity"],
                )
                broker.place_order(order)
                portfolio.close_position(sym, broker.latest_ltps.get(sym, pos["entry_price"]), 0.0, 0.0)
                position_manager.remove_position(sym)
            artifacts.clear_kill_switch()
            stop_event.set()
            break

        try:
            candle = q.get(timeout=1.0)
        except queue.Empty:
            continue

        try:
            time_obj = datetime.strptime(candle.timestamp, "%Y-%m-%d %H:%M:%S").time()
            broker.update_market_price(candle.symbol, candle.close)

            # 1. Manage existing positions for exit signals
            exit_sig = position_manager.check_candle(candle, time_obj)
            if exit_sig:
                pos = portfolio.positions.get(candle.symbol)
                if pos:
                    exit_side = OrderSide.SELL if pos["side"] == "BUY" else OrderSide.BUY
                    order = Order(
                        symbol=candle.symbol,
                        security_id=sec_name_to_id.get(candle.symbol, candle.symbol),
                        side=exit_side,
                        order_type=OrderType.MARKET,
                        quantity=pos["quantity"],
                    )
                    filled_order = broker.place_order(order)
                    if filled_order.state == OrderState.FILLED:
                        net_pnl = (filled_order.average_fill_price - pos["entry_price"]) * pos["quantity"]
                        trade_record = portfolio.close_position(
                            symbol=candle.symbol,
                            exit_price=filled_order.average_fill_price,
                            net_pnl=net_pnl,
                            net_amount=filled_order.average_fill_price * pos["quantity"],
                        )
                        position_manager.remove_position(candle.symbol)

                        # Save Journal Entry & PaperTrade
                        rec = recommendations_by_symbol.get(candle.symbol) or Recommendation(symbol=candle.symbol)
                        paper_trd = PaperTrade(
                            trade_id=f"TRD-{filled_order.client_order_id}",
                            recommendation_id=rec.recommendation_id,
                            trading_date=trading_date_ist().strftime("%Y-%m-%d"),
                            symbol=candle.symbol,
                            side=pos["side"],
                            quantity=pos["quantity"],
                            entry_time=candle.timestamp,
                            entry_price=pos["entry_price"],
                            exit_time=candle.timestamp,
                            exit_price=filled_order.average_fill_price,
                            exit_reason=exit_sig.exit_reason,
                            gross_pnl=round(net_pnl, 2),
                            net_pnl=round(net_pnl, 2),
                            planned_sl=pos.get("sl", 0.0),
                            planned_tp=pos.get("tp", 0.0),
                        )
                        store.save_paper_trade(paper_trd)
                        jrn_entry = build_trade_journal_entry(rec, paper_trd)
                        store.save_journal_entry(jrn_entry)
                        logger.info(f"[JOURNAL] Saved journal entry for {candle.symbol}. PnL: ₹{net_pnl:.2f}")

            # 2. Check for entry signals
            univ = symbol_univ_map.get(candle.symbol, "large")
            strategy = strategy_small if univ == "small" else strategy_large

            sig = strategy.on_candle(candle)
            if sig and sig.direction in ("LONG", "SHORT"):
                logger.info(f"[SIGNAL] {sig.direction} {sig.symbol} on {sig.timestamp} | entry={sig.entry:.2f} sl={sig.sl:.2f} tp={sig.tp:.2f}")
                log_signal(sig)
                send_webex_alert(sig, bot_token, room_id, universe=univ)

                sector = SECTOR_MAP.get(candle.symbol, "Other")
                rec = Recommendation(
                    trading_date=trading_date_ist().strftime("%Y-%m-%d"),
                    symbol=candle.symbol,
                    sector=sector,
                    strategy=f"ORB_{univ.upper()}",
                    action="BUY" if sig.direction == "LONG" else "SELL",
                    entry_price=sig.entry,
                    stop_loss=sig.sl,
                    target_price=sig.tp,
                    reasoning=sig.reason,
                )
                recommendations_by_symbol[candle.symbol] = rec
                store.save_recommendation(rec)

                # Validate with RiskEngine
                passed, reason, qty = risk_engine.validate_recommendation(
                    rec=rec,
                    current_daily_trades=len(portfolio.completed_trades_today) + len(portfolio.positions),
                    realized_pnl_today=portfolio.realized_pnl_today,
                    portfolio_value=portfolio.get_total_portfolio_value(broker.latest_ltps),
                    open_positions=list(portfolio.positions.values()),
                    completed_symbols_today=portfolio.completed_symbols_today,
                )

                if passed and qty > 0:
                    order_side = OrderSide.BUY if sig.direction == "LONG" else OrderSide.SELL
                    order = Order(
                        symbol=candle.symbol,
                        security_id=sec_name_to_id.get(candle.symbol, candle.symbol),
                        side=order_side,
                        order_type=OrderType.MARKET,
                        quantity=qty,
                    )
                    filled_order = broker.place_order(order)
                    if filled_order.state == OrderState.FILLED:
                        position_manager.track_position(
                            symbol=candle.symbol,
                            side="BUY" if sig.direction == "LONG" else "SELL",
                            entry_price=filled_order.average_fill_price,
                            sl=sig.sl,
                            tp=sig.tp,
                        )

        except Exception:
            logger.exception("Error in agent worker processing candle")
        finally:
            q.task_done()

    # EOD Snapshot on shutdown
    snap = portfolio.get_snapshot(broker.latest_ltps)
    store.save_portfolio_snapshot(snap)
    logger.info(f"Agent loop stopped. EOD Realized P&L: ₹{snap.realized_pnl_today:.2f}")


def _resolve_feed_source(cfg) -> str:
    """Return 'dhan' or 'yfinance' based on FEED_SOURCE and available credentials."""
    mode = (cfg.feed_source or "auto").lower()
    if mode in ("dhan", "yfinance"):
        return mode
    if cfg.dhan_client_id and cfg.dhan_pin and cfg.dhan_totp_secret:
        return "dhan"
    return "yfinance"


def main() -> None:
    logger.info("Initializing Autonomous Trading Agent ...")
    cfg = get_config()
    init_logger()

    trade_plan = cfg.load_active_trade_plan(required=False) or cfg.security_id_map
    if not trade_plan:
        logger.error("No valid stocks found in trade plan or config.")
        sys.exit(1)

    symbol_univ_map = {sym: "large" for sym in trade_plan}
    if os.path.exists("trade_plan_smallcap.json"):
        try:
            small_plan = cfg.load_trade_plan("trade_plan_smallcap.json")
            for sym in small_plan:
                symbol_univ_map[sym] = "small"
        except Exception:
            pass

    security_ids = list(trade_plan.values())
    security_id_to_name = {v: k for k, v in trade_plan.items()}
    symbol_names = list(trade_plan.keys())

    logger.info("Loaded %d stocks for autonomous monitoring.", len(trade_plan))

    feed_source = _resolve_feed_source(cfg)
    trading_mode = cfg.trading_mode or os.getenv("TRADING_MODE", "paper")
    logger.info("Feed source: %s | Trading mode: %s", feed_source, trading_mode)

    strategy_queue: queue.Queue = queue.Queue(maxsize=2000)
    recorder_queue: queue.Queue = queue.Queue(maxsize=2000)
    stop_event = threading.Event()

    producer = None
    if feed_source == "dhan":
        try:
            from hermes.integrations.auth_manager import get_fresh_dhan_token
            access_token = get_fresh_dhan_token(cfg.dhan_client_id, cfg.dhan_pin, cfg.dhan_totp_secret)
        except Exception as e:
            logger.error("Failed to generate Dhan Access Token: %s", e)
            sys.exit(1)

        producer = MarketFeedProducer(
            client_id=cfg.dhan_client_id,
            access_token=access_token,
            security_ids=security_ids,
            strategy_queues=[strategy_queue, recorder_queue],
            security_id_to_name=security_id_to_name,
        )
    else:
        from hermes.live.yfinance_feed import YfinanceFeedProducer

        producer = YfinanceFeedProducer(
            symbols=symbol_names,
            strategy_queues=[strategy_queue, recorder_queue],
        )

    mongo_uri = cfg.mongodb_uri or os.getenv("MONGODB_URI")
    if not mongo_uri:
        logger.warning(
            "MONGODB_URI not set — paper trades will NOT persist after shutdown. "
            "Add your Atlas connection string to .env (see .env.example)."
        )

    agent_thread = threading.Thread(
        target=agent_loop_worker,
        args=(
            strategy_queue,
            stop_event,
            cfg.webex_token,
            cfg.webex_room_id,
            symbol_univ_map,
            trade_plan,
            trading_mode,
            mongo_uri,
        ),
        daemon=True,
        name="agent-worker",
    )

    recorder_thread = threading.Thread(
        target=candle_recorder_worker,
        args=(recorder_queue, stop_event, trade_plan),
        daemon=True,
        name="recorder-worker",
    )

    def graceful_exit(signum, frame):
        logger.info("Shutdown signal received.")
        stop_event.set()
        producer.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    agent_thread.start()
    recorder_thread.start()

    try:
        producer.start()
    except Exception:
        logger.exception("Producer crashed.")
    finally:
        graceful_exit(None, None)


if __name__ == "__main__":
    main()
