"""
Domain models for Trading Analytics & Continuous Learning Framework and Trade Journal.
"""

from dataclasses import dataclass, field
import uuid
from hermes.clock import now_ist


@dataclass
class Recommendation:
    recommendation_id: str = field(default_factory=lambda: f"REC-{uuid.uuid4().hex[:12].upper()}")
    trading_date: str = ""
    created_at: str = field(default_factory=lambda: now_ist().strftime("%Y-%m-%d %H:%M:%S IST"))
    symbol: str = ""
    company_name: str = ""
    sector: str = ""
    strategy: str = "ORB"
    action: str = "BUY"  # BUY / SELL / HOLD
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_price: float = 0.0
    risk_reward_ratio: float = 1.0
    confidence_score: float = 0.0
    reasoning: str = ""
    market_regime: str = ""
    vix_value: float = 0.0
    supporting_indicators: dict = field(default_factory=dict)


@dataclass
class PaperTrade:
    trade_id: str = ""
    recommendation_id: str = ""
    trading_date: str = ""
    symbol: str = ""
    strategy: str = "ORB"
    side: str = "BUY"
    quantity: int = 0
    entry_time: str = ""
    entry_price: float = 0.0
    exit_time: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    gross_pnl: float = 0.0
    total_charges: float = 0.0
    net_pnl: float = 0.0
    return_pct: float = 0.0
    planned_sl: float = 0.0
    planned_tp: float = 0.0
    target_hit: bool = False
    stop_loss_hit: bool = False


@dataclass
class TradeJournalEntry:
    journal_id: str = field(default_factory=lambda: f"JRN-{uuid.uuid4().hex[:12].upper()}")
    trade_id: str = ""
    recommendation_id: str = ""
    trading_date: str = ""
    created_at: str = field(default_factory=lambda: now_ist().strftime("%Y-%m-%d %H:%M:%S IST"))
    symbol: str = ""
    company_name: str = ""
    sector: str = ""
    strategy: str = ""
    reasoning: str = ""
    confidence_score: float = 0.0
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: int = 0
    holding_duration_mins: int = 0
    stop_loss: float = 0.0
    target: float = 0.0
    risk_reward_ratio: float = 1.0
    gross_pnl: float = 0.0
    brokerage: float = 0.0
    stt: float = 0.0
    exchange_charges: float = 0.0
    gst: float = 0.0
    sebi_charges: float = 0.0
    stamp_duty: float = 0.0
    total_charges: float = 0.0
    net_pnl: float = 0.0
    return_pct: float = 0.0
    is_win: bool = False
    target_hit: bool = False
    stop_loss_hit: bool = False
    time_exit: bool = False
    exit_reason: str = ""


@dataclass
class PortfolioSnapshot:
    snapshot_id: str = field(default_factory=lambda: f"SNAP-{uuid.uuid4().hex[:12].upper()}")
    trading_date: str = ""
    timestamp: str = field(default_factory=lambda: now_ist().strftime("%Y-%m-%d %H:%M:%S IST"))
    starting_capital: float = 1_000_000.0
    available_cash: float = 1_000_000.0
    capital_deployed: float = 0.0
    realized_pnl_today: float = 0.0
    unrealized_pnl_today: float = 0.0
    total_net_pnl_cumulative: float = 0.0
    total_trades_today: int = 0
    open_positions_count: int = 0


@dataclass
class FailureAnalysis:
    analysis_id: str = field(default_factory=lambda: f"FAIL-{uuid.uuid4().hex[:12].upper()}")
    trade_id: str = ""
    recommendation_id: str = ""
    trading_date: str = ""
    symbol: str = ""
    strategy: str = ""
    root_cause_tags: list[str] = field(default_factory=list)
    notes: str = ""
    context_snapshot: dict = field(default_factory=dict)
