# Autonomous Trading Agent — Roadmap

**Project:** Gemini Stock Suggestions (Hermes)  
**Date:** July 2026  
**Status:** Draft — signal/alert system today; autonomous agent is the target state

This document captures a repo-wide audit and a phased plan to evolve the current NSE intraday signal system into an **autonomous trading agent**. It complements the technical design in [`agent.md`](../agent.md), which covers architecture, ORB strategy, backtesting assumptions, and SEBI compliance.

---

## Executive Summary

The codebase is a **well-architected signal and alerting system**, not yet an autonomous agent. Roughly **30% of the work toward autonomy is done** (data pipeline, live feed, strategy decoupling, ops tooling). The remaining **70%** is not “wire up the broker API” — it is the **position state machine, risk engine, order lifecycle, and validated edge** that must exist before any real execution.

**Critical finding:** You cannot yet trust that the strategy is profitable, and you currently **lack the data to find out**. The ORB backtest models zero costs, runs one symbol at a time, and has no historical candle store — while `market_feed.py` discards every 1-min candle it builds. At 1:1 risk-reward, realistic friction pushes breakeven to roughly a 55–60% win rate, which is a demanding bar for ORB. Phase 0 exists to answer this question with enough data to be believed, and it may well answer "no".

**Paper trading validates execution, not edge.** Phase 2–3 build a mock trading engine and trade journal to prove that live fills, slippage, and charges match the model — with no broker APIs — before Phase 4. Expectancy is established in Phase 0 by backtest, because a 4–6 week paper run yields at most ~150 trades and cannot resolve a 5-point difference in win rate.

---

## Current System (As-Is)

### What exists today

```
Evening pipeline (3:45 PM IST)
  news_sentiment.py → news_features.csv
  comprehensive_screener.py → screener_results.csv
  intraday_trigger.py → trade_plan.json
  notify_webex.py evening

Morning pipeline (8:30 AM IST)
  global_signals.py → market_data.db
  notify_webex.py morning

Live intraday (9:00 AM IST, VM cron)
  main.py → Dhan WebSocket → ORBBreakoutStrategy → Webex alert + signals.csv
  (NO order placement)

ChatOps
  webex_listener.py → /ping, /pnl, /plan, /morning (polling or webhook mode)
```

### Module map

| Area | Key files | Role |
|------|-----------|------|
| Live engine | `main.py`, `market_feed.py`, `strategy.py`, `notifier.py` | WebSocket → candles → ORB signals → alerts |
| Evening data | `comprehensive_screener.py`, `news_sentiment.py`, `intraday_trigger.py` | Stock selection → trade plan |
| Backtest | `backtest.py`, `screener_backtest.py`, `nse_backtester.py` | ORB replay, screener validation, research strategies |
| Persistence | `market_db.py`, `logger.py`, CSV/JSON artifacts | SQLite history, signal log |
| Ops | `setup_vm.sh`, `webex_listener.py`, GitHub Actions | VM cron, ChatOps, scheduled screener |

---

## What We're Doing Well

### 1. Architecture

- **Producer–consumer pattern** with bounded queues (`main.py`, `market_feed.py`) — feed isolation from strategy workers.
- **Strategy decoupled from config** — `ORBBreakoutStrategy` takes `ORBConfig`, same class in live and backtest.
- **Plain dataclasses** on queues (`models.py`) — low overhead, easy to test.
- **Graceful shutdown** — SIGINT/SIGTERM, feed reconnect with exponential backoff.

### 2. Security and ops

- Secrets in `.env`, gitignored; pydantic-settings lazy singleton.
- TOTP-based Dhan token refresh (`auth_manager.py`).
- ChatOps with polling fallback for corporate/firewalled VMs.
- Systemd service + cron for 24/7 operation.

### 3. Documentation and compliance awareness

- [`agent.md`](../agent.md) documents SEBI 2026 framework, backtest limitations, and phased build plan.
- Live system **intentionally alert-only** — no broker order placement (compliance by design).

### 4. Test coverage (partial)

- 30+ unit tests: ORB strategy, candle aggregator, Webex listener, auth client factory.
- **Gap:** no tests on backtesters, screener, or end-to-end agent loop; CI does not run pytest.

---

## The Core Gap: Signals vs. Agency

| Capability | Today | Needed for autonomy |
|------------|-------|---------------------|
| Position state | None | Track open positions, entry, size, exposure |
| Order lifecycle | None | submitted → acked → partial → filled → rejected |
| Reconciliation | None | Broker is source of truth on every restart |
| Risk gate | None | Pre-trade checks before every order |
| Exit management | Backtest only | Live never manages SL/TP after alert |
| Circuit breakers | None | Daily loss limit, max trades, max exposure |
| Audit trail | `signals.csv` | Every decision and order, immutable |

**Backtest–live parity today:** Entry logic is shared (`ORBBreakoutStrategy.on_candle`). Exit simulation exists only in `ORBBacktester._manage_trade` (`backtest.py`) — live code does not track positions after firing an alert.

---

## Issues to Fix (By Severity)

### Tier 1 — Would lose money if automated today

1. **Stale trade plan** — Empty screener run does not overwrite `screener_results.csv`; missing CSV leaves old plan. Empty `trade_plan.json` falls back to `.env` symbols in `config.security_id_map` — agent could trade wrong universe silently.
2. **No risk controls** — No daily loss limit, position sizing, or max exposure.
3. **Local clock for candles** — `market_feed.py` uses `datetime.now()` instead of exchange LTT; ORB boundaries can be wrong.
4. **`nse_eq_mapping.json` not in CI** — Gitignored; `update_security_ids.py` not wired into evening workflow; fresh deploy breaks `intraday_trigger.py`.
5. **Timezone inconsistency** — CI (UTC) vs VM (IST); SQLite date keys use naive `datetime.now()`.

### Tier 2 — Cannot trust the numbers

1. **Backtest: zero costs** — No brokerage, STT, slippage, or impact.
2. **Screener backtest lookahead** — Entry at signal-day close (optimistic); should be next-day open.
3. **Screener logic drift** — `screener_backtest.py` duplicates scoring but omits regime/VIX/news modifiers from production screener.
4. **Hand-tuned weights** — Scoring described as “empirical” but not fitted in code.
5. **CI never runs tests** — Workflows run production logic on schedule without pytest gate.

### Tier 3 — Engineering hygiene

- 152-stock universe copy-pasted in 3 files.
- `breakout_screener.py` appears unused (dead code).
- `market_data.db` committed to git (merge conflict risk).
- Per-stock screener failures swallowed (`except: pass`).
- Half-pinned dependencies, no lockfile; `nse_backtester.py` deps missing from `requirements.txt`.

---

## Compliance Reality (SEBI 2026)

Before live auto-execution (Phase 4), confirm with Dhan:

| Requirement | Implication |
|-------------|-------------|
| Algo-ID on every order | Exchange registration via broker |
| Static IP whitelisting | VM must use registered IP for order API |
| Daily 2FA | No indefinite background sessions — verify TOTP satisfies broker policy |
| ~10 orders/sec cap | Rate limiter required |
| Personal/family use only | No commercial signal distribution without empanelment |

**Daily 2FA vs. “fully autonomous”:** Programmatic TOTP may satisfy auth, but operational design must handle session expiry and refused orders during the trading day.

See [`agent.md` §9](../agent.md) for full detail.

---

## Target Architecture (To-Be)

```
┌─────────────────────────────────────────────────────────────────┐
│                        AGENT LOOP (main.py)                      │
│  Candle → Strategy → RiskEngine → Sizer → OrderRouter → Broker  │
│              ↓                              ↓                    │
│       PositionManager ←────────── Portfolio (reconciled)         │
│              ↓                                                   │
│    AuditLog (SQLite ops) + AnalyticsStore → MongoDB (analytics)  │
└─────────────────────────────────────────────────────────────────┘
         ↑                              ↑
   MarketFeedProducer              PaperBroker | DhanBroker
   (live ticks)                   (Phase 2)     (Phase 4)

Post-session: outcome_enricher → evaluations + failure_analysis
              market_snapshot_job → daily benchmarks
              trade_journal_report → daily journal + equity curve
              analytics_report → weekly/monthly learning reports
```

**Design principle:** Backtest and live share the same `PositionManager`, `CostModel`, and `RiskEngine` — not duplicate exit logic.

The **Trading Analytics & Continuous Learning** layer (see below) sits alongside the agent loop: every recommendation is persisted at creation time, enriched with market outcomes after the trade window, and evaluated for continuous improvement.

The **Paper Trading & Trade Journal** engine (see below) is how we validate the agent **before any broker API** — simulated execution on live prices, full Indian cost modeling, and every trade persisted to MongoDB.

---

## Trading Analytics & Continuous Learning Framework

### Objective

Build a comprehensive analytics layer so every recommendation can be **measured, evaluated, and improved over time**. The agent should become **data-driven** — learning from historical outcomes, not relying solely on live P&L or gut feel.

Today, persistence is fragmented: `signals.csv` (live alerts), `market_data.db` (SQLite screener/news/gap history), and CSV artifacts. That is enough for ops, not enough for systematic improvement. This framework defines the target state.

### Database

- Integrate **MongoDB** as the **primary analytics database**.
- Design a clean, normalized document schema with proper indexing for efficient querying and reporting.
- Keep the database layer **modular** via a repository interface (`AnalyticsStore` protocol) so MongoDB can be replaced or extended (e.g. TimescaleDB, BigQuery) without rewriting the agent.

**Relationship to existing SQLite (`market_db.py`):**

| Store | Role |
|-------|------|
| SQLite (`market_db.py`) | Operational history on the VM — screener snapshots, gap predictions, lightweight cron state. Can remain or migrate later. |
| MongoDB | Long-lived analytics — recommendations, outcomes, evaluations, benchmarks, failure analysis, report aggregates. |

Do not duplicate writes indefinitely; new recommendation/outcome data goes to MongoDB. Existing SQLite tables can be backfilled once during migration.

#### Proposed collections (MongoDB)

| Collection | Purpose | Key indexes |
|------------|---------|-------------|
| `recommendations` | One doc per agent recommendation at creation time | `{ trading_date, symbol }`, `{ strategy, trading_date }`, `{ created_at }` |
| `recommendation_outcomes` | Market result after trade window completes | `{ recommendation_id }` (unique), `{ trading_date }` |
| `recommendation_evaluations` | Success/failure label + metrics | `{ recommendation_id }`, `{ outcome: 1, trading_date: -1 }` |
| `failure_analyses` | Root-cause tags and notes for unsuccessful trades | `{ recommendation_id }`, `{ root_causes: 1 }` |
| `market_snapshots` | Daily benchmark data (gainers, losers, sectors, indices) | `{ trading_date }` (unique) |
| `performance_rollups` | Pre-aggregated weekly/monthly stats (optional, for fast dashboards) | `{ period_type, period_start }` |
| `paper_trades` | Executed simulated trades (fills, charges, outcome) | `{ trade_id }` (unique), `{ trading_date, symbol }`, `{ strategy }` |
| `trade_journal` | Human-readable journal entry per completed trade | `{ trade_id }` (unique), `{ trading_date: -1 }` |
| `portfolio_snapshots` | End-of-day / intraday virtual portfolio state | `{ trading_date, snapshot_type }` |
| `daily_summaries` | Aggregated daily P&L and stats | `{ trading_date }` (unique) |
| `weekly_summaries` | Weekly rollups | `{ week_start }` (unique) |
| `monthly_summaries` | Monthly rollups | `{ month_start }` (unique) |

#### Modular interface (sketch)

```python
# analytics_store.py — Protocol only; MongoDB impl in analytics_mongo.py

class AnalyticsStore(Protocol):
    def save_recommendation(self, rec: Recommendation) -> str: ...
    def save_paper_trade(self, trade: PaperTrade) -> None: ...
    def save_journal_entry(self, entry: TradeJournalEntry) -> None: ...
    def save_portfolio_snapshot(self, snapshot: PortfolioSnapshot) -> None: ...
    def save_outcome(self, outcome: RecommendationOutcome) -> None: ...
    def save_evaluation(self, evaluation: RecommendationEvaluation) -> None: ...
    def save_failure_analysis(self, analysis: FailureAnalysis) -> None: ...
    def save_market_snapshot(self, snapshot: MarketSnapshot) -> None: ...
    def get_recommendations(self, filters: RecommendationQuery) -> list[Recommendation]: ...
```

Agent code depends on the protocol, not on pymongo directly.

---

### Data to Capture

For **every recommendation** generated by the trading agent, persist all relevant information.

#### Trade metadata

| Field | Description |
|-------|-------------|
| Timestamp | ISO 8601 with timezone (IST) |
| Trading session | Date + session type (pre-market, regular, post) |
| Stock symbol | NSE ticker |
| Company name | Human-readable name |
| Sector | From universe/sector map |
| Strategy used | e.g. `ORB`, `SCREENER_V3`, composite agent strategy |
| Reasoning | Agent/strategy explanation (ORB reason string, score breakdown) |
| Confidence score | 0–100 or normalized 0–1 where applicable |
| Supporting indicators | Feature snapshot: RSI, vol ratio, ORB high/low, regime modifier, news sentiment, etc. |
| Market conditions | Nifty trend, VIX bucket, gap prediction, regime label at recommendation time |

#### Trade recommendation

| Field | Description |
|-------|-------------|
| Action | Buy / Sell / Hold (maps to LONG / SHORT / no trade) |
| Recommended entry price | From signal or screener close |
| Suggested stop loss | From strategy |
| Suggested target(s) | Primary TP; optional ladder |
| Risk-reward ratio | Computed from entry, SL, TP |
| Expected holding period | e.g. intraday until 15:15 IST |

#### Market outcome (after trade window completes)

Captured by a **post-session job** (`outcome_enricher.py`) using Dhan/yfinance intraday or EOD data:

| Field | Description |
|-------|-------------|
| Actual entry price | Paper/live fill or proxy (next tick / open) |
| Highest price reached | Intraday high during window |
| Lowest price reached | Intraday low during window |
| Closing price | Session close or exit price |
| Maximum gain (%) | From entry to high |
| Maximum drawdown (%) | From entry to low |
| Final P&L | Net of costs where applicable |
| Target / SL hit | Boolean flags + which fired first |
| Trade duration | Minutes from entry to exit |

Link outcome to recommendation via stable `recommendation_id`.

---

### Market benchmarking

For **every trading day**, store a `market_snapshots` document:

- Top gainers and top losers (universe or Nifty 500 subset)
- Sector-wise performance (aggregated returns)
- Index performance (Nifty 50, Bank Nifty, India VIX level)
- Overall market sentiment (gap bias, advance/decline if available)

This enables comparison: *Did the agent pick names that actually moved? Did it beat the index and sector on the same day?*

Populate from existing pipelines where possible (`global_signals.py`, screener universe, yfinance EOD batch).

---

### Performance evaluation

Every recommendation should eventually receive an **evaluation** record:

| Outcome label | Meaning |
|---------------|---------|
| Successful | Target hit or P&L above threshold |
| Partially successful | Positive but below target / exited early |
| Failed | Stop loss or negative P&L |
| Missed opportunity | Hold/no trade but symbol moved favorably |
| False positive | Signal fired but conditions invalidated quickly |
| False negative | No signal but setup would have worked |

**Measurable metrics** (stored on evaluation or rollup):

- Accuracy (labeled correct / total labeled)
- Win rate
- Average return / average loss
- Sharpe ratio (optional, on rolling windows)
- Maximum drawdown
- Profit factor

Evaluation can be **rule-based initially** (TP/SL/P&L thresholds); ML-based labeling is a future enhancement.

---

### Failure analysis

For every unsuccessful trade, capture **why** it failed whenever identifiable:

| Root cause (tag) | Example |
|------------------|---------|
| Incorrect trend prediction | Breakout against broader trend |
| Weak entry timing | Late entry after move exhausted |
| Poor stop-loss placement | SL too tight for volatility |
| Incorrect target estimation | TP unreachable in session |
| News/event impact | Negative headline intraday |
| High volatility | VIX spike / whipsaw |
| Low confidence prediction | Score below threshold but traded |
| Strategy-specific failure | ORB chop day |
| Market regime mismatch | Bear regime long breakout |
| Other | Free-text note |

Store multiple tags per trade plus optional `context_snapshot` (same indicators as at recommendation time) so failures can be queried and clustered later.

---

### Periodic analytics

Generate **weekly and monthly reports** (script: `analytics_report.py` → Webex and/or HTML/JSON export):

- Which strategies perform best / lose consistently?
- Which sectors produce the highest returns?
- What market conditions are most favorable?
- What common mistakes does the agent make?
- Which indicators correlate with profitable trades?
- Do confidence scores predict outcomes?
- Concrete suggestions to improve the recommendation engine

Reports read from MongoDB aggregations; optional `performance_rollups` collection for speed.

---

### Future learning

The analytics database is a **historical knowledge base** for:

- Backtesting against **historical recommendations** (not just price replay)
- Strategy comparison on real agent output
- Performance trend analysis over time
- Identification of recurring mistakes (failure tag frequency)
- Feature importance analysis (which indicators matter)
- Fine-tuning or retraining future models on labeled outcomes

No ML pipeline is required in v1 — **capture everything first**, analyze second, model third.

---

### Engineering principles

- Capture **every meaningful data point** that could improve the agent later.
- Design schema for **scalability and query patterns** (date + strategy + sector filters).
- Keep implementation **clean and modular** — `AnalyticsStore` protocol, thin write path from agent.
- **Avoid over-engineering** — start with append-only writes and batch enrichment; add rollups when queries slow down.
- Architecture must support future **dashboards, ML, and automated reporting** without a redesign.

---

### Analytics implementation phases (within roadmap)

| When | What |
|------|------|
| **Phase 2** | `analytics_store.py` + MongoDB impl; persist recommendation + metadata on every signal; **Paper Trading Engine** + trade journal writes; `Recommendation` model aligned with `Signal` + screener `ScoreResult` |
| **Phase 3** | `outcome_enricher.py` nightly job; market snapshots; rule-based evaluations; failure analysis; **daily/weekly/monthly journal reports**; 4–6 week paper validation |
| **Phase 5** | Weekly/monthly `analytics_report.py`; ChatOps `/stats`, `/journal`; optional FastAPI read API for dashboards |
| **Future** | Feature importance, ML retraining export, automated weight tuning proposals, reinforcement learning feedback loops |

---

## Paper Trading & Trade Journal Framework

### Objective

Before integrating with any broker API, build our own **Paper Trading (Mock Trading) Engine** to validate and improve the trading agent in a controlled environment **without risking real capital**.

The paper engine simulates real-world trading as closely as possible while remaining modular enough to swap in live broker execution later. **MongoDB is the central source of truth** for every simulated trade, journal entry, and portfolio snapshot.

**Relationship to other components:**

| Component | Role |
|-----------|------|
| `broker.py` (Protocol) | Shared interface — `PaperBroker` today, `DhanBroker` in Phase 4 |
| `paper_broker.py` | Mock execution against live Dhan feed prices |
| `costs.py` | Indian equity charge breakdown (brokerage, STT, GST, etc.) |
| `risk.py` | Daily trade cap, loss limit, sizing, sector exposure |
| `position_manager.py` | SL / TP / time / EOD exits — shared with backtest |
| `AnalyticsStore` | Recommendations + evaluations (analytics section) |
| Trade journal | One rich document per completed paper trade linking recommendation → execution → outcome |

Paper trading is **Phase 2 deliverable** and **Phase 3 validation vehicle**. No broker order APIs until Phase 4.

---

### Core requirements

- **No broker APIs** at this stage — all execution inside the application.
- **Live market prices** for fills (Dhan WebSocket LTP on incoming ticks/candles).
- **Every simulated trade** persisted to MongoDB — nothing discarded.
- **Same `Broker` interface** as future live implementation — switch modes with minimal code change (`--mode paper` vs `--mode live`).

---

### Daily trading rules

The agent must take **high-conviction setups only**, not force trades.

| Rule | Default / notes |
|------|-----------------|
| Max trades per day | **4–5** (configurable via `MAX_DAILY_TRADES`) |
| Max daily loss | Configurable rupee or % of starting capital |
| Position sizing | From SL distance + `risk_per_trade_pct` |
| Capital allocation | Max % of equity per single position |
| Max exposure per sector | Prevent over-concentration (e.g. 2 names same sector) |
| Duplicate entries | **Blocked** — one open position per symbol per day unless strategy explicitly allows re-entry |
| Min confidence | Optional gate — reject signals below screener/strategy threshold |

All rules enforced in `risk.py` **before** `PaperBroker.place_order()`.

---

### Mock order execution

`PaperBroker` supports (v1 in bold, future in italics):

- **Buy orders** (LONG entry)
- **Sell orders** (SHORT entry / exit)
- **Stop-loss execution** — triggered by `PositionManager` on candle/tick
- **Target execution** — limit-style fill at TP price when touched
- **End-of-day auto close** — configurable time (default 15:15 IST)
- *Partial exits* — Phase 2 stub, full support later
- *Manual close* — ChatOps `/close SYMBOL` in Phase 3

**Fill model (realistic but simple):**

- Market entry: LTP + slippage from `CostModel.apply_slippage()`
- SL: adverse slippage on trigger
- TP: fill at target price when high/low crosses (optimistic within bar — same as backtest, tunable)
- Reject order if insufficient virtual cash or risk gate fails

---

### Trade journal

Every **completed** paper trade generates a `trade_journal` document (and linked `paper_trades` record).

#### Trade information

| Field | Description |
|-------|-------------|
| Trade ID | Stable UUID, links recommendation → journal → analytics |
| Date & time | Entry and session (IST) |
| Trading session | Regular / pre-market |
| Stock symbol | NSE ticker |
| Company name | From universe metadata |
| Sector | From sector map |
| Strategy used | e.g. `ORB`, `SCREENER_V3` |
| AI / agent reasoning | Strategy reason string + score breakdown |
| Confidence score | 0–100 |

#### Order details

| Field | Description |
|-------|-------------|
| Buy price | Entry fill (LONG) or cover (SHORT exit) |
| Sell price | Exit fill |
| Quantity | Shares/lots |
| Entry timestamp | ISO 8601 IST |
| Exit timestamp | ISO 8601 IST |
| Holding duration | Minutes |
| Stop loss | Planned SL |
| Target | Planned TP |
| Risk-reward ratio | From plan |

#### Financial details (Indian equity realism)

Use `CostModel` from Phase 0 — itemized, not a single lump fee:

| Charge | Notes |
|--------|-------|
| Gross profit/loss | Before charges |
| Brokerage | Flat + % cap per order |
| Exchange transaction charges | On turnover |
| STT | Sell-side for intraday equity |
| GST | On brokerage + exchange charges |
| SEBI charges | Per crore turnover |
| Stamp duty | Buy-side |
| Total charges | Sum of above |
| Net profit/loss | Gross − total charges |
| Return (%) | On capital deployed |

Paper results should be **comparable to live P&L** after Phase 0 cost calibration.

#### Trade outcome

| Field | Description |
|-------|-------------|
| Win / Loss | Net P&L > 0 |
| Target hit | Boolean |
| Stop-loss hit | Boolean |
| Time exit | Boolean |
| Max unrealized profit | Peak favorable move during hold |
| Max unrealized loss | Peak adverse move (MAE) |
| Best possible exit | Theoretical best price in window |
| Worst possible exit | Theoretical worst price in window |
| Exit reason | `SL Hit`, `TP Hit`, `Time Exit`, `EOD Close`, etc. |

Journal entries are **append-only**; corrections get a new audit record, not silent overwrites.

---

### Portfolio tracking

Virtual portfolio maintained in memory during session; **snapshots** written to MongoDB at EOD and on demand.

| Metric | Description |
|--------|-------------|
| Starting capital | Configurable (e.g. ₹10,00,000) |
| Available cash | After entries and charges |
| Capital deployed | Mark-to-market open positions |
| Realized P&L | Closed trades today / cumulative |
| Unrealized P&L | Open positions MTM |
| Daily / weekly / monthly P&L | From summaries collection |
| Total return | Since inception |
| Win rate | Closed trades |
| Average winner / average loser | Net of charges |

Module: `portfolio.py` — rebuild state from `paper_trades` on restart (MongoDB as recovery source).

---

### Analytics & reporting (trade journal layer)

Generated by `trade_journal_report.py` (Phase 3+) — complements `analytics_report.py`:

- Daily trade journal (every trade narrative + numbers)
- Weekly / monthly performance reports
- Strategy-wise and sector-wise performance
- Best and worst trades
- Common mistakes (from failure tags)
- Missed opportunities (Hold signals vs actual move)
- Risk analysis (exposure, loss streaks)
- Equity curve and drawdown analysis

Deliver via Webex (`/journal`, `/paper`) and optional HTML/JSON export.

---

### MongoDB storage (paper trading)

Persist **everything** — nothing discarded:

| Data | Collection |
|------|------------|
| Trade recommendations | `recommendations` |
| Executed paper trades | `paper_trades` |
| Trade journal entries | `trade_journal` |
| Portfolio snapshots | `portfolio_snapshots` |
| Daily / weekly / monthly summaries | `daily_summaries`, `weekly_summaries`, `monthly_summaries` |
| Market snapshots | `market_snapshots` |
| Performance metrics | `performance_rollups` or embedded in summaries |
| Failure analysis | `failure_analyses` |
| Agent reasoning | Embedded in recommendation + journal |
| Strategy metadata | Embedded in trade docs |

---

### Future roadmap (broker abstraction)

Design so the paper engine extends cleanly to:

| Capability | Interface |
|------------|-----------|
| Real broker execution (Dhan, Zerodha, …) | Same `Broker` protocol |
| Live portfolio management | Same `Portfolio` + broker reconciliation |
| Backtesting engine | Same `PositionManager` + historical price feed |
| Multi-strategy execution | Multiple strategy workers → shared router |
| Reinforcement learning feedback | MongoDB labeled outcomes → training export |
| AI strategy optimization | Analytics + journal as labeled dataset |

**Switching paper → live:** change `Broker` implementation and `--mode`; agent loop, risk engine, position manager, and journal schema stay the same.

---

### Engineering principles

- **Clean, modular, production-ready** — one responsibility per module.
- **SOLID** — depend on `Broker` and `AnalyticsStore` protocols, not concrete drivers.
- **No unnecessary abstractions** — no factory-of-factories; Protocol + two implementations is enough.
- **Paper engine is the foundation** for the autonomous platform; MongoDB holds historical performance for analytics and continuous learning.

---

### Paper trading implementation phases (within roadmap)

| When | What |
|------|------|
| **Phase 0** | `costs.py` with full Indian charge breakdown — required for realistic journal |
| **Phase 2** | `PaperBroker`, `portfolio.py`, daily rules in `risk.py`, journal write on trade close, EOD snapshot |
| **Phase 3** | 4–6 week paper run; `trade_journal_report.py`; ChatOps `/paper`, `/journal`; calibrate costs vs reality |
| **Phase 4** | `DhanBroker` implements same `Broker` protocol — minimal agent loop changes |
| **Phase 5** | Equity curve dashboard, drawdown alerts, automated weekly journal to Webex |

---

## Phased Implementation Plan

### Phase 0 — Answer the edge question

**Goal:** A defensible yes/no on "does ORB have positive net-of-cost expectancy on this universe?" **Gate:** Do not build the paper engine, the analytics layer, or execution until this is answered.

**Effort:** 1.5–2.5 weeks of build, plus a data-dependent waiting period (see Task 1).

#### Why this phase is larger than "add a cost model"

Three constraints make the current backtester unable to answer the question, regardless of cost modeling:

1. **No usable intraday history.** `market_feed.py` builds 1-min candles, fans them to strategy queues, and discards them — nothing is persisted. Every yfinance call in the repo is `interval="1d"`, and Yahoo does not serve months of 1-min data. Dhan's intraday history depth is the only candidate source and has never been measured.
2. **The backtester cannot run a universe.** `ORBBacktester` holds one global `_active_trade`, so a second symbol's signal is silently dropped while the first symbol's trade is open. Multi-symbol runs would produce wrong numbers, not obviously broken ones.
3. **Sample size is the binding constraint.** At 1:1 RR with realistic friction (~0.1–0.3R), breakeven sits near a 55–60% win rate. Distinguishing that from 50% needs several hundred trades. Any conclusion drawn from fewer is noise, so the tooling must report whether the sample can support a conclusion at all.

---

#### Task 1 — Measure data availability, then start recording (do this first, day 1)

**New: `scripts/probe_dhan_history.py`** — request progressively older date windows from `/v2/charts/intraday` for a few liquid security IDs and record the oldest timestamp actually returned, the max span per request, and observed rate limits. Write findings to `docs/DATA_AVAILABILITY.md`.

This single measurement decides the shape of the whole phase:

| Dhan depth | Consequence |
|------------|-------------|
| Months–years of 1-min | Backfill the cache; Phase 0 completes on build time alone |
| Only days | Historical backtest cannot reach significance. The forward recorder becomes the only path, and Phase 0's answer is gated on calendar time |

**New: `candle_recorder.py`** — start this on day 1 regardless of the probe result, because recorded history only accumulates in real time.

`main.py` already fans out to `strategy_queues: list[Queue]`, so the recorder is a second queue plus a second consumer thread — no architectural change. It appends every finalized candle to the cache.

**New: `data_cache.py`** — Parquet-backed 1-min candle store, the single source of candles for every backtest.

```python
class CandleCache:
    """Parquet store at data/candles/security_id=<id>/<YYYY-MM>.parquet."""

    def coverage(self, security_id: str) -> list[tuple[date, date]]: ...
    def read(self, security_id: str, start: date, end: date) -> pd.DataFrame: ...
    def write(self, security_id: str, df: pd.DataFrame) -> None: ...
```

Writes are idempotent and deduplicate on timestamp, so backfill and live recording can target the same store. Add `pyarrow` to `requirements.txt`.

**New: `scripts/backfill_candles.py`** — chunked, throttled, resumable backfill into the cache for the full universe, skipping ranges already covered.

---

#### Task 2 — `costs.py`

```python
@dataclass(frozen=True)
class CostModel:
    brokerage_per_order: float
    brokerage_pct_cap: float
    stt_pct_sell: float
    exchange_txn_pct: float
    gst_pct: float
    sebi_charges_per_crore: float
    stamp_duty_pct_buy: float
    slippage_bps: float

    def charges(self, price: float, qty: int, side: Side) -> ChargeBreakdown: ...
    def round_trip(self, entry: float, exit: float, qty: int) -> ChargeBreakdown: ...
    def apply_slippage(self, price: float, side: Side, is_entry: bool) -> float: ...
```

Returns an **itemized `ChargeBreakdown`**, not a lump sum — the same structure the Phase 2 trade journal needs, so it is built once. Defaults in `config.py`.

---

#### Task 3 — Rebuild the backtest harness

Modify `backtest.py`:

- **Per-symbol trade slots** — `_active_trades: dict[str, dict]` replaces the single `_active_trade`. Concurrency across symbols is capped by the same limit the live risk engine will use, so backtest and live agree on trade selection.
- **Next-bar entry.** Fill at the *next* candle's open, not the signal candle's close. After a breakout candle the next tick is systematically worse, and a flat slippage constant cannot represent a directional bias. Keep the strategy's SL at the structural ORB level, and recompute TP from the actual fill so realized RR matches the configured ratio.
- **Apply `CostModel`** — itemized charges plus slippage per leg; report gross and net side by side.
- **`--intrabar {pessimistic,optimistic}`**, default pessimistic (SL checked first). Report both in the summary; at 1:1 RR the gap between them is material and needs to be visible, not optional.
- **Fix** `if not exit_price` → `if exit_price is None` (latent, since prices are never zero).
- **Metrics:** expectancy in R, net expectancy, profit factor, max drawdown, Sharpe.
- **Sample sufficiency block** — the most important output. Report trade count, net expectancy, a bootstrap 95% confidence interval, and the trade count required to resolve the observed effect size. The report should state plainly whether the data supports a conclusion yet.

**New: `scripts/run_backtest.py`** — universe-wide runner over the cache, replacing the single-symbol `__main__` block.

---

#### Task 4 — Unify scoring

**New: `scoring.py`** — extract from `comprehensive_screener.py`:

```python
def score_stock(inp: ScoreInput) -> ScoreResult  # includes factor_breakdown
```

Both `comprehensive_screener.py` and `screener_backtest.py` import it; delete the duplicated logic. Screener backtest: entry at **next-day open**, MAE from forward **lows**.

---

#### Task 5 — Out-of-sample protocol (write before running anything)

**New: `docs/RESEARCH_PROTOCOL.md`**, committed before the first tuning run:

- **Split by date, fixed in advance.** Oldest ~65% is training, newest ~35% is holdout. Recorded in the document, never adjusted afterward.
- **Declare the parameter grid up front** — ORB window, volume threshold, RR ratio — and record the number of combinations. More combinations means a higher bar on the holdout.
- **The holdout is evaluated once.** Looking at it and re-tuning converts it into training data, and it must then be retired in favor of newly recorded history.
- **`research_log.csv` is append-only** — one row per run: date, parameters, dataset span, metrics. This is the record that makes overfitting visible instead of deniable.

---

#### Task 6 — Compliance spike (parallel, ~1 hour of effort)

Email Dhan now rather than at Phase 4. Two questions determine whether the destination is reachable:

1. Can an unattended, cron-started process place orders under the daily 2FA policy, or is interactive authentication required each session?
2. What is the Algo-ID registration path for a self-developed personal-use strategy, and what is the lead time?

A restrictive answer to either reshapes the roadmap. It is the cheapest information in the project and currently sits behind three months of work.

---

#### New tests

`tests/test_costs.py`, `tests/test_scoring.py`, `tests/test_backtest.py`, `tests/test_data_cache.py` (idempotent writes, coverage gaps, overlapping ranges).

---

#### Exit criteria — decide, then branch

Run the holdout **once** and read the sample sufficiency block:

| Result | Meaning | Action |
|--------|---------|--------|
| **Green** | Net expectancy positive, 95% CI excludes zero | Proceed to Phase 1, then Phase 2 |
| **Amber** | Positive point estimate, CI includes zero | Sample too small to conclude. Keep recording, keep the holdout sealed, revisit at the trade count the report specifies |
| **Red** | Net expectancy negative or CI clearly straddling zero with no trend | **Stop.** Do not build the paper engine. Return to strategy research — most likely the 1:1 RR geometry, since it is the parameter the cost model most directly indicts |

Also required regardless of branch: screener and backtest produce identical scores for identical input.

**Amber is the most likely outcome, and it is not a failure.** It means the answer needs more data, the recorder is already accumulating it, and Phase 1 (cheap, independently valuable) can proceed in the meantime.

---

### Phase 1 — Harden the pipeline (fail loudly)

**Goal:** Broken or stale pipeline cannot produce a tradeable plan. **Gate:** Required before Phase 2.

#### New: `clock.py`

```python
IST = ZoneInfo("Asia/Kolkata")
def now_ist() -> datetime
def trading_date_ist() -> date
```

Replace naive `datetime.now()` in screener, `market_db`, news, global signals.

#### Modify: `intraday_trigger.py`

Write structured plan with provenance:

```json
{
  "trading_date": "2026-08-03",
  "generated_at": "2026-07-31T15:47:12+05:30",
  "symbols": { "RELIANCE": "11536" }
}
```

Raise on missing inputs instead of silent `return`.

#### Modify: `config.py`

- `load_trade_plan(required=True)` with freshness check (`trading_date` must match next session).
- Remove silent fallback to `.env` for live agent (keep `.env` only for manual/backtest).

#### Modify: `comprehensive_screener.py`

- Always write `screener_results.csv` (even if empty).
- Log and count per-stock failures; abort if failure rate exceeds threshold.

#### Modify: `market_feed.py`

- Use exchange LTT for candle bucketing; warn on fallback to local clock.
- Feed-gap detection per symbol.

#### CI / ops

- New `.github/workflows/test.yml` — run pytest on push/PR.
- Add `update_security_ids.py` to evening workflow before `intraday_trigger.py`.
- Fix morning artifact download (cross-run artifact ID).
- Stop committing `market_data.db` to git; use artifacts or external store.

#### Cleanup

- Delete `breakout_screener.py`.
- New `universe.py` — single 152-stock list.
- `requirements-dev.txt` + lockfile or full pins.

**Exit criteria:** Stale plan impossible without explicit override; CI runs tests.

---

### Phase 2 — Agent core + paper trading engine

**Goal:** Full intraday loop on `PaperBroker` with shared exit/risk logic, trade journal, and MongoDB persistence. **No broker APIs.** **Effort:** ~2–3 weeks.

#### New modules

| Module | Responsibility |
|--------|----------------|
| `orders.py` | `Order`, `OrderState`, idempotent `client_order_id` |
| `broker.py` | Protocol: `place_order`, `cancel_order`, `fetch_positions`, `fetch_orders` |
| `paper_broker.py` | **Paper Trading Engine** — simulated fills on live LTP + `CostModel` |
| `dhan_broker.py` | Stub only in Phase 2; implements same protocol in Phase 4 |
| `portfolio.py` | Virtual capital, cash, MTM, realized/unrealized P&L; EOD snapshots |
| `risk.py` | Pre-trade gate: max **4–5 trades/day**, daily loss, sizing, sector exposure, no duplicate symbol |
| `position_manager.py` | SL/TP/time/EOD exit — **shared by live, paper, and backtest** |
| `trade_journal.py` | Build journal doc from closed trade + charges + outcome fields |

#### Paper trading config (add to `config.py`)

```python
PAPER_STARTING_CAPITAL=1000000
MAX_DAILY_TRADES=5
MAX_DAILY_LOSS_RUPEES=10000
RISK_PER_TRADE_PCT=0.01
MAX_SECTOR_EXPOSURE_PCT=0.30
ALLOW_REENTRY=false
EOD_CLOSE_TIME=15:15
TRADING_MODE=paper  # paper | live
```

#### Modify: `main.py`

Agent loop: candle → strategy → risk → size → **PaperBroker** → portfolio → position manager → journal + analytics.

Default `--mode paper`. Kill switch: file sentinel + `/kill` ChatOps → flatten virtual positions + halt.

#### Modify: `costs.py` (from Phase 0)

Itemized charges for journal: brokerage, exchange, STT, GST, SEBI, stamp duty — per leg and round-trip.

#### Modify: `market_db.py`

Operational SQLite for VM cron; **all paper trades and journal → MongoDB**.

#### New: analytics + journal persistence (Phase 2)

| Module | Responsibility |
|--------|----------------|
| `analytics_models.py` | `Recommendation`, `PaperTrade`, `TradeJournalEntry`, `PortfolioSnapshot`, … |
| `analytics_store.py` | Protocol — includes `save_paper_trade`, `save_journal_entry`, `save_portfolio_snapshot` |
| `analytics_mongo.py` | MongoDB impl + indexes (`MONGODB_URI` in config) |

On signal: `save_recommendation`. On fill/close: `save_paper_trade` + `save_journal_entry`. At EOD: `save_portfolio_snapshot` + `daily_summaries`.

#### Tests

- `tests/test_paper_broker.py` — fills, SL/TP, charges, insufficient cash
- `tests/test_risk.py` — daily trade cap, duplicate symbol block, sector limit
- `tests/test_trade_journal.py` — journal field completeness
- `tests/test_agent_loop.py` — synthetic full paper day
- `tests/test_analytics_store.py` — in-memory fake store (no Mongo in CI)

**Exit criteria:** One full paper trading day completes; max 5 trades enforced; every closed trade has a journal entry in MongoDB; net P&L includes itemized Indian charges.

---

### Phase 3 — Execution validation (4–6 weeks)

**Goal:** Prove that **live execution matches the model** — fills, slippage, charges, and feed behaviour — using only the paper trading engine, no broker APIs. **Duration:** 4–6 weeks elapsed.

The edge was established in Phase 0 against cached history. Phase 3 does not re-litigate it: ~150 paper trades cannot resolve the expectancy question, and treating a favourable paper run as confirmation is how an unvalidated strategy reaches production. What a paper run *can* prove is that the assumptions the backtest made about the real world hold.

- Run `main.py --mode paper` daily through full market sessions.
- `daily_report.py` — paper vs backtest comparison on same days.
- Calibrate `CostModel` from paper vs expected charges; feed slippage gap back into config.
- ChatOps **`/paper`** (portfolio summary), **`/journal`** (today's trades).
- **`trade_journal_report.py`** — daily journal, weekly/monthly reports, equity curve, drawdown.
- **`outcome_enricher.py`** — recommendation outcomes + evaluations for signals not traded (missed opportunities).
- **`market_snapshot_job.py`** — daily benchmark document.
- **`failure_analyses`** for losing paper trades.

**Exit criteria — all about fidelity, not profit:**

- **Fill fidelity:** realized paper slippage within tolerance of `CostModel.slippage_bps`; if not, recalibrate and re-run the Phase 0 backtest with the measured value before proceeding.
- **Charge fidelity:** itemized journal charges reconcile against a broker contract note for equivalent trades.
- **Signal fidelity:** signals fired live match those the backtest produces when replayed over the same recorded candles. Any divergence is a feed-gap or clock bug, not strategy behaviour.
- **Risk behaviour:** ≤5 trades/day, no duplicate symbols, no breach of daily loss limit across the run.
- **Data chain complete:** recommendation → paper trade → journal → evaluation, with no orphaned records.

Paper P&L is **recorded and reported but is not a gate** — the sample is too small to carry that weight. A materially negative run is still a signal to stop and investigate whether Phase 0's assumptions were wrong.

---

### Phase 4 — Live execution (compliance gate)

**Prerequisites:** Phase 3 pass + Dhan confirmation on 2FA and Algo-ID.

#### New: `compliance.py`

- Rate limiter (<10 orders/sec).
- Daily 2FA session gate.
- Static IP assertion at startup.
- Algo-ID on every order.

#### Implement: `dhan_broker.py`

Wire to Dhan Order API behind same `broker.py` interface as paper.

**Rollout:** Minimal position sizes; kill switch always available.

---

### Phase 5 — Observability and self-healing

- FastAPI `health.py` — feed lag, queue depth, positions, P&L, risk headroom.
- Alerts on disconnect, backlog, crash, risk breach.
- Flatten-on-disconnect if feed dies with open positions.
- **`analytics_report.py`** — weekly/monthly reports (strategy, sector, regime, failure patterns).
- ChatOps **`/stats`** — summary win rate, recent evaluations, top failure tags.
- Optional read-only analytics API for a future dashboard.

---

## Sequencing and Effort

| Phase | Focus | Effort | Gate to proceed |
|-------|--------|--------|-----------------|
| **0** | Data cache, cost model, backtest harness, OOS protocol | 1.5–2.5 weeks + data wait | **Edge question answered green** |
| **1** | Fail-loud pipeline, CI, timezones | 3–4 days | No silent stale plans |
| **2** | **Paper trading engine** + trade journal | 5–8 weeks | Full paper day; journal complete |
| **3** | **Execution validation** (4–6 weeks) + journal reports | 4–6 weeks | Live fills match modeled fills |
| **4** | Live execution | 1–2 weeks + broker lead time | Compliance confirmed |
| **5** | Observability + **periodic analytics reports** | ~1–2 weeks | — |

**Hard gates:**

1. **Phase 0 green before Phase 2** — never build execution for an unvalidated edge. Amber means wait for data, not proceed.
2. **Phase 3 before Phase 4** — never send real orders through unvalidated execution.

Phases 0 and 1 are independent and can start in parallel. The Task 6 compliance spike should start on day 1 of Phase 0.

**Division of labour between Phase 0 and Phase 3.** These answer different questions and must not be conflated:

| Question | Answered by | Why |
|----------|-------------|-----|
| Does the strategy have an edge? | **Phase 0 backtest** | Cached history yields years of data in seconds |
| Do live fills match the model? | **Phase 3 paper run** | Only live execution reveals real slippage, feed gaps, and cost drift |

Paper trading is the slowest possible instrument for edge discovery — one calendar day buys one day of data. Its job is calibration, not expectancy. Phase 3's exit criterion is therefore **fill fidelity** (paper slippage and charges within tolerance of `CostModel`), not P&L.

---

## Recommended Starting Point

| If you want… | Start with |
|--------------|------------|
| Know whether the strategy works at all | **Phase 0 Task 1** — probe Dhan history depth, start `candle_recorder.py` today |
| Trust backtest numbers | **Phase 0** — `costs.py` + rebuilt harness + sample sufficiency reporting |
| Avoid a dead end three months in | **Phase 0 Task 6** — email Dhan about 2FA and Algo-ID this week |
| Stop silent production bugs | **Phase 1** — trade plan freshness + CI tests |
| See full agent shape | **Phase 2** design review only (after 0 or 1) |
| Measure every recommendation | **Phase 2** — `AnalyticsStore` + MongoDB on first signal |
| Learn from failures systematically | **Phase 3** — outcome enricher + failure tags |
| Validate without real money | **Phase 2** — Paper Trading Engine + trade journal |
| Realistic Indian P&L in paper mode | **Phase 0** first — itemized `costs.py`, then Phase 2 journal |

---

## Related Documents

- [`agent.md`](../agent.md) — Original design doc (ORB, backtest assumptions, SEBI, phased build v1)
- [`README.md`](../README.md) — Setup and usage (partially outdated re: Telegram vs Webex)
- [`.env.example`](../.env.example) — Environment variables including ChatOps

---

## Changelog

| Date | Change |
|------|--------|
| 2026-07-31 | Initial roadmap from repo audit |
| 2026-07-31 | Added Trading Analytics & Continuous Learning Framework (MongoDB, outcomes, evaluations, failure analysis) |
| 2026-07-31 | Added Paper Trading & Trade Journal Framework (mock engine, daily rules, Indian charges, portfolio tracking) |
| 2026-07-31 | Rewrote Phase 0 around the edge question: candle cache + forward recorder, universe backtest harness, next-bar entry, sample sufficiency reporting, pre-registered out-of-sample protocol, compliance spike. Moved expectancy validation from Phase 3 to Phase 0; Phase 3 now validates execution fidelity |
