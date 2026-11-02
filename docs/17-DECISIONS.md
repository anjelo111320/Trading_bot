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
