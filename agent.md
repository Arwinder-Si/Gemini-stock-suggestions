Intraday Algorithmic Trading System — Design Document
Project: NSE Intraday ORB Signal & Alert System
Prepared for: Arwinder Singh
Target build environment: Antigravity (Gemini)
Date: July 2026
---
1. Executive Summary
This document specifies the design of a Python-based intraday trading signal system for NSE equities, built around the DhanHQ broker API. The system ingests live market data via WebSocket, aggregates ticks into OHLCV candles, evaluates rule-based strategies (starting with Opening Range Breakout — ORB), and pushes trade signals to Telegram. It includes a companion backtesting engine that reuses the exact same strategy code used in live trading, and is designed to scale from a single strategy to multiple concurrent strategies via a producer-consumer queue architecture.
Important scope clarification: This is designed as a signal/alert generation and research system, not an auto-execution (order-placing) bot, in order to minimize regulatory exposure under SEBI's 2026 retail algo trading framework (see Section 9). Order execution can be added later as an explicit, opt-in extension once compliance requirements are satisfied.
---
2. Goals and Non-Goals
2.1 Goals
Ingest real-time NSE intraday market data (tick/quote level) via DhanHQ.
Aggregate ticks into 1-minute OHLCV candles per symbol.
Implement a modular strategy engine, starting with Opening Range Breakout (ORB).
Emit trade signals (direction, entry, stop-loss, target) with clear reasoning.
Deliver signals via Telegram bot in real time.
Support multiple concurrent strategies without one blocking another.
Provide an event-driven backtesting engine that reuses live strategy code.
Log all signals and (if available) trade outcomes for performance analysis.
2.2 Non-Goals (v1)
Automated order placement / execution (explicitly deferred; see Section 9).
Options/F&O strategies (equity intraday only for v1).
Multi-broker abstraction (Dhan-only for v1).
Portfolio-level risk netting across strategies (each strategy is independent in v1).
---
3. High-Level Architecture
```
                    ┌─────────────────────────┐
                    │   DhanHQ MarketFeed      │
                    │   (WebSocket, Quote mode)│
                    └───────────┬─────────────┘
                                │ raw tick/quote packets
                                ▼
                    ┌─────────────────────────┐
                    │  Candle Aggregator        │
                    │  (ticks → 1-min OHLCV)    │
                    └───────────┬─────────────┘
                                │ finalized Candle objects
                                ▼
                    ┌─────────────────────────┐
                    │   Fan-out Queue Layer      │
                    │  (per-strategy queues)     │
                    └──┬─────────────┬──────────┘
                       ▼             ▼
              ┌─────────────┐ ┌─────────────┐
              │ ORB Worker   │ │ Future        │
              │ (Strategy 1) │ │ Strategy N     │
              └──────┬───────┘ └──────┬────────┘
                     ▼                ▼
              ┌─────────────────────────────┐
              │   Signal Object (dataclass)   │
              └───────────────┬─────────────┘
                              ▼
                    ┌─────────────────────────┐
                    │   Telegram Notifier        │
                    │   + Signal Logger (DB/CSV) │
                    └─────────────────────────┘
```
3.1 Components
Component	Responsibility	Tech
MarketFeed Producer	Connects to Dhan WebSocket, receives ticks	DhanHQ-py, threading
Candle Aggregator	Converts ticks → per-symbol 1-min candles	Pure Python, dataclasses
Queue Layer	Decouples feed from strategy processing	`queue.Queue` (or `asyncio.Queue`)
Strategy Workers	Evaluate rules per candle, emit signals	Python classes, one thread per strategy
Telegram Notifier	Sends formatted alerts	`httpx` / `python-telegram-bot`
Signal Logger	Persists signals + outcomes	SQLite/Postgres or CSV (v1)
Backtest Engine	Replays historical candles through same strategy classes	pandas, custom event loop
Historical Data Loader	Pulls intraday candles from Dhan for backtesting	Dhan `/charts/intraday` REST API
---
4. Data Flow — Live Mode
Startup: Load config (symbols, security IDs, strategy params, credentials).
Feed connection: `MarketFeedProducer` thread starts, subscribes to configured NSE_EQ instruments in Quote mode.
Tick processing: Each incoming packet is parsed; `CandleAggregator` updates the in-progress candle for that symbol/minute.
Candle finalization: When a new minute begins, the previous candle is finalized and pushed into the fan-out queue(s).
Strategy evaluation: Each `StrategyWorker` thread pulls candles from its queue, feeds them into its strategy's `on_candle()` method.
Signal emission: If a strategy's rules are satisfied, a `Signal` object (symbol, direction, entry, SL, TP, reason) is created.
Delivery: Signal is sent to Telegram and written to the signal log (CSV/DB).
Shutdown: On market close or manual stop, feed connection is closed gracefully and any open state is flushed.
---
5. Data Flow — Backtest Mode
Historical data pull: `HistoricalDataLoader` fetches full-day intraday candles per symbol per date from Dhan's `/charts/intraday` endpoint.
Replay: `ORBBacktester` (or equivalent for other strategies) feeds each candle, in chronological order, through the same strategy class used live (`ORBBreakoutStrategy`).
Trade simulation: When a signal is emitted, a simulated `Trade` is opened; subsequent candles are checked against SL/TP/time-based exit rules.
Metrics: Completed trades are aggregated into a DataFrame; summary stats computed (win rate, average P&L%, max win/loss, total trades).
Output: Results written to `backtest_results.csv` for further analysis (e.g., in a notebook, or a dashboard).
Design principle: Backtest and live share strategy code. Only the "candle source" (WebSocket vs REST-historical) and "trade execution" (Telegram alert vs simulated fill) differ. This eliminates strategy-logic drift between test and production.
---
6. Strategy Specification — Opening Range Breakout (ORB)
6.1 Rules
Opening range window: 09:15–09:30 (configurable).
During this window, track running `high` and `low` per symbol — this defines the ORB range.
After 09:30, the range is "locked."
Long signal: candle close breaks above ORB high, with candle volume above a configured minimum threshold.
Short signal: candle close breaks below ORB low, with the same volume filter.
Stop-loss: opposite side of the ORB range (conservative).
Target: 1:1 risk-reward by default (configurable to 1:2, 1:3, etc.).
Trade management: one open trade per symbol per day (no re-entry after SL/TP hit, in v1).
Time-based exit: force-close any simulated/tracked position by 15:15 IST if neither SL nor TP is hit (avoids carrying intraday risk into close).
6.2 Parameters (configurable per symbol/strategy instance)
`orb_start`, `orb_end` (default 09:15–09:30)
`min_volume` threshold
`risk_reward_ratio` (default 1:1)
`time_exit` (default 15:15)
6.3 Known Limitations of ORB Specifically
Performs poorly in low-volatility, range-bound days — frequent false breakouts ("chop").
Highly sensitive to opening range window choice — 15 min vs 30 min windows can produce materially different signals.
Volume filters are heuristic; thin-volume midcaps can trigger false breakouts even above threshold.
No adjustment for overall market regime (e.g., high-VIX/event days) in v1 — this is a known future enhancement (see Section 11).
---
7. Backtesting Design Details
7.1 Data Source
Dhan's Historical Data API (`/v2/charts/intraday`) provides per-minute OHLCV for NSE_EQ instruments across a specified date range, keyed by `securityId`. This is the same schema used by the live REST fallback, ensuring consistency between backtest and any REST-based live testing.
7.2 Assumptions in v1 Backtest (Important — Read Risks Section)
No slippage modeling: Trades are assumed to fill exactly at signal price. Real fills will differ, especially on breakout candles with fast price movement.
No brokerage/tax modeling: P&L is gross, not net of brokerage, STT, or other charges.
No liquidity constraint modeling: Assumes full position size can be filled at the candle's close price — unrealistic for illiquid names or large size.
Single position per symbol per day: Does not model partial fills, scaling in/out, or multiple re-entries.
Survivorship bias risk: If your symbol universe is chosen based on today's liquid/large-cap names, backtests on historical data may overstate historical performance (some stocks may not have been as liquid/attractive in the past).
7.3 Metrics to Track
Win rate %, average P&L % per trade, total P&L %, max single win/loss, number of trades, average holding time, and (recommended addition) max drawdown and Sharpe-like ratio on the trade P&L series.
7.4 Future Enhancement: Vectorized Sweeps
For large-scale parameter optimization (e.g., testing ORB windows of 10/15/20/30 minutes across dozens of symbols and months of data), consider porting validated rules into a vectorized framework (e.g., vectorbt) for speed, while keeping the event-driven backtester as the "ground truth" correctness check.
---
8. Scalability & Performance Design
8.1 Producer-Consumer Queue Pattern
MarketFeed runs in its own thread, purely responsible for: connecting to WebSocket, aggregating ticks into candles, and pushing finalized candles into queue(s).
Each strategy runs in its own worker thread, consuming from its dedicated queue.
This isolates a slow/buggy strategy from blocking the live data feed or other strategies.
8.2 Performance Guidelines
Keep queued objects small and flat (plain dataclasses with primitive fields) — avoid pickling overhead if ever moving to multiprocessing.
Use threading + `queue.Queue` for v1 (I/O-bound workload, GIL is not a bottleneck for WebSocket I/O).
Consider `asyncio.Queue` with a single event loop as a future optimization if you want everything (feed + N strategies) in one process without OS thread overhead.
If a strategy becomes CPU-heavy (e.g., ML-based signal scoring), consider moving that specific strategy to a separate process with a high-performance IPC queue (e.g., `faster-fifo`), while keeping the feed and lightweight strategies on threads.
Set `maxsize` on all queues to detect and handle backpressure (a slow consumer should not silently balloon memory usage).
8.3 Scaling to More Strategies
Adding a new strategy requires only:
Implementing a new class with an `on_candle()` method (same interface as `ORBBreakoutStrategy`).
Creating a new queue.
Adding the queue to the feed's fan-out list.
Starting a new `StrategyWorker` thread wrapping the new strategy.
No changes are needed to the MarketFeed or Candle Aggregator code.
---
9. Regulatory & Compliance Considerations (SEBI, 2026) — CRITICAL SECTION
SEBI's retail algorithmic trading framework became mandatory for all brokers from April 1, 2026. This has direct implications for this project and must be read carefully before deploying anything beyond signal-generation.
9.1 Key Rules (as of April 2026)
Every algorithmic order must carry an exchange-assigned Algo-ID, allowing exchanges to trace the order back to a registered algorithm.
Open/unrestricted API access is prohibited. Order placement is only permitted through broker-approved, whitelisted API keys tied to a static IP address.
Static IP requirement: Orders are accepted only from a registered App ID mapped to a whitelisted static IP; unregistered/non-whitelisted IPs will have orders rejected. A static IP must be obtained from an ISP or a cloud provider (AWS/GCP) or VPN/VPC service.
Daily 2FA: Two-factor authentication must be completed once per trading day; continuous refresh-token sessions (i.e., "log in once, run forever") are not supported under the new framework.
Order rate limits: A maximum of ~10 orders per second is allowed via API; excess requests may be rejected.
Market orders are converted to MPP (Market Price Protection) orders automatically by the broker/exchange layer.
Self-developed algorithms can only be used for personal and immediate family accounts (self, spouse, dependent children, dependent parents) — commercial use or offering the algo/signals to third parties is not permitted without registering as an algo provider empanelled with the exchange.
Volume thresholds: If an algorithm's order flow crosses a specified orders-per-second threshold, registration with the exchange (through the broker) becomes mandatory, even for personal use.
Kill switch: Brokers must maintain the ability to immediately disable a malfunctioning algorithm; as a user, you should design your own manual "pause/kill" control as well (already included in the architecture via `stop()` methods).
9.2 Direct Implications for This Project
This project, as designed (signal generation + Telegram alerts, no auto order placement), sits outside the strictest parts of the framework, because it does not place orders via API. This is a deliberate design choice to reduce regulatory burden while you validate the strategy.
If you later add auto-execution (i.e., the system places real orders via Dhan's Order API), you will need to:
Register/whitelist a static IP with Dhan.
Ensure your app complies with daily 2FA (no indefinite background sessions).
Respect the ~10 orders/sec rate limit.
Confirm the algorithm is used only for your own/family accounts, not offered to others, unless you go through formal exchange empanelment.
Personal use only: Do not package and distribute this system (e.g., selling signals or offering it as a service to other traders) without registering as an algo provider — this requires Research Analyst registration for "black box" algos and exchange empanelment.
9.3 Recommendation
Treat v1 strictly as a research and alerting tool. Any move toward auto-execution should be scoped as a separate, explicitly-approved phase with its own compliance checklist (static IP setup, broker registration, 2FA flow, rate-limit handling).
---
10. Risks and Limitations (Non-Regulatory)
10.1 Strategy / Market Risks
ORB false breakouts: Choppy or low-volume days generate frequent false signals; expect a non-trivial losing streak even in a fundamentally sound strategy.
Backtest-to-live gap: Backtests assume ideal fills; real intraday slippage (especially on breakout candles, which by definition move fast) will reduce real P&L versus backtested P&L.
Overfitting risk: Tuning ORB window/volume thresholds too tightly on a small historical sample risks overfitting to noise rather than a persistent edge. Always validate on out-of-sample/rolling periods.
Regime risk: A strategy validated in trending markets may perform poorly in range-bound or highly volatile (news-driven) markets; v1 has no explicit regime filter.
10.2 Technical / Infrastructure Risks
WebSocket disconnections: Live feed reconnection logic must be robust; a dropped connection mid-session can cause missed candles/signals if not handled with retries and backoff.
Clock/timestamp drift: Candle bucketing depends on accurate, consistent timestamps (server vs local clock); recommend using exchange-provided timestamps (LTT) rather than local wall-clock time wherever possible.
Queue backpressure: Under high tick volume (e.g., volatile market opens), if a strategy worker is slow, its queue can build up; without bounded queues and monitoring, this can silently delay or drop signals.
API rate limits / quota: Dhan's historical and live APIs have their own rate limits; large backtest data pulls should be throttled and cached locally (CSV/Parquet) to avoid hitting limits repeatedly.
Credential security: Access tokens and client IDs must be stored securely (e.g., environment variables, secrets manager) — never hard-coded or committed to source control.
10.3 Operational Risks
No auto risk controls in v1: There is no automatic daily loss-limit or max-trades-per-day circuit breaker built into the alerting logic yet; this should be added before increasing position sizes or trade frequency (recommended as a Phase 2 item).
Alert fatigue: If thresholds are too loose, high signal frequency can lead to alert fatigue and impulsive manual execution errors.
Single point of failure: In v1, the system runs as a single process/host; no redundancy or failover is designed in. A crash during market hours means missed signals until manually restarted.
10.4 Data Risks
Survivorship and universe bias in backtests (see 7.2).
Corporate actions (splits, bonuses, dividends) can distort historical price/volume data if not adjusted for; verify Dhan's historical data handles adjustments or apply your own adjustment logic.
---
11. Phased Build Plan
Phase 1 — Core Pipeline (Weeks 1–2)
Implement config, DhanHQ REST-based intraday data client (polling), ORB strategy, Telegram notifier.
Validate against 2–3 liquid large-cap symbols (e.g., INFY, TCS, HDFCBANK) in a paper-tracking mode (no real capital).
Phase 2 — Real-Time Feed + Queue Architecture (Weeks 3–4)
Replace REST polling with DhanHQ MarketFeed WebSocket.
Implement CandleAggregator, fan-out queue layer, threaded StrategyWorker.
Add signal logging (CSV → migrate to SQLite/Postgres).
Phase 3 — Backtesting Engine (Weeks 4–5)
Build HistoricalDataLoader + event-driven ORBBacktester reusing live strategy code.
Run backtests across multiple symbols/date ranges; produce win-rate, P&L, drawdown metrics.
Iterate on ORB parameters (window, volume threshold, R:R) based on results — with out-of-sample validation.
Phase 4 — Risk Controls & Monitoring (Week 6)
Add daily loss-limit / max-signal-count circuit breakers.
Add health-check/alerting for feed disconnects, queue backlog, and process crashes.
Add a simple dashboard (FastAPI + basic HTML/Streamlit) showing today's signals and system health.
Phase 5 — Additional Strategies (Ongoing)
Add new strategies (price+volume breakout, ATR-based volatility filter, momentum) as independent classes/workers.
Consider regime filters (e.g., only trade ORB on days with above-average expected volatility).
Phase 6 — (Optional, Separate Compliance Track) Execution Layer
Only after Phases 1–4 are stable and validated: evaluate adding auto order placement via Dhan Order API.
Requires explicit SEBI-compliance setup: static IP, daily 2FA flow, rate-limit-aware order logic, personal-use-only scope.
---
12. Success Criteria for v1
System runs unattended through a full trading session without crashing or missing >X% of expected candles (target: <1% missed candles).
Backtest and live signal logic produce identical outputs when fed the same historical candle sequence (verifies backtest-live parity).
At least 4–6 weeks of live paper-signal tracking completed before considering any capital deployment.
Clear, reviewed risk-control rules (max daily signals, max risk per idea) documented and enforced in code, not just manually.
---
13. Open Questions to Resolve During Build
Final symbol universe for v1 (recommend starting with 5–10 liquid large-caps).
Exact volume threshold and ORB window to start with (recommend beginning with published defaults, then tuning via backtest).
Where signal logs will live long-term (CSV during prototyping, Postgres/SQLite once stable).
Whether a lightweight web dashboard is needed in v1 or can wait until Phase 4.
---
End of document.