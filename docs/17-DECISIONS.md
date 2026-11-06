# Architecture Decision Records

Record important decisions here.

For each decision include:
- Date.
- Status.
- Context.
- Options considered.
- Decision.
- Consequences.
- Revisit conditions.

## Initial Decisions

### D001: Paper trading first
Status: Accepted.
No live execution in the initial release.

### D002: Authorized market data
Status: Accepted.
Use provider APIs with suitable licensing.
No unauthorized TradingView scraping.

### D003: Deterministic risk engine
Status: Accepted.
AI recommendations must pass independent numerical validation.

### D004: Claude as reasoning layer
Status: Accepted.
Claude interprets validated features; Python performs calculations.

### D005: Event-driven AI analysis
Status: Accepted.
Do not call Claude on every market tick.

### D006: Personal use only
Date: 2026-11-02.
Status: Accepted by the owner.
Context: Every major exchange limits free market data to personal or internal use, or requires permission for anything more. Providing recommendations to others may also be regulated.
Options considered: personal use; third-party product, free or paid.
Decision: The platform is for the owner's personal use only.
Consequences:
- Binance's "non-commercial personal or internal business use" wording fits this use.
- No paid data licence is needed.
- One owner account is enough (D019). Multi-user features are out of scope.
- Personal-use terms such as Finnhub's free tier become usable.
- The repository stays private, because data and derived results must not be redistributed.
- Risks R1 and R15 fall to low while this holds.
Revisit conditions: anyone else gets access, in any form, free or paid. That needs a licensing, security and legal review first.

### D007: Run on the owner's computer first
Date: 2026-11-02.
Status: Accepted by the owner.
Context: The review recommended an always-on server, because sleep stops data collection. The owner chose to start locally on a MacBook Air (M1, 8 GB memory, 4.6 GB free disk at review time).
Options considered: owner's computer; always-on server in an eligible region.
Decision: Run everything on the owner's computer first.
Consequences:
- No hosting cost.
- At least 20 GB of free disk is required before the full history download. D027 lets testing start with less.
- A local storage profile keeps the database at about half the full size (D024).
- Candles and funding repair automatically after sleep. Open interest repairs within one month. Spread and liquidation data for those periods is lost.
- Paper fills during sleep are reconstructed from 1M candles and labelled as such.
- The 72-hour soak needs the computer plugged in, lid open and kept awake.
- Forward results will contain gaps, which reports must show.
Eligibility: on 2026-11-02 the owner confirmed Binance is allowed where they live. Only public data is read, and no Binance account is used.
Revisit conditions: forward paper trading starts, and gaps become a problem; the disk or memory cannot keep up. D026 records the intended next host.

### D008: SELL means a simulated short on perpetuals
Date: 2026-11-02.
Status: Accepted by the owner.
Context: Spot cannot be shorted without margin, yet the brief requires BUY and SELL, leverage and funding.
Options considered: long-only spot; simulated short on USDT-margined perpetuals; simulated spot shorts with no real venue.
Decision: SELL opens a simulated short on USDT-margined perpetuals. BUY uses the same instruments, so both directions share one cost model and one backtest. Spot stays as long-history market context.
Consequences:
- Phase 1B is firm, and the perpetual feed becomes the primary dataset.
- Funding, mark price and margin are modelled.
- Two WebSocket connections are needed for futures.
- Paper trading only. No exchange account or order path exists.
Revisit conditions: the owner wants spot-only strategies.

### D009: Python owns numbers, Claude owns judgment
Date: 2026-11-02.
Status: Accepted by the owner.
Context: The brief makes Claude the main reasoning engine, and also forbids invented numbers. Backtests need a deterministic strategy.
Options considered: Claude proposes prices; Claude only reviews a deterministic setup; Python catalogues levels and Claude selects them.
Decision: Python builds a catalogue of candidate levels. Claude decides BUY, SELL, WAIT or NO_TRADE and selects levels by ID. Python resolves prices and sizes the trade. The risk engine validates. A rule baseline uses the same catalogue.
Consequences:
- Claude cannot produce an unverified number.
- The baseline can be backtested. Claude is evaluated forward only.
- Claude's value is measured as uplift over the baseline.
Revisit conditions: the catalogue repeatedly lacks levels that Claude's reasoning needs.

### D010: Evidence before AI
Date: 2026-11-02.
Status: Accepted by the owner.
Context: The original roadmap built Claude before backtesting, so money would be spent before knowing whether any setup has an edge.
Options considered: original order; risk and backtesting first.
Decision: Foundation, Market data, Quant, Setups and Risk, Backtesting, Paper trading, News, Claude, Hardening.
Consequences:
- Evidence arrives before AI cost.
- AI spend is zero until the news phase.
- The AI analyst arrives later. Shadow mode after Phase 3 remains available.
- Official news collection starts early, because an archive cannot be created afterwards.
Revisit conditions: the owner wants Claude output earlier.

## Engineering Defaults

Adopted 2026-11-02 when Phase 0 started. These were proposed in [18-ARCHITECTURE-REVIEW.md](18-ARCHITECTURE-REVIEW.md), section 8, and the owner raised no objection. Each is a default, so each states what would reopen it.

### D011: Modular monolith with plain worker processes
Date: 2026-11-02. Status: Adopted.
Context: One owner, one computer, and seven kinds of work that fail independently.
Options considered: microservices; a single process; one codebase with several processes.
Decision: One Python package, started as separate processes such as `api`, `ingestor` and `quant-worker`.
Consequences: One deploy unit and shared types. Process boundaries are kept by import rules, not network calls.
Revisit conditions: one workload needs to scale or fail separately on a different host.

### D012: PostgreSQL 18, with TimescaleDB only if measured
Date: 2026-11-02. Status: Adopted.
Context: Candle reads must stay fast, and the disk is small.
Options considered: PostgreSQL; TimescaleDB from the start; a dedicated time-series store.
Decision: Plain PostgreSQL 18. T1.17 benchmarks TimescaleDB on the real dataset.
Consequences: One less extension to manage. Native `uuidv7()` replaces a substitute function.
Revisit conditions: T1.12 latency target is missed, or the benchmark shows a large measured benefit.

### D013: Native ingestion of all seven timeframes, closed candles only
Date: 2026-11-02. Status: Adopted.
Context: Aggregating from 1M hides provider differences, and a forming candle in storage risks future leakage.
Options considered: store 1M and aggregate; store native candles for each timeframe.
Decision: Store each provider's native candles for 1M, 5M, 15M, 30M, 1H, 4H and 1D. `market_candles` holds closed candles only.
Consequences: Cross-timeframe checks become a data-quality test. Forming candles exist only in memory and on live streams.
Revisit conditions: storage cost outweighs the checking benefit.

### D014: Redis Streams and Pub/Sub, no job-queue library
Date: 2026-11-02. Status: Adopted.
Context: Closed candles must not be lost, and latest-price updates may be.
Options considered: Celery or a similar queue; Kafka; Redis Streams and Pub/Sub.
Decision: Redis Streams with consumer groups for closed candles. Pub/Sub for latest-value data. PostgreSQL commits before any publish.
Consequences: Consumers must be idempotent. Missed events replay from the database.
Revisit conditions: a workload needs scheduling or retries that Streams handle poorly.

### D015: Decimal and float boundary
Date: 2026-11-02. Status: Adopted.
Context: Money must be exact, and indicators need fast array maths.
Options considered: float everywhere; Decimal everywhere; a defined boundary.
Decision: `Decimal` in storage, domain models, risk and the wire format, where it is a string. Floats only inside the indicator engine.
Consequences: Indicator outputs are converted deliberately at the boundary and never feed money calculations unconverted.
Revisit conditions: none expected.

### D016: Hard-coded paper mode and no exchange keys
Date: 2026-11-02. Status: Adopted.
Context: A setting that can say "live" can be changed by mistake or by an attacker.
Options considered: a `TRADING_MODE` setting; a mode with only one possible value.
Decision: `TradingMode` has one member, `PAPER`. No exchange credentials exist anywhere, and no order path is written.
Consequences: Live trading would need a new isolated module and explicit human authorisation.
Revisit conditions: the owner explicitly requests live execution after the initial release.

### D017: Binance endpoints, no Vision archive, top of book first
Date: 2026-11-02. Status: Adopted.
Context: Binance's data archive has a stricter licence, and a full order book is costly.
Options considered: REST and WebSocket only; adding the archive; a full local book.
Decision: Public REST and WebSocket endpoints. No `data.binance.vision` files. Top of book first, with depth summaries only if a strategy needs them.
Consequences: Backfill is limited by request weight rather than file downloads.
Revisit conditions: the owner accepts the archive terms, or a strategy proves it needs depth.

### D018: Python 3.14, uv, pnpm, Docker Compose, Makefile
Date: 2026-11-02. Status: Adopted.
Context: This computer's default Python is 3.10, which is too old.
Options considered: pyenv and pip; uv.
Decision: Versions from [03-TECHNOLOGY-STACK.md](03-TECHNOLOGY-STACK.md). uv for Python, pnpm for Node, Compose for local services, and a Makefile as the single entry point.
Consequences: `make bootstrap` and `make check` are the only commands a contributor needs.
Revisit conditions: a required library does not support Python 3.14.

### D019: Single owner authentication
Date: 2026-11-02. Status: Adopted.
Context: D006 limits use to the owner, but the dashboard still shows private data.
Options considered: no login; one account; full multi-user.
Decision: One owner account with a hashed password and a session cookie, behind one replaceable dependency.
Consequences: Moving to a host needs no redesign, only stronger exposure checks.
Revisit conditions: D006 changes.

### D020: Structured logs and health status from Phase 1
Date: 2026-11-02. Status: Adopted.
Context: Reliability work depends on seeing what the system did.
Options considered: plain logs; a metrics stack; structured logs and a health API.
Decision: JSON logs through `structlog` with secret filtering, and a health model in the API.
Consequences: No separate metrics service on an 8 GB computer.
Revisit conditions: moving to a host where external monitoring is worthwhile.

### D021: Model selection
Date: 2026-11-02. Status: Adopted.
Context: Reasoning and classification have different needs.
Options considered: one model; a stronger and a cheaper model.
Decision: `claude-opus-5-5` for reasoning and `claude-haiku-5-5` for classification.
Consequences: Model IDs are configuration and are stored with every analysis.
Revisit conditions: measured uplift shows a cheaper model is as good.

### D022: Claude has no tools and no web access
Date: 2026-11-02. Status: Adopted.
Context: Tools widen the prompt-injection risk from untrusted news.
Options considered: web search; supplied context only.
Decision: Claude reads supplied, classified context and has no tools.
Consequences: Every fact can be traced to stored evidence.
Revisit conditions: the supplied context repeatedly lacks what the analysis needs.

### D023: Module names follow the brief
Date: 2026-11-02. Status: Adopted.
Context: The brief names its modules.
Options considered: earlier names; the brief's names.
Decision: Use the names in [23-PROJECT-STRUCTURE.md](23-PROJECT-STRUCTURE.md).
Consequences: Documents and code use one vocabulary.
Revisit conditions: none expected.

### D024: Storage profile
Date: 2026-11-02. Status: Adopted, extended by D027.
Context: Full history is about 5.5 GB and this computer has little free disk.
Options considered: everything; a reduced profile.
Decision: Full history for perpetuals. For spot history, 15M and above only.
Consequences: Saves 2.85 GB. Spot 1M and 5M history can be downloaded later.
Revisit conditions: a strategy needs spot 1M or 5M history.

### D025: AI cost strategy
Date: 2026-11-02. Status: Adopted.
Context: A naive design would cost about $700 a month.
Options considered: see [24-AI-COST-STRATEGY.md](24-AI-COST-STRATEGY.md).
Decision: Deterministic gates, including a viability pre-check, `medium` effort for decisions, and limits of $3 a day and $40 a month.
Consequences: Most candles cost nothing. Figures remain estimates until measured.
Revisit conditions: real usage differs materially from the planning numbers.

## Owner Decisions, 2026-11-02 Build Start

### D026: Railway is the intended next host, subject to a connection test
Date: 2026-11-02.
Status: Accepted by the owner as the intent. The move is conditional.
Context: The owner wants to test on their Mac and then move to Railway. Railway's documented regions are California, Virginia, Amsterdam and Singapore. Railway staff stated on 2026-04-01 that all four use IP ranges Binance may block, and a user reported the restriction after moving to Singapore and then the Netherlands.
Options considered: Railway; keeping the Mac; another host.
Decision: Finish testing on the Mac. Before any migration, run a single public `GET` to Binance's spot and futures endpoints from a Railway service in the chosen region. Treat HTTP 451 or 403 as the end of that route.
Consequences:
- A geographic block is never bypassed. No proxy, VPN or alternate host is used to get around one.
- If Binance refuses Railway, the choices are another host in a region Binance serves, keeping ingestion on the Mac, or another licensed provider through the adapter layer.
- Listed Railway prices on 2026-11-02 are about $10 per GB of memory, $20 per vCPU and $0.15 per GB of volume per month, plus a plan fee.
- Hosting needs stronger exposure checks: TLS, Secure cookies and a security audit.
Revisit conditions: the connection test result is known.

### D027: Test profile for the Mac
Date: 2026-11-02.
Status: Adopted.
Context: The owner chose to test on this Mac and did not approve deleting caches. It has about 5 GB free, against the 20 GB needed for full history. A move to Railway would take full history off this computer.
Options considered: wait for 20 GB; test with a recent window.
Decision: The 20 GB rule now blocks only the full history download. Local testing uses a recent window of 90 days on all seven timeframes for BTCUSDT and ETHUSDT, spot and perpetual: about 685,000 rows, or 170 MB at the measured 245.5 bytes per row. Backfill still refuses to run below a free-disk floor, which is a setting: 2 GB for this profile, 10 GB for full history.
Consequences:
- Reports from the test window say so. It is too short for walk-forward evidence, so backtest evidence waits for full history.
- Integration tests use the Compose PostgreSQL rather than testcontainers, to avoid another image.
Revisit conditions: 20 GB becomes available, or the platform moves to a host.

### D028: Keep building through phases
Date: 2026-11-02.
Status: Accepted by the owner.
Context: The release gate stopped each phase until the last had a report, and Phase 1's report needs a 72-hour live test.
Options considered: keep building; stop after every phase; stop after Phase 1.
Decision: Each phase is built in order, with its code, tests and report. The next phase starts without waiting for owner review. Long tests run alongside later work. Stop at Phase 7, which needs the owner's Claude API key.
Consequences:
- A phase can be code-complete before its long test passes. Reports must say which gates are still open, and nothing counts as proven until it passes.
- Work is committed locally, one commit per task, on the `develop` branch, after a secret scan. Nothing leaves this computer.
Revisit conditions: a long test fails in a way that changes earlier work.

### D029: Holdout frozen from 2025-11-01
Date: 2026-11-02.
Status: Adopted.
Context: The methodology keeps the most recent 12 months untouched, and requires the date to be frozen before any strategy research. The 90-day test window sits entirely inside that period, so running the strategy on it and reading the results would spend the only clean test.
Options considered: freeze now; choose a date later; test on the recent window.
Decision: The final holdout starts at 2025-11-01 00:00 UTC. The backtest code refuses any window touching it unless the run is explicitly a holdout run, which the database allows once per strategy version. Real-data checks of the engine use candles from before that date.
Consequences:
- The 90-day window remains valid for the dashboard, indicators and live monitoring. Only pattern counts have been read from it, never strategy results.
- A small research window from before the holdout is needed to exercise the engine on real data.
- Results from that window prove the engine runs. They are far too short to be evidence.
Revisit conditions: none. A changed strategy needs fresh out-of-sample time, normally from forward paper trading.

## Owner Decisions, 2026-11-03 Pattern Signals

The owner asked for pattern and candle research, a Python detector that feeds Claude, news-aware signals with stops and targets, and a historical profitability test.

### D030: Claude trades its own paper account
Date: 2026-11-03.
Status: Accepted by the owner.
Context: The evidence gate in D025 blocks live Claude calls until the rule baseline passes its promotion gate. That needs history this Mac cannot hold, so Claude would never run.
Options considered: Claude trades a separate paper account; Claude's signals are shown but never traded; build patterns first and keep Claude off.
Decision: Claude's recommendations that pass validation and the risk engine open simulated trades in their own paper account, next to the rule strategy's account. The evidence gate is relaxed for paper trading only. Every other gate in [24-AI-COST-STRATEGY.md](24-AI-COST-STRATEGY.md) stays, including the $3 daily and $40 monthly limits.
Consequences:
- Uplift over the rule strategy is measured forward, on the same period, net of API cost.
- Spending starts once the owner adds an API key. No key exists yet.
- Claude still selects levels by ID and never produces a price (D009). Paper mode stays hard-coded (D016).
Revisit conditions: 300 resolved Claude trades, spending above budget, or the owner asks for opinions only.

### D031: 1H setups
Date: 2026-11-03.
Status: Accepted by the owner.
Context: Chart patterns need room to form, and costs took about a third of gross profit on the 15M baseline's BTC test.
Options considered: 15M, 1H or 4H setups.
Decision: Pattern strategies use 1D for direction, 4H for structure, 1H for setups and 15M for entry timing. The 15M rule baseline stays as a separate strategy.
Consequences: Fewer signals and Claude calls than 15M. History for 15M and above fits this computer (D034).
Revisit conditions: forward results show 1H setups are too rare to evaluate.

### D032: News sources
Date: 2026-11-03.
Status: Accepted by the owner in intent. Each source is conditional on its terms.
Context: News today comes only from the Federal Reserve archive.
Decision: Add crypto news RSS feeds such as CoinDesk and Cointelegraph, official sources such as SEC releases, US Treasury releases and the BLS release calendar, and one news API such as CryptoPanic or Finnhub using a key from the owner.
Consequences:
- Each source's terms are read in full and recorded in `providers` before collection starts. Findings so far are in [26-PATTERN-RESEARCH.md](26-PATTERN-RESEARCH.md), section 8.
- Headlines and short summaries are stored locally for the owner only (D006). Article pages are never fetched.
- Claude reads stored, classified items and has no web access (D022).
Revisit conditions: a source's terms forbid this use, or the owner's key is not provided.

### D033: Coin universe with news-driven candidates
Date: 2026-11-03.
Status: Accepted by the owner on 2026-11-04. **SOLUSDT, XRPUSDT, BNBUSDT and DOGEUSDT were added on 2026-11-06** at the owner's request (migration 0008), each checked that day as a trading perpetual listed in 2020 and outside Binance Alpha. The candidate screen is not built yet.
Context: The owner asked which coins people trade now, and for a way to add coins when news makes them relevant. Research is in [26-PATTERN-RESEARCH.md](26-PATTERN-RESEARCH.md), section 7.
Options considered: a fixed list; automatic adds; screened suggestions that the owner approves.
Proposal:
- Core list: BTCUSDT and ETHUSDT now. Add SOLUSDT, XRPUSDT, BNBUSDT and DOGEUSDT after approval. All six were listed at least five years ago and rank in the top 10 by 30-day median volume.
- A candidate is raised when classified news links a contract with relevance of at least 0.7 and medium or high impact, or when its daily volume reaches three times its 30-day median.
- A candidate must pass a screen: a trading USD-M perpetual, listed at least 180 days, not in Binance's Alpha category, a 30-day median volume of at least 50 million USDT, and spread within risk limits.
- Passing candidates appear as suggestions. The owner approves each one, which starts a 90-day backfill and adds it to analysis. At most eight coins are active, under the same Claude budget.
- A coin below the volume floor for 30 days is suggested for removal.
Consequences: New coins can enter without costs growing silently. Short histories mean pattern statistics come mainly from the core coins.
Revisit conditions: the owner prefers automatic adds, or a fixed list.

### D034: History for 1H pattern research
Date: 2026-11-03.
Status: Adopted.
Context: Testing 1H setups needs years of history. Full history is mostly 1M and 5M candles, which do not fit this computer, but 15M and above do.
Decision: The `history` backfill profile loads perpetual 15M, 1H, 4H and 1D candles and funding from listing to the frozen holdout start, 2025-11-01. Pattern research runs simulate fills on 15M candles instead of 1M.
Consequences:
- 527,685 rows, about 125 MB, were loaded on 2026-11-03. The only gaps are the first hours of each listing day.
- When a stop and a target fall in the same 15M candle, the stop is taken first. Coarser candles therefore make results worse, never better. Reports say so.
- The holdout is never loaded by this profile.
Revisit conditions: 1M history becomes affordable, on a host or with more disk.

### D035: Claude reads numbers, not chart images
Date: 2026-11-04.
Status: Accepted by the owner.
Context: Claude can read images, and a chart picture would let it judge a pattern the way a person does. The owner chose numbers only.
Options considered: numbers only; numbers plus a chart image as an opinion; numbers plus an image that can veto.
Decision: Claude receives no chart images. Each pattern's shape is described in numbers by `pattern_detection/describe.py`: size, symmetry, slopes, breakout strength, volume and room to the invalidation level and targets, in ATR at the breakout candle.
Consequences:
- Every value Claude reads is exact, traceable and stored with the analysis snapshot.
- No image tokens are spent.
- Claude judges only what the measurements capture. A cue a person would see but no measure covers needs a new measure, which Python computes.
Revisit conditions: forward results show that pattern quality judged from numbers fails where a picture would have helped.

### D036: History tunes the system, and Claude reads the present
Date: 2026-11-04.
Status: Accepted by the owner.
Context: The owner judged that raw history is of little use to a single decision, and asked that past data tune the system and shape strategies for changing markets instead.
Decision: Claude never reads raw history at decision time. History is used offline to tune and test the Python rules, and to measure how each strategy performed in each market regime. Claude receives the current regime and those base rates, with sample sizes.
Consequences:
- `market_structure/regime.py` labels each day by daily ADX and by daily ATR ranked against its trailing year.
- Base rates shown to Claude come only from data before the decision.
- Smaller context, and no outcomes for Claude to remember.
Revisit conditions: forward results show Claude needs more history than the summaries give.

### D037: Test regime rules on data they were not built from
Date: 2026-11-04.
Status: Accepted by the owner on 2026-11-04. Run once on 2026-11-04, together with version 1 so the rule's effect can be measured on the same year: [pattern-holdout.md](reports/pattern-holdout.md).
Context: Trial 1 lost on both coins when daily volatility was in the highest quarter of its year. The finding came from slicing the same data, so it cannot be validated on that data.
Proposal: Register `pattern_breakout` version 2, which is version 1 plus "no new trade when daily volatility is in the highest quarter". Test it once on the frozen holdout, 2025-11-01 to 2026-11-01, and keep running both versions forward in paper trading.
Consequences: The holdout is spent for version 2, as D029 allows once per version. If version 2 fails there, the rule is dropped rather than adjusted.
Result, 2026-11-04: version 2 did not beat version 1. BTC made +0.17R a trade against +0.30R, and ETH lost 0.33R a trade in both. **The volatility rule is dropped.** Both versions have now used their holdout run.
Revisit conditions: the owner prefers forward paper trading only, keeping the holdout for later.

### D038: Risk by setup grade
Date: 2026-11-04.
Status: Accepted by the owner on 2026-11-04. Built with the Claude analyst in Phase 7, since grades come from Claude.
Context: Professional traders risk less on weaker setups. Claude grades each setup A, B or C, and C never trades.
Proposal: An A setup risks the profile's full 1%, and a B setup half of it. Claude never sets size: the grade maps to a fraction the risk engine applies, which can only lower risk below the profile's limit.
Consequences: Claude influences position size, though only downwards. Results must be reported by grade.
Revisit conditions: grades show no relation to outcomes after 100 forward trades.


### D039: Daily trend following and trailing stops
Date: 2026-11-04.
Status: Accepted by the owner, who asked for the daily trend strategy next.
Context: The pattern strategy showed no proven edge. Trend following is the best-documented effect across markets, and it needs exits that follow price.
Decision: Add `daily_trend`, the Turtle System 1 rules, as a second strategy, pre-registered in [29-TREND-STRATEGY.md](29-TREND-STRATEGY.md). The shared simulator gains tighten-only stops: a strategy may move its stop at a candle close, effective from the next candle, and never against the trade.
Consequences:
- Backtests and paper trading share the capability, so paper results keep validating backtests.
- The risk engine still requires a target, so trend trades carry a far profit cap at 10R and exit on the trailing stop.
- The holdout is not used for this strategy, because its direction is already known.
Revisit conditions: the risk engine gains a native rule for trades without fixed targets.

### D041: Trend pullback strategy, tested and rejected
Date: 2026-11-06.
Status: Added at the owner's request for more strategies, and rejected by its own pre-registered test.
Context: Both earlier strategies enter on strength. The owner asked for more strategies, and a market pulling back inside its trend had no rule.
Decision: Add `trend_pullback`, pre-registered in [31-PULLBACK-STRATEGY.md](31-PULLBACK-STRATEGY.md): a with-trend 1H reversal candle at a Python support or resistance level, with 4H and 1D agreeing, a stop beyond the level, and catalogue targets at least 2R away. It ran once on 2020 to 2025 and lost money on BTC and ETH with 95% confidence, worse than random entries with the same trend filter and exits. It is kept out of the live view, the paper loop and Claude's evidence.
Consequences:
- The code, tests and reports stay, so the result can be reproduced.
- In this history, a reversal candle at a level inside a trend more often came before the level broke than before it held. Claude's reviews should not treat one as a reason to enter.
Revisit conditions: none for this version. A changed version is a new trial with its own pre-registration.

### D042: Automatic paper trading with the two tested strategies
Date: 2026-11-06.
Status: Accepted by the owner, who asked to start it with the Mac kept awake.
Context: The two older strategies made small backtest profits that could be luck (docs/27, docs/29), and the holdout cannot settle that. Forward paper results are the evidence hindsight cannot reach.
Decision:
- The quant worker runs the 1H pattern breakout at every 1H close and the daily trend at every daily close, for every core perpetual, through the risk engine into the owner's single paper account. The 15M rule baseline no longer runs live.
- Each strategy holds at most one position per coin, as in its backtest. The account's limits apply across both: at most 3 open positions and a 3% daily loss limit.
- The daily trend's 10-day trailing exit tightens the stop at each daily close. Moves are stored once in `paper_stop_moves` and take effect from the next candle, so a replay after sleep gives the same fills.
- The ingestor runs under `caffeinate` through `scripts/soak.sh`, so the Mac stays awake while it runs.
Consequences:
- Forward results per strategy come from the stored recommendations, which name their strategy.
- Live trades can differ from backtests where the account limits refuse a signal, and the refusal is stored with its reason.
Revisit conditions: a strategy's forward results fall outside its backtest's range, or Railway replaces this computer.

## Owner Decisions, 2026-11-05 Model Forecasts

### D040: Kronos forecasts are labelled evidence, never prices
Date: 2026-11-05.
Status: Accepted by the owner, who chose option A. **Retired by the owner on 2026-11-06** after the study and the audit: the setting `kronos_enabled` is off, so Kronos is not on the dashboard, not run by re-analysis or at setups, and not in Claude's evidence. Its code, stored runs and research commands stay, so it can be studied again under a new pre-registered configuration.
Context: The owner asked to install Kronos, a pretrained candle forecasting model, and day-trader-skill, so the system could give exact entries and targets. No model gives exact prices. Kronos samples possible futures, and whether it beats ordinary movement is unknown.
Options considered: A, forecasts as evidence for Claude only; B, forecast levels that Claude can also select as entries or targets.
Decision:
- Kronos runs in its own environment, from a pinned checkout and pinned weights, offline and without secrets. It samples 30 paths of 24 1H candles, beside a time machine baseline of 10,000 resampled paths. Design: [30-MODEL-FORECASTS.md](30-MODEL-FORECASTS.md).
- Claude reads both as an unvalidated forecast. Neither sets a price, a size or a decision, and trade signals, paper trading, the risk engine and backtests cannot import them.
- Every forecast and outcome is stored once and cannot be changed. The track record compares Kronos with the baseline.
- Kronos runs at setups, by hand, or in studies of stored days after its weights last changed on 2025-09-09 whose outcomes end before the holdout.
- day-trader-skill is not installed. It targets US stocks, reads Yahoo Finance data, and its broker module places real orders (D016). Only its Time Machine idea is reused.
Consequences:
- About 90 seconds of processor time per forecast, and about 860 MB of disk for the environment, weights and code.
- Claude's context grows by an estimated 300 tokens when a forecast is present.
- Option B, or any effect on size, needs a new decision after live forecasts show "better than baseline".
Revisit conditions: 100 resolved live forecasts, or a study showing Kronos worse than the baseline.
Result, 2026-11-05: the study of 104 forecasts from 2025-09-10 to 2025-10-31 found Kronos **worse than the baseline** with 95% confidence: Brier 0.393 against 0.252, and its 80% close band held the real close 24% of the time. The revisit condition is met, and the owner's decision is pending. Until then Claude's context labels the track record as "worse than baseline". Details: [30-MODEL-FORECASTS.md](30-MODEL-FORECASTS.md).
Audit, 2026-11-06: the call matches Kronos's own batch prediction, so the errors come from the model in this configuration, not the wiring. Its 24-hour middle moves 45% of the way back to the mean of its 400 input hours (correlation 0.86), where prices moved 12% (correlation 0.19).
