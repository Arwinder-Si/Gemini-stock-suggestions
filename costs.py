"""
Indian equity transaction cost model (Dhan defaults).
Provides itemized breakdown for brokerage, STT, Exchange charges, GST, SEBI charges, Stamp duty, and slippage.
"""

from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class ChargeBreakdown:
    turnover: float
    brokerage: float
    stt: float
    exchange_txn_charge: float
    gst: float
    sebi_charge: float
    stamp_duty: float
    slippage: float
    total_charges: float
    net_amount: float  # For BUY: turnover + total_charges; For SELL: turnover - total_charges

    @property
    def charges_without_slippage(self) -> float:
        return self.total_charges - self.slippage


@dataclass(frozen=True)
class CostModel:
    brokerage_per_order: float = 20.0        # ₹20 flat or cap
    brokerage_pct_cap: float = 0.0003         # 0.03% max brokerage
    stt_pct_sell: float = 0.00025            # 0.025% on sell side for intraday
    exchange_txn_pct: float = 0.0000345       # NSE 0.00345%
    gst_pct: float = 0.18                    # 18% on (brokerage + exchange txn)
    sebi_charges_per_crore: float = 10.0      # ₹10 per crore turnover (0.000001)
    stamp_duty_pct_buy: float = 0.00003      # 0.003% on buy side
    slippage_bps: float = 5.0                # 5 bps (0.05%) default per leg

    def charges(self, price: float, qty: int, side: Side) -> ChargeBreakdown:
        """Calculate itemized transaction charges for a single order leg."""
        if qty <= 0 or price <= 0:
            return ChargeBreakdown(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

        turnover = price * qty

        # Brokerage: lower of flat rate or % cap
        brokerage = min(self.brokerage_per_order, turnover * self.brokerage_pct_cap)

        # STT: intraday STT is charged ONLY on sell side (0.025%)
        stt = (turnover * self.stt_pct_sell) if side == Side.SELL else 0.0

        # Exchange transaction charges
        exchange_txn_charge = turnover * self.exchange_txn_pct

        # GST: 18% on (brokerage + exchange txn charge)
        gst = (brokerage + exchange_txn_charge) * self.gst_pct

        # SEBI Turnover Charges: ₹10 / crore
        sebi_charge = (turnover / 10_000_000.0) * self.sebi_charges_per_crore

        # Stamp Duty: charged ONLY on buy side (0.003%)
        stamp_duty = (turnover * self.stamp_duty_pct_buy) if side == Side.BUY else 0.0

        # Slippage: bps converted to ratio
        slippage = turnover * (self.slippage_bps / 10_000.0)

        total_charges = brokerage + stt + exchange_txn_charge + gst + sebi_charge + stamp_duty + slippage
        
        if side == Side.BUY:
            net_amount = turnover + total_charges
        else:
            net_amount = turnover - total_charges

        return ChargeBreakdown(
            turnover=round(turnover, 2),
            brokerage=round(brokerage, 2),
            stt=round(stt, 2),
            exchange_txn_charge=round(exchange_txn_charge, 2),
            gst=round(gst, 2),
            sebi_charge=round(sebi_charge, 4),
            stamp_duty=round(stamp_duty, 2),
            slippage=round(slippage, 2),
            total_charges=round(total_charges, 2),
            net_amount=round(net_amount, 2),
        )

    def round_trip(self, entry_price: float, exit_price: float, qty: int, entry_side: Side = Side.BUY) -> tuple[ChargeBreakdown, ChargeBreakdown, float, float]:
        """
        Calculate total round-trip costs and gross vs net P&L.
        Returns: (entry_breakdown, exit_breakdown, gross_pnl, net_pnl)
        """
        exit_side = Side.SELL if entry_side == Side.BUY else Side.BUY
        entry_charges = self.charges(entry_price, qty, entry_side)
        exit_charges = self.charges(exit_price, qty, exit_side)

        if entry_side == Side.BUY:
            gross_pnl = (exit_price - entry_price) * qty
        else:
            gross_pnl = (entry_price - exit_price) * qty

        total_cost = entry_charges.total_charges + exit_charges.total_charges
        net_pnl = round(gross_pnl - total_cost, 2)

        return entry_charges, exit_charges, round(gross_pnl, 2), net_pnl

    def apply_slippage(self, price: float, side: Side, is_entry: bool = True) -> float:
        """Apply directional slippage to execution price. BUYing is adverse if higher, SELLing is adverse if lower."""
        slippage_ratio = self.slippage_bps / 10_000.0
        if side == Side.BUY:
            return round(price * (1.0 + slippage_ratio), 2)
        else:
            return round(price * (1.0 - slippage_ratio), 2)
