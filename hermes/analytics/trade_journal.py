"""
Trade Journal builder module.
Constructs itemized TradeJournalEntry documents for persistence upon paper/live trade completion.
"""

from hermes.data.analytics_models import TradeJournalEntry, Recommendation, PaperTrade
from hermes.domain.costs import CostModel, Side
from hermes.clock import now_ist, trading_date_ist


def build_trade_journal_entry(
    rec: Recommendation,
    paper_trade: PaperTrade,
    cost_model: CostModel | None = None,
) -> TradeJournalEntry:
    """
    Constructs a rich, itemized TradeJournalEntry from recommendation and paper trade execution.
    """
    cm = cost_model or CostModel()

    # Re-calculate exact itemized charges
    side = Side.BUY if paper_trade.side == "BUY" else Side.SELL
    entry_ch = cm.charges(paper_trade.entry_price, paper_trade.quantity, side)
    exit_side = Side.SELL if side == Side.BUY else Side.BUY
    exit_ch = cm.charges(paper_trade.exit_price, paper_trade.quantity, exit_side)

    total_brokerage = entry_ch.brokerage + exit_ch.brokerage
    total_stt = entry_ch.stt + exit_ch.stt
    total_exchange = entry_ch.exchange_txn_charge + exit_ch.exchange_txn_charge
    total_gst = entry_ch.gst + exit_ch.gst
    total_sebi = entry_ch.sebi_charge + exit_ch.sebi_charge
    total_stamp = entry_ch.stamp_duty + exit_ch.stamp_duty

    # Calculate holding duration
    try:
        from datetime import datetime
        t_entry = datetime.strptime(paper_trade.entry_time, "%Y-%m-%d %H:%M:%S IST")
        t_exit = datetime.strptime(paper_trade.exit_time, "%Y-%m-%d %H:%M:%S IST")
        duration_mins = int((t_exit - t_entry).total_seconds() / 60)
    except Exception:
        duration_mins = 0

    return TradeJournalEntry(
        trade_id=paper_trade.trade_id,
        recommendation_id=rec.recommendation_id,
        trading_date=paper_trade.trading_date or trading_date_ist().strftime("%Y-%m-%d"),
        symbol=paper_trade.symbol,
        company_name=rec.company_name or paper_trade.symbol,
        sector=rec.sector or "Other",
        strategy=paper_trade.strategy,
        reasoning=rec.reasoning,
        confidence_score=rec.confidence_score,
        entry_price=paper_trade.entry_price,
        exit_price=paper_trade.exit_price,
        quantity=paper_trade.quantity,
        holding_duration_mins=duration_mins,
        stop_loss=rec.stop_loss,
        target=rec.target_price,
        risk_reward_ratio=rec.risk_reward_ratio,
        gross_pnl=paper_trade.gross_pnl,
        brokerage=round(total_brokerage, 2),
        stt=round(total_stt, 2),
        exchange_charges=round(total_exchange, 2),
        gst=round(total_gst, 2),
        sebi_charges=round(total_sebi, 4),
        stamp_duty=round(total_stamp, 2),
        total_charges=paper_trade.total_charges,
        net_pnl=paper_trade.net_pnl,
        return_pct=paper_trade.return_pct,
        is_win=(paper_trade.net_pnl > 0),
        target_hit=(paper_trade.exit_reason == "TP Hit"),
        stop_loss_hit=(paper_trade.exit_reason == "SL Hit"),
        time_exit=(paper_trade.exit_reason == "Time Exit"),
        exit_reason=paper_trade.exit_reason,
    )
