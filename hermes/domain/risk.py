"""
Pre-trade Risk Engine.
Enforces daily trade caps, daily loss limits, position sizing, sector exposure, and duplicate entry blocks.
"""

from dataclasses import dataclass, field
import logging
from hermes.domain.orders import Order, OrderSide
from hermes.data.analytics_models import Recommendation

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    max_daily_trades: int = 5
    max_daily_loss_rupees: float = 10_000.0
    risk_per_trade_pct: float = 0.01  # 1% of portfolio risk per trade
    max_sector_exposure_pct: float = 0.30  # 30% max sector allocation
    allow_reentry: bool = False
    min_confidence_score: float = 0.0


class RiskEngine:
    """Pre-trade risk gate ensuring no risk rules are breached prior to order submission."""

    def __init__(self, config: RiskConfig | None = None):
        self.cfg = config or RiskConfig()

    def validate_recommendation(
        self,
        rec: Recommendation,
        current_daily_trades: int,
        realized_pnl_today: float,
        portfolio_value: float,
        open_positions: list[dict],
        completed_symbols_today: set[str],
    ) -> tuple[bool, str, int]:
        """
        Validates if a recommendation passes all pre-trade risk checks.
        Returns: (passed: bool, reason: str, position_size_qty: int)
        """
        # 1. Max daily trade count
        if current_daily_trades >= self.cfg.max_daily_trades:
            msg = f"Rejected: Max daily trade count limit reached ({current_daily_trades}/{self.cfg.max_daily_trades})."
            logger.warning(msg)
            return False, msg, 0

        # 2. Max daily loss limit
        if realized_pnl_today <= -self.cfg.max_daily_loss_rupees:
            msg = f"Rejected: Max daily loss limit breached (P&L: ₹{realized_pnl_today:.2f} <= -₹{self.cfg.max_daily_loss_rupees})."
            logger.warning(msg)
            return False, msg, 0

        # 3. Duplicate symbol check
        existing_open = any(pos["symbol"] == rec.symbol for pos in open_positions)
        if existing_open or (not self.cfg.allow_reentry and rec.symbol in completed_symbols_today):
            msg = f"Rejected: Position already exists or re-entry disabled for {rec.symbol}."
            logger.warning(msg)
            return False, msg, 0

        # 4. Confidence score gate
        if rec.confidence_score < self.cfg.min_confidence_score:
            msg = f"Rejected: Confidence score {rec.confidence_score} below minimum threshold {self.cfg.min_confidence_score}."
            logger.warning(msg)
            return False, msg, 0

        # 5. Sector exposure check
        sector_capital = sum(pos["value"] for pos in open_positions if pos.get("sector") == rec.sector)
        max_sector_cap = portfolio_value * self.cfg.max_sector_exposure_pct
        if sector_capital >= max_sector_cap:
            msg = f"Rejected: Max sector exposure limit reached for {rec.sector} (₹{sector_capital:.2f} >= ₹{max_sector_cap:.2f})."
            logger.warning(msg)
            return False, msg, 0

        # 6. Position Sizing based on SL distance
        sl_distance = abs(rec.entry_price - rec.stop_loss)
        if sl_distance <= 0:
            msg = "Rejected: Invalid stop loss price (SL distance is 0)."
            logger.warning(msg)
            return False, msg, 0

        risk_capital_rs = portfolio_value * self.cfg.risk_per_trade_pct
        qty = int(risk_capital_rs / sl_distance)
        if qty <= 0:
            msg = "Rejected: Calculated position size quantity is 0."
            logger.warning(msg)
            return False, msg, 0

        logger.info(f"Risk gate PASSED for {rec.symbol}. Size: {qty} shares (Risk ₹{risk_capital_rs:.2f}).")
        return True, "PASSED", qty
