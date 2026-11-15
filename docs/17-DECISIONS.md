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
Date: 2026-11-02. Status: Adopted. Amended on 2026-11-10 by D048: Binance demo trading keys and orders exist, with test funds only. Real money is still unrepresentable. Amended on 2026-11-11 by D052: one read-only key from the owner's main Binance account, used only for Binance's announcement stream, and refused if it can trade, withdraw or transfer. **Replaced for the owner's futures wallet on 2026-11-13 by D060**: one real key, for USDⓈ-M futures only, refused if it can withdraw or transfer, and trading only once the owner arms it. `TradingMode` still has one member: it describes the paper accounts.
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
Status: Accepted by the owner in intent. Each source is conditional on its terms. **On 2026-11-11 (D052)** the publisher RSS feeds were refused by their terms, and Finnhub and Binance's announcement stream were built, each off until its key is set.
Context: News today comes only from the Federal Reserve archive.
Decision: Add crypto news RSS feeds such as CoinDesk and Cointelegraph, official sources such as SEC releases, US Treasury releases and the BLS release calendar, and one news API such as CryptoPanic or Finnhub using a key from the owner.
Consequences:
- Each source's terms are read in full and recorded in `providers` before collection starts. Findings so far are in [26-PATTERN-RESEARCH.md](26-PATTERN-RESEARCH.md), section 8.
- Headlines and short summaries are stored locally for the owner only (D006). Article pages are never fetched.
- Claude reads stored, classified items and has no web access (D022).
Revisit conditions: a source's terms forbid this use, or the owner's key is not provided.

### D033: Coin universe with news-driven candidates
Date: 2026-11-03.
Status: Accepted by the owner on 2026-11-04. **SOLUSDT, XRPUSDT, BNBUSDT and DOGEUSDT were added on 2026-11-06** at the owner's request (migration 0008), each checked that day as a trading perpetual listed in 2020 and outside Binance Alpha. **ZECUSDT and 1000PEPEUSDT were added on 2026-11-11** (D052, migration 0014) after passing the screen by hand on Binance's public data, which makes eight. The automatic candidate screen is not built yet.
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

### D043: Crash warning filter, tested and not adopted
Date: 2026-11-06.
Status: Studied at the owner's request after the fall of 2026-11-05, and not adopted by its own pre-registered rule.
Context: The owner asked whether the system can detect a fall like the one on 2026-11-05 before it happens.
Decision: The study in [32-SHOCK-STUDY.md](32-SHOCK-STUDY.md) ran once on six coins from 2020 to 2025. A down warning made a large fall 3.8 times as likely as a random hour, but caught only 12% of large falls and was followed by none 94% of the time. As a 12-hour filter on new longs it would have skipped 10 pattern trades and no daily trend trades, so its rule was not met. Nothing changes in trading.
Consequences:
- `market_structure.shock.down_warnings` stays, with its tests, so a later decision can use it.
- Liquidation bursts and open interest, which were the clearest signs on 2026-11-05, can only be studied forward from November 2026.
Revisit conditions: the owner wants the warning shown as information, or six months of forward liquidation and open-interest data exist.

### D044: A demo bot on the 15M rule baseline, in its own 100 USDT account
Date: 2026-11-07.
Status: Accepted by the owner, who chose all four options on 2026-11-07.
Context: The owner wanted a bot they can watch buy and sell on the live chart, with every trade saved and profit counted on 100 USDT. The two tested strategies trade about twice a month per coin and had made no trade since D042 started.
Options considered:
- Strategy: add a faster demo in its own account; move the tested strategies to 100 USDT; or run only a faster strategy.
- Balance: 100 USDT as the starting balance at 1% risk; 100 USDT per trade; or a starting balance at 2% risk.
- Entry: at the live price seconds after the close; never missing a signal; both; or before the candle closes, which acts on unconfirmed candles.
- Chart: one coin with a picker; or all six in a grid.
Decision:
- The quant worker runs the 15M rule baseline (docs/reports/phase-4.md) at every 15M close for each core perpetual, into a separate `Demo` paper account with 100 USDT and the default risk profile. The risk engine decides every trade. The tested strategies and their `Paper` account are unchanged.
- The bot enters at the live price. The risk engine sizes the trade from the live mid, rounded against the trade, and the entry fills there plus half the spread and slippage at the decision time, about 10 seconds after the close. The shared simulator checks only the stop in that first minute (docs/10, fill rules).
- The API takes `account=paper|demo` on signals, summary and positions, and adds `GET /paper-trading/trades` with every fill. The dashboard's Demo bot page draws entries, exits and open levels on the live chart, with the account and the trade history.
Consequences:
- The baseline showed no edge in its only backtest, so the page labels it untested. Its results are a demonstration, not evidence for the tested strategies.
- More decisions: 24 a day per coin instead of 1. In its three-month backtest the baseline made 9 BTC trades and 32 ETH trades, so a few trades a week across six coins is a rough expectation, not a promise.
- At 100 USDT, 1% risk is 1 USDT. Trades whose size falls below Binance's minimum (0.001 BTC, 20 USDT of ETH, 5 USDT otherwise) or whose notional would exceed equity are refused, and the refusal is shown with its reason.
- Live entries do not match the backtest entry rule exactly, so demo fills are not used to validate backtests.
Revisit conditions: the owner wants a different strategy on the page, a different balance or risk, or the demo account to stop.

### D045: A money plan across all coins, sized by tested evidence
Date: 2026-11-09.
Status: Accepted by the owner, who chose all four recommended options on 2026-11-09.
Context: The owner wanted the whole fund divided across many coins, with more money on the signals with the most potential, and a target of 3% profit a day. They asked to make Python's engine more accurate before Claude is added. The best tested strategy averaged about 0.02% a day in its backtest, and Python's setup score is mostly fixed numbers, so it does not measure a chance of winning. Of the first 12 live signals, 7 were refused because the account was full, and all 12 were sells on coins that move together.
Options considered:
- The 3% target: stop new trades for the day at +3%; only show progress; or raise risk to about 18% a trade to chase it, where three losses in a row would cost about 45%.
- Splitting money: by tested evidence per strategy; equally; or by the current setup score, which would mostly favour farther targets.
- Account: a new 1,000 USDT account; the 100 USDT demo, where most tested trades fall below Binance's minimum size; or the main account, which would break its comparison with the backtests.
- Accuracy first: test the strategies on the other four coins; build a tested signal score; wait for live results. The owner chose all three.
Decision:
- A new `Portfolio` paper account with 1,000 USDT runs the daily trend, the 1H pattern breakout and the 15M rule baseline on all six core perpetuals. The `Paper` and `Demo` accounts are unchanged.
- Each strategy asks for a share of the 1% risk per trade set by the six-coin replication study, pre-registered and run once (docs/33): daily trend full, pattern breakout half, 15M baseline a quarter.
- At each 15M close, all due strategies are decided for all coins together. The strongest evidence is served first and equal evidence splits what is left, within the room for open risk, the daily loss budget, exposure and position slots.
- New limits, for this account only: at most 3% of equity at risk across open trades, new trades stop for the UTC day at +3%, and up to 10 positions. Risk per trade stays at most 1%, exposure within equity, and the daily loss limit 3%.
- The risk engine decides every trade. A share can only lower risk, as in D038, and is stored with each assessment.
Consequences:
- The +3% stop is a ceiling, not a target. Nothing trades more to reach it, and most days will end well below it.
- Shares weigh backtest evidence; they are not win probabilities, and the dashboard says so.
- The 15M baseline fills on one-minute candles, which exist only from 2025, so its quarter share rests on no multi-coin test.
- Correlated coins still count as separate trades. The 3% open-risk limit caps what they can lose together.
- The signal score is the next accuracy step. It needs its own pre-registration and a test on history before it can change size.
Revisit conditions: the study's shares are replaced by forward paper results after enough trades per strategy, a tested signal score passes, or the owner wants different limits.

### D046: Signal score, tested and not adopted
Date: 2026-11-10.
Status: Studied at the owner's request, who chose that a passing score may only lower risk on weak signals. Not adopted by its own pre-registered rule.
Context: The money plan (D045) gives every signal from one strategy the same share. The owner asked for more money on the signals with the most potential, and for Python to become more accurate before Claude is added.
Decision:
- The study in [34-SIGNAL-SCORE.md](34-SIGNAL-SCORE.md) scored every tested trade on six coins from 2020 to 2025. The four conditions were the coin's and Bitcoin's 200-day trend, volume and funding, and a signal was weak with two or more against it. The rules were committed before the run, as `c0482f3`.
- Strong signals made +0.19R a trade and weak ones +0.10R, with an interval for the gap of -0.15 to +0.32. Among shorts the gap reversed, and it was positive in only 2 of 6 years. Halving weak signals would have cut profit more than drawdown. Four of the six checks failed, so nothing changes in trading.
- While preparing the study, the backtests were found to charge no funding from 2020 to early 2023, because Binance's history has no mark price before March 2023. The loader now uses the last 15M close as the mark. The corrected six-coin study gives the same shares (docs/33), with the daily trend at +0.40R a trade instead of +0.44R.
Consequences:
- `trade_signals/signal_score.py` and the study stay, with their tests, so the run can be reproduced.
- From 2026-11-10, at the owner's request, the four conditions are stored with every live signal in every account and shown on the Bot page. They are information only: the risk engine never reads them, and they set no size. Forward results can then test the score on data it was never fitted on.
- Python's setup score in `trade_signals/quality.py` is still a checklist of mostly fixed numbers, and it sets no size.
- Earlier reports for docs/27 and docs/29 were run without that funding, and are kept as they were, with corrected figures beside them.
Revisit conditions: none for this version. A changed score is a new trial, tested on forward paper results.

### D073: The profit lock tested on history; it stays, and switching it off is recommended
Date: 2026-11-15.
Status: Run at the owner's request ("do step 3, 4, 5") by the rules pre-registered in [43-PROFIT-LOCK-STUDY.md](43-PROFIT-LOCK-STUDY.md) at 03:27 UTC, and applied by them. The owner was away and had given permission to make the decisions.
Decision:
- **The decision rule changes nothing.** The lock (D066) stays on every strategy, because no strategy's own 95% interval is entirely below zero.
- **The results, as change in R per trade from the lock:**
  - the daily trend -0.117 (-0.25 to 0.00);
  - the 1H pattern -0.045;
  - the 4H gap -0.015;
  - the 15M rule -0.042 (-0.09 to +0.01);
  - **all four pooled -0.050, with an interval of -0.086 to -0.015, entirely below zero.**
Consequences:
- **The pooled result is reported to the owner with a recommendation to switch the lock off.** That is their call, because the pre-registered rule decides by strategy.
- **All 6,093 replays with no rule matched the engine.** On the 39% of trades where the lock acted, it kept 724.7R and gave up 894.1R.
Revisit conditions: the owner switches the lock off or changes its values, which is a new trial.

### D072: A cap on each direction, set at 60% on the real account; exit advice stays shadow; demo stays off
Date: 2026-11-15.
Status: Done at the owner's request ("do step 3"), while they were away. They said "pls do not ask any permissions just ask classification questions and do… I give you all the permissions to edit the code now". Each choice is the safe one and can be reversed. The owner had earlier given standing permission to choose the safer design when money is at risk (D067).
Decision:
- **A limit on one direction (`max_side_exposure_fraction`).**
  - All longs together, or all shorts together, waiting entries included, at most this share of equity.
  - A trade past it is refused as `DIRECTION_EXPOSURE_EXCEEDED`, and the Binance plan shrinks it to the room left on its side.
  - It is set on the Settings tab ("One direction"), saved as a profile version like every limit, and blank means none.
- **Set at 60% on the real account,** as profile version 8 through the dashboard's own limits route as the owner, audit-logged. Every other limit is as the owner left it in version 7:
  - 1% a trade and 5% open risk;
  - positions within 100%, with the largest trade at 40%, at up to x5;
  - a 3% daily loss limit and a 10% loss stop from the highest equity.
  - Demo and the paper accounts have no direction cap.
- **Claude's exit advice stays in shadow mode** (D051). Of 50 scored trades, only 4 got advice other than "hold", and those 4 lost a mean of 0.161R against the trades' own exits.
- **Binance demo stays switched off.** The owner switched it off themselves (D064), and nothing here needed it on.
Consequences:
- **Before this, the real account held four shorts worth 93% of equity** (2026-11-14). At 60%, a second big trade on the same side would have been shrunk.
- **A jump through every stop now costs at most 60% times the jump, instead of 100%.**
Revisit conditions: the owner changes the cap on the Settings tab, or wants advice acted on.

### D071: The risk engine reads the freshest quote
Date: 2026-11-15.
Status: Fixed at the owner's request ("do step 5"). A bug fix inside D044's freshness rule. The 30-second data-age limit is unchanged.
Context:
- **The ingestor saves a minute's top of book only once the minute has ended,** at its next 5-second tick. At busy closes the save ran up to 26 seconds late.
- **So signals decided late in a minute were refused as `DATA_STALE`** while live data was at hand:
  - at the daily close, the ten coins are decided one by one, and the later ones came 32 to 38 seconds into the minute;
  - at busy hourly closes, signals were refused 12 to 18 seconds into the minute.
- **On the real account, 6 of its first 86 signals were refused this way,** one of them for no other reason.
Decision:
- **The signal service also reads the ingestor's live quote,** which is published to Redis a few times a second and kept for a minute. When it is fresher than the saved row, its time, bid and ask are used.
- **If Redis cannot be read, the saved rows decide alone,** as before.
Consequences: stale refusals now mean the data really is stale.

### D070: The 15M rule's loose copy switched off; the 15M rule kept
Date: 2026-11-15.
Status: The owner's choices on the results of docs/42 (D069), each the recommended option. **Amends D059**, which added the loose copy.
Decision:
- **The loose copy (`trend_break_loose`) is switched off on every coin,** in the money plan and on both Binance accounts. It lost -0.109R a trade on ten coins pooled, with a 95% interval of -0.18R to -0.04R.
  - The money plan no longer asks it at a 15M close, so it records no signals.
  - Its code stays, named in `SWITCHED_OFF`, so it can be brought back.
- **The 15M rule (`trend_break_baseline`) keeps trading** at its untested quarter share, as the pre-registered rule says. It came to -0.046R a trade, with an interval of -0.13R to +0.04R, on 15-minute fills.
- **The Coins page (D068) shows the loose copy as switched off on every coin.**
Consequences: the bot makes fewer 15M signals.
Revisit conditions: forward paper results or a test on 1-minute history show either rule differently.

### D069: The new coins and the 15M rule tested; four pairs left out
Date: 2026-11-14.
Status: Run at the owner's request ("do it now") by the rules pre-registered in [42-NEW-COIN-STUDY.md](42-NEW-COIN-STUDY.md) at 14:07 UTC, and applied by them. The loose copy's switch-off waits for the owner, as that rule says.
Decision:
- **Left out (`LEFT_OUT`)** in the money plan and on both Binance accounts, each having lost with 95% confidence:
  - the daily trend and the 1H pattern on HYPE (on 6 and 13 trades);
  - the loose copy of the 15M rule on DOGE and HYPE.
- **The Coins page (D068) shows every new result.** Its backtest table now holds all 50 published rows, checked against the reports by a test.
- **Shares of risk are unchanged.**
Consequences:
- **The loose copy:** -0.109R a trade on ten coins, with a 95% interval of -0.18R to -0.04R. It is recommended to the owner to switch it off on every coin.
- **The 15M rule itself:** -0.046R, with an interval of -0.13R to +0.04R. It keeps trading at its untested quarter share. Both were tested on 15-minute fills, which can only lower their results, and over two years.
- **1000PEPE's live losses:** its 0 of 5 fits bad luck. On two years of history the 15M rule made +0.09R a trade on PEPE.
Revisit conditions: the owner decides on the loose copy; or 1-minute history before the holdout is loaded for more coins.

### D068: A coin scorecard on the dashboard
Date: 2026-11-14.
Status: Built at the owner's request ("start step 2"). They had asked for a score for each coin, because "some coins entries are kinda wrong", with Claude Sonnet adjusting parameters daily. Step 1 is the coin study (docs/42). This is step 2, built by Python alone. Step 3, Claude reviewing the scorecard in shadow mode, is not built.
Decision:
- **A Coins page (`/coins`) and `GET /api/v1/coins/scorecard`,** read-only. It has one row per coin the bot trades, and each row opens to every strategy on that coin.
- **Backtest evidence:** each strategy's published result on the coin (docs/33, docs/35).
  - The numbers are copied into `performance/scorecard.py`, and a test checks them row for row against the reports.
  - A pair no study ran says why it is untested.
- **Live trades:** the trades signals opened on every paper account and both Binance accounts.
  - A setup traded on several accounts counts once.
  - Each shows its wins, and the mean of the net result over the planned risk (R).
- **Entry quality,** for each entry that has a full hour of 1-minute candles after its fill:
  - how much worse than planned it filled;
  - how far the price went against it in that hour, in R;
  - how many went 0.5R or more against.
  - The fill's own minute is left out, as in docs/37.
- **The coin now:**
  - the 1H ATR(14) over the price;
  - the spread from the latest book within 10 minutes;
  - data gaps not yet repaired;
  - today's signals on the real account, or demo before it existed, with the most common refusal.
Consequences:
- **Nothing reads it to trade.** No trade, size or limit uses the scorecard.
- **First readings, 2026-11-14 at 14:42 UTC:**
  - **1000PEPE:** 0 of 5 trades won, a mean of -1.00R. Its entries went a median 0.55R against in their first hour, and 3 of the 5 went 0.5R or more. All were the 15M rule or its loose copy.
  - **BTC:** 3 of 3 won, with entries 0.07R against.
  - **BNB:** one data gap was open, and all 8 of its signals that day were refused as DATA_INCOMPLETE.
  - **BTC's 10 signals that day** were refused as QTY_BELOW_MIN, because the real account is too small for Binance's smallest BTC order.
- **Live counts are small.** The page says a coin's live result is mostly luck until it has dozens of trades.
Revisit conditions: the docs/42 study reports, and its results join the table; or Claude's shadow review needs a daily snapshot.

### D067: A moved stop frees no room for more trades
Date: 2026-11-14.
Status: Done at the owner's request ("you can edit into a best way, if it could lose my money"), after the research report of 2026-11-14 warned about D066's risk count. **Amends D066**, under which a stop past the entry counted as no open risk.
Context:
- **D066 let a lock open room for more trades.** A locked trade counted as no open risk, so it freed room under the open-risk cap for more trades in the same direction, and crypto coins rise and fall together.
- **Stops fill at market, and a gap can pass them.**
  - On 2025-10-10, Binance's worst one-minute drops were 5.3% on ETH, 12.4% on SOL, 21.6% on XRP, 28.6% on DOGE and 34.1% on 1000PEPE.
  - A +1R lock on a 1.4% stop, filled at the bottom of ETH's worst minute, would have lost about 2.8R.
- **The real account held four shorts that day,** ETH, XRP, DOGE and SOL, worth 93% of equity.

Decision:
- **On both Binance accounts, a trade's open risk never drops below what it risked at its first stop.** That is the stop the risk engine approved. Otherwise it is what the trade could lose at the stop Binance holds.
  - A stop moved toward or past the entry, by the profit lock or the daily trend's trail, protects that trade but frees no room for another.
  - A stop the owner moves further away counts in full, as under D066.
- The profit lock itself is unchanged, and so are every limit and the paper accounts.

Consequences:
- After a lock, the open-risk cap stays as full as before it, so the bot opens no more trades than it would have without the lock.
- With the owner's 100% room, positions in one direction can still reach the whole equity. A cap on each direction is an option for the owner; it is not built.

Revisit conditions: a portfolio test of how to count locked trades, with a 2025-10-10 stress test, as the research report proposes; or the owner asks for locked trades to free room again.

### D066: The profit lock on Binance trades, and the owner's own stops kept
Date: 2026-11-14.
Status: Built and live at the owner's request ("if the coin passes the profit 3% then increase leverage and put the stop loss to 2% profit, so which is take out the fund right?"). From clarifying questions with numbers, the owner chose:
- scaled to each trade's stop, not a fixed percentage;
- fix the risk count and keep the limits;
- build it on real now, with no backtest first;
- when they move a bot stop in the Binance app, keep their stop.

**Amends D060**, under which only the bot's own orders counted on the real account.
Context:
- **A fixed +3% means a different thing for each strategy,** from the 210 signals stored by 2026-11-14:
  - 0.29R on the daily trend, whose median stop is 10.3% away;
  - 0.73R on the 1H pattern breakout (4.1%);
  - 1.9R to 2.4R on the 15M and news strategies (1.2% to 1.6%).
- **The nearest rule tested was not adopted** (docs/37, D050). Breakeven at +1R changed results by -0.023R, -0.005R and -0.073R a trade.
- **Leverage changes only the margin a trade holds.**
  - The owner's two real shorts held 98.6% of equity against the 100% room the owner set, so the room stopped new trades, not margin.
  - On isolated margin, Binance frees nothing when leverage rises. The margin must be removed in a separate call, and removing it moves liquidation nearer.
- **On 2026-11-14 at 02:11 UTC the bot closed the real SOL short at market (+0.30 USDT).**
  - The owner had changed its stop in the Binance app.
  - Binance refused the bot's own stop beside it with -4130, because a whole-position stop already stood.
  - The minute check then closed the position as unprotected.
  - The owner closed the XRP short from the app at 04:17 UTC, at +2.0%.

Decision:
- **The profit lock (`risk_management/profit_lock.py`) on both Binance accounts, at each minute check.**
  - Once the mark price is 1.5R beyond the entry fill, the bot's stop moves to 1R beyond the fill.
  - R is the planned entry to the first stop. The new stop is rounded to the tick that keeps a little less profit, and a stop only ever tightens.
  - On the real ETH short (fill 1902.98, R 38.24), that is a stop at 1864.74 once the mark reaches 1845.62.
  - The move cancels the bot's stop and places the new one, as the daily trend's trail does. It is recorded, so the minute check and the risk count read the new stop.
  - The mark price is read once a minute, so a spike past +1.5R that turns back within the minute is missed.
  - The paper accounts keep the strategies' own exits, for comparison.
- **A stop past the entry counts as no risk.** D067 changed this the same day: a moved stop now counts the risk at its first stop.
  - A Binance trade's open risk is what it loses at its stop, and zero once that stop is past the entry, as on paper. Until now the distance counted either way, so a locked or trailed stop still used the open-risk budget.
  - The stop counted is the one Binance holds, the bot's or the owner's, else the one recorded.
  - The owner's own positions still count at their whole value.
- **The owner's stop is kept.**
  - On the real account, a bot trade the owner protects with a stop of their own, one that closes the whole position, stays open.
  - The bot restores nothing and closes nothing. It never moves or cancels the owner's stop, the profit lock and the trail included.
  - A stop Binance refuses with -4130 closes nothing either, on both accounts.
- **Leverage, the room, the largest trade and every other limit are unchanged.**

Consequences:
- **No backtest backs the lock.** The research of 2026-11-14 (`data/research/`, not in Git) found no study showing that a profit lock adds expected return. Under a random walk a lock changes the spread of results, not the mean, and on trend strategies stops cost money.
- **On the daily trend the lock sits about 15% from the entry,** beside its own 10-day trail, so it should rarely act there.
- **The lock can cut short a winner that would have reached its target, but it cannot make a loss larger.** Stops fill at market, though, so a gap can still turn a locked trade into a loss. On 2025-10-10, Binance's one-minute drops reached 5.3% on ETH and 34.1% on 1000PEPE.
- **New worker log events:** `exchange_profit_locked`, `exchange_profit_lock_refused`, `exchange_profit_lock_failed` and `exchange_stop_already_held`.

Revisit conditions: a test of the lock on 2020 to 2025 with 1-minute data, or 30 locked trades on the real account; the owner changes its values or wants it on paper.

### D065: The Signals page filters, and opens an entered trade on the chart
Date: 2026-11-13.
Status: Built at the owner's request ("make filters in the signals tab, if a trade entered so in the table there should be ability to navigate to the chart like binance app does").
Decision:
- **Filters, kept in the page's address,** so a reload and Back from the chart keep them:
  - account: real, demo, or one of the three paper accounts;
  - coin, strategy, side, and the risk engine's decision;
  - result: entered, open, won, lost, waiting, or not entered;
  - period: today, 7 days, 30 days or all.
  - The API applies them (`GET /api/v1/signals`) to at most the newest 500 matches. The page opens on the account last chosen on the Bot page, else the real one.
- **A table, one row per signal:**
  - The row shows its time, coin, strategy, side, the planned entry beside the filled price, the stop, the targets, the net reward to risk, the planned risk, the decision with its codes, and the result.
  - A row opens to everything the risk engine weighed.
  - A line above it totals the trades shown: entered, won, lost, open, and the closed trades' net. It says whether that is real money, test funds or simulated.
- **Results come from fills, never from the plan.** Each signal now carries its `trade`: state, entry and exit times and prices, and net after fees and funding.
  - On Binance it is the trade the signal's entry order opened, rebuilt from Binance's own fills (D057).
  - On paper it is the simulator's position.
  - A limit entry counts as waiting only while it is its coin's newest entry and its good-till time has not passed.
- **The Chart link:** an entered trade's Chart link opens the Bot page on its account, coin and timeframe. A 4H or daily signal opens on 1H.
  - The chart loads older candles until the trade is in view, then scrolls to it.
  - It marks the entry fill with its price and the exit with its result.
  - A bar above the chart describes the trade, with Back to signals and Clear.
  - The Results tab's completed trades have the same Chart button.
- A paper signal's link keeps the Binance account chosen on the Bot page, so that account's own markers stay on the chart. The bar names the paper account.
Consequences:
- Read-only: nothing here can place, change or close a trade, and the list of write routes is unchanged.
- Each read rebuilds the account's trades from every stored fill, as the orders and results routes do. That is quick at today's few hundred fills.
- On 2026-11-15 the orders table took the same waiting rule. It had shown an older, expired limit entry as waiting whenever a newer one on its coin was resting.
Revisit conditions: the owner wants other filters, or an account's signals often pass the 500 cap.

### D064: Demo trading gets the same on/off switch, and is switched off
Date: 2026-11-13.
Status: Done at the owner's request ("stop the demo for now (put a switch)").
Decision:
- **Binance demo has the switch too.** It is in its account panel on the Bot page (`PUT /api/v1/exchange-demo/arming`), and both accounts' status now carries `armed`.
  - Demo trading is on until first switched off, as before.
  - Its switch needs only a confirm, no password and no check, since its funds are test funds.
  - Off stops new demo trades; open trades keep their stops and targets, and closes from the dashboard still run.
- **Switched off at 12:40 UTC on 2026-11-13** through the dashboard's API as the owner, audit-logged. No demo position was open. The real account stayed on.
- The paper accounts keep running, and the money plan still decides every coin for them.
Revisit conditions: the owner switches demo back on.

### D063: A switch on the dashboard turns real trading on and off
Date: 2026-11-13.
Status: Built at the owner's request ("put a switch to on/off the real account"). **Amends D060**, where only the terminal could arm the real account.
Decision:
- **The switch** sits in the real account's panel on the Bot page and shows whether real trading is on. The status reads it from the database, so a change shows at once.
- **Off** needs only a confirm. It stops new trades at once; open trades keep their stops and targets on Binance.
- **On** needs a confirm and the owner's dashboard password, checked as at login with the same rate limit. The API refuses it unless:
  - the bot saved the account within the last 5 minutes;
  - its check of the key and the account has run and found no problem.
- **Every attempt is in the audit log:** `exchange_live_armed`, `exchange_live_disarmed`, or `exchange_live_arm_refused` for a wrong password. The route takes requests from the dashboard's origin only (`PUT /api/v1/exchange-live/arming`).
- The terminal commands `binance_live arm` and `disarm` still work.
Consequences:
- Anyone with the dashboard session and the password can turn real money on. The dashboard runs on this Mac, and the password is asked again on purpose.
- On the day it was built, the owner connected the real futures wallet (40.84 USDT, 11:51 UTC). On the Settings tab they set 5% a trade (version 3), with 5% open risk, 100% room, a 60% largest trade, up to x5, 3% daily loss, a +3% daily stop and a 10% loss stop from the highest equity. They turned real trading on at 12:01 UTC. The 3% daily loss limit caps any one trade's loss at about 1.23 USDT there.
Revisit conditions: the dashboard is reached from anywhere but this Mac, such as on Railway (D026).

### D062: Claude's daily cost limit, $0.50, shown and set on the dashboard
Date: 2026-11-13.
Status: Accepted by the owner ("claude should have daily limit too"), who chose the recommended options after the numbers below.
Context:
- A daily limit already existed: $3 for every Claude call together (news labels and exit advice), checked before each call. It was written twice in code and shown nowhere.
- Use so far: 215 calls in three days, $0.035 in all. At most $0.022 and about 153k tokens in a day (11 Nov), on Haiku 5.5. The limit was never reached.
Options considered: what the limit covers (Claude's cost, or a cap on Claude's actions for when it may act), and $0.50, $1 or $3 a day.
Decision:
- **$0.50 a day** for every Claude call together, about 25 times the busiest day so far.
- **One setting:** kept in `ai_budgets` (migration 0022), newest row in force, append-only. The news pipeline and the exit reviews read it before every call, so a change applies at once. At the limit, calls stop until 00:00 UTC (`skipped_budget`).
- **On the dashboard:** the Claude tab shows today's spend, calls and tokens against the limit. The Settings tab changes it: from the dashboard's origin only, from $0 to a $3 ceiling (the old limit), each change written to the audit log. $0 stops every call.
- A cap on Claude's actions was not chosen. Claude still acts on nothing (D051).
Consequences:
- A runaway loop or a flood of news can cost at most about $15 a month.
- If later work asks Claude more, such as the full trade analyst (docs/28), the limit may need raising; that is the owner's change on the Settings tab.
Revisit conditions: the limit is reached on an ordinary day, or Claude's work grows.

### D061: Room for several trades at once on Binance demo: 300% for all positions, 100% for one
Date: 2026-11-13.
Status: Accepted by the owner, who asked why Python "cannot put leverage" and said that money in the account should start new trades instead of depending on one. They chose both recommended options. Binance demo only; the real account is unchanged.
Context:
- Every Binance demo trade had used x1, and Binance never refused a leverage setting. Under D048, Python uses the lowest leverage at which the margin fits. With all positions capped at 90% of equity, x1 always fitted.
- Leverage never changes what a stop loses or a target makes, so the limit on trades was the 90% cap, not money.
- At 5% a trade, one trade wants a position of about 44% of equity (daily trend, median stop 11.3%), 72% (1H pattern, 3.45%) or 177% (4H gap and 15M CHoCH, 1.41%). So one or two trades filled the cap.
- Of 47 signals assessed on Binance demo, the cap shrank 42. 40 of those were then too small for Binance's minimum order and refused; 6 traded. The 10% open-risk limit was never the reason.
- The real account, at 1% a trade, holds positions of about 9% to 36% of equity each, so several already fit. It is unchanged.
Decision:
- **Binance demo profile version 9**, saved through the Settings tab's API (audit-logged), with every other limit kept from version 8:
  - all positions together up to 300% of equity;
  - no single position above 100% of equity.
  The rest: 5% a trade, 10% open risk, 10% daily loss, up to x5, a 20% daily profit stop, and a 20% loss stop from the highest equity.
- **A largest-single-position limit** (`max_position_fraction`) in the risk profile, stored with the other plan settings. The risk engine refuses a larger trade as `EXPOSURE_EXCEEDED`. The Binance plan shrinks it to fit, as it does for the total cap (D058). The Settings tab has a "Largest single trade" field; blank means no limit.
- **The leverage a trade starts at** is the cap on all positions, rounded down, at least x1 and at most the maximum. That is x3 with 300%: three positions of 100% then fit the margin, where at x1 the first would hold almost all of it. It still rises, up to x5, if the margin does not fit. With the cap at or below 100%, it is x1 as before (D048).
Consequences:
- About three or four trades can be open at once on demo. Their stops together still lose at most 10% of equity.
- Leverage x3 to x5 holds less margin and brings liquidation closer. The risk engine still refuses a trade whose liquidation is not at least one ATR beyond its stop.
- A gap through every stop at once loses more: a 10% move against 300% of equity in positions is about 30% of equity. On 10 October 2025, Binance futures fell 12.9% (BTC) to 67.6% (PEPE) within about 75 minutes.
- Smaller, tighter-stop trades are no longer squeezed to below Binance's minimum by one large position. Some still are: BTC's smallest order is about 70 USDT.
Revisit conditions: the loss stop is reached, or a week of demo results with several trades open at once.

### D060: The owner's real Binance futures wallet, beside demo trading, with closes from the dashboard
Date: 2026-11-13.
Status: Accepted by the owner. After the trade-offs below, they chose the main account's futures wallet, a capital of "as I put in there", 1% a trade and keeping demo running. **Replaces D016's paper-only rule and rule 13 in `CLAUDE.md`**, as D048 and D053 required.
Context: The owner asked to put their real account on the Bot page, to close trades from the system, and for closes made in the Binance app to show on the dashboard, so the USDT is free for the next trade. The bot must read only the futures balance, never the Overview, Spot or Funding.
- Binance demo when asked: 1 completed trade, +1.11 USDT (+2.23R), and 4 open after three days. Equity was 101.99 on its 100 USDT budget, too few trades to show an edge.
- Backtests from 100 USDT (six coins, 2020 to 2025): 1% a trade ended at 591 with a deepest fall of 37%; 2% at 2,161, fall 61%; 5% at 7,897, fall 93%.
- Binance cannot limit a key to reading futures: a key with reading on reads every wallet. Self-generated Ed25519 keys may trade without an IP restriction; system-generated HMAC keys cannot.
Options considered:
- Account: the main account's futures wallet, guarded by code and key permissions; or a sub-account, where Binance itself hides every other wallet. The sub-account needs its own email, and the owner logs in to it to close a trade in the app.
- Capital: a fixed amount (50, 100 or 200 USDT) plus the bot's own results; or what is in the futures wallet.
- Limits: 1%, 2% (D053) or the demo's 5%.
- Demo trading: keep it beside the real account, or stop it.
Decision:
- **The real account** is a new `exchange_live` account mode, `Binance real` (migration 0021).
  - The whole futures wallet is the capital: what the owner put in is the equity first seen plus transfers since.
  - Transfers are read from the futures wallet's own income history. Each one moves the day's starting equity by as much, so it is never a profit or a loss.
  - The account is made by the quant worker when it first sees USDT in the wallet.
- **The limits** are `EXCHANGE_LIVE_PROFILE`: the project's defaults with a 20% loss stop. That is 1% a trade, 3% across open trades, 3% daily loss, positions within 100%, up to x3, and the +3% daily stop. They change on the Settings tab, each save a logged version.
- **Futures only:**
  - The gateway for the real account reaches `https://fapi.binance.com` alone, and only the paths in `FUTURES_PATHS`. Any other request is refused before it is sent.
  - The only other call is Binance's key-permission endpoint, in `execution/key_check.py`.
  - The bot refuses a key that can withdraw, transfer, or trade spot, margin, options, portfolio margin or FIX. It requires futures. It checks hourly, with one-way mode and single-asset margin, and every 5 minutes while a problem stands. Any problem stops new trades.
- **Arming:** no real trade opens until the owner runs `binance_live arm --yes` in the terminal after its check passes. Arming is append-only and records who did it and when. The dashboard shows "Real money: armed" on every page.
- **Only the bot's own:**
  - On the real account the bot touches only orders with its client ID prefix, and positions on coins of its open trades. A trade ends when the minute check sees its coin flat.
  - The owner's own position is never given a stop, moved or closed. It still takes its coin, and counts at its whole value as open risk.
  - The kill switch closes the bot's trades only. Demo trading keeps clearing its whole account.
- **Closing:**
  - The Bot page has a Close button on the bot's positions, and Cancel on a waiting entry, with a confirm step.
  - The API stores the request, from the dashboard's origin only, for a trade of the bot's only, and writes it to the audit log.
  - The quant worker, the only holder of the key, carries it out within seconds. It cancels a waiting entry, closes at market with a reduce-only order, then cancels the bot's stop and targets. A refused close leaves the stop and targets in place.
  - It works for demo trading too.
- **Closes in the Binance app:** the minute check sees the coin flat, records the trade's end and copies its fills at once. The dashboard shows it within a minute, and its margin is free at the next decision.
- **Demo trading** keeps running beside it on the same signals. The Bot page switches between Real and Demo and remembers the choice.
Consequences:
- Real losses are possible. A stop can fill worse than planned, and a crash can skip it. Backtests are not proof of future profit.
- The owner's own trades in the same wallet share its money with the bot. Their results change its equity and count toward its daily limits and loss stop. Their whole value counts as open risk, so a large position of the owner's can leave no room for the bot's trades.
- The bot trades only while this Mac is on. Its stops and targets sit on Binance and protect open trades while it sleeps.
- The real account's minute check adds to the request weight this IP spends on `fapi.binance.com`, which the market data shares. Its transfer read alone weighs 30 a minute. A 429 from Binance stops requests rather than retrying them (D048).
- Claude still places no trade and closes none. Its exit advice stays in shadow mode (D051).
Revisit conditions: the loss stop is reached; the hourly check finds a problem; a month of real results; or the owner wants a sub-account.

### D059: More chances to trade: the daily trend tested all day, a loose 15M copy, HYPE and NEAR, and 5% a trade
Date: 2026-11-12.
Status: Accepted by the owner, who asked for trades "all the time if there are signals" and chose every option offered. Resolved by follow-up questions: keep the 15M rule and add a looser copy, and HYPE with NEAR. **Amends D033** (ten coins, not eight) and D058's 10% (5% a trade).
Context: Python already decided every coin at every 15M close, 147 closes since Binance demo started. Only 5 closes had a setup, because the rules rarely fire:
- The 15M rule found no break on the latest candle 966 times in 1,032.
- The 1H pattern found no breakout 250 times in 254.
- The daily trend decides only at 00:00 UTC.
- At 10% a trade, the 10% open-risk limit allowed one full trade at a time.
Decision:
- **5% a trade,** saved through the Settings tab's API as version 6. It kept the owner's own changes made at 02:50 UTC: positions within 90%, a 20% daily profit stop, and a 5% loss stop measured from the highest equity.
- **The daily trend checked all day** was pre-registered in [41-INTRADAY-TREND.md](41-INTRADAY-TREND.md) and run once. It made 416 trades at +0.325R, against 344 at +0.397R for the daily close. It failed its rule, so **the daily trend still decides at 00:00**.
- **A loose copy of the 15M rule**, `trend_break_loose`, accepts a break of structure on any of the last 3 candles. The 15M rule itself is unchanged. The copy runs in the money plan, on Binance demo and the paper money plan, at the smallest share, untested. The 15M rule cannot be backtested before the holdout.
- **HYPEUSDT and NEARUSDT** passed the D033 screen, at 526M and 550M a day (migration 0020). They are backfilled the same way as ZEC and PEPE, and trade untested. Free disk allowed two coins, not four.
  - News links HYPE by "Hyperliquid" and NEAR by "NEAR Protocol" or the contract name only, because "hype" and "near" are everyday words.
Consequences:
- **The loss stop and 5% interact:** with the stop 5% below the highest equity and 5% a trade, little room is left for new trades, and one full loss can stop the bot until limits are saved again.
- Ten coins and a looser 15M rule mean more signals. All of the new ones are untested.
Revisit conditions: the loose copy's forward record in the Results tab, or free disk for more coins.

### D058: Binance demo at 10% a trade, positions within 80%, and a settings page for its limits
Date: 2026-11-12.
Status: Accepted by the owner, who chose "Raise the ceiling to 10%" after three questions with the backtest numbers. **Amends D053's limits and the brief's 2% per-trade hard ceiling.** Test funds only; real money stays impossible.
Context: The owner asked to use 80% of capital for trades, with risk around 10%, and for a settings page to adjust these.
- **What the backtests showed:** the three tested strategies' 1,389 trades, from 100 USDT, compounding:
  - 2% a trade ended at 2,161 with a deepest fall of 61%;
  - 5% ended at 7,897 with a fall of 93%;
  - 10% fell to almost nothing on the way and ended at 38.
  - The growth-maximizing risk (Kelly) on those trades was 3.9%.
- **Choices:**
  - The owner first chose 10% per trade and also keeping the 2% ceiling.
  - Asked to resolve the conflict, they chose to raise the ceiling.
Decision:
- **Ceilings:**
  - The risk engine's per-trade ceiling rises from 2% to 10%, and its daily loss ceiling from 5% to 10%.
  - A new ceiling caps all positions at 5× equity.
  - Defaults are unchanged: 1% per trade, a 3% daily loss limit.
- **Binance demo, profile version 3 (migration 0019, `EXCHANGE_DEMO_PROFILE`):**
  - 10% per trade, 10% across open trades, and a 10% daily loss limit.
  - All positions within 80% of equity.
  - Leverage up to 3×, a 20% loss stop, and the +3% daily stop, all unchanged.
- **Shrinking to the position cap:** on Binance demo, a trade that only the position cap refuses is shrunk to the room left, as the paper money plan already did, instead of refused. At 10%, a 15M trade with a 1.4% stop would need a 714 USDT position. Shrunk to 80 USDT, it risks about 1.1 USDT. A daily trend trade with an 11% stop risks up to about 8.8.
- **The loss stop** can follow profits: with `loss_stop_from_high`, it is measured from the highest equity the bot's closed trades reached, not the starting budget.
- **The Settings tab on the Bot page** shows these limits and their ceilings: risk per trade, risk across open trades, the position cap, leverage, the daily loss and profit stops, the loss stop and its mode.
  - Saving goes through `PUT /api/v1/exchange-demo/limits` and becomes a new profile version, written to the audit log. The bot uses it from its next close.
  - The request is refused unless it comes from the dashboard's own origin.
  - Saving also restarts trading after the loss stop.
Consequences:
- A losing trade can cost up to 10 USDT on 100, and two in a row about 19%. With the 20% loss stop, about two full losses stop the bot until the owner saves limits again.
- The open-risk limit at 10% means one full-risk trade at a time.
- The +3% daily stop now ends a day after any good win. It can be changed on the Settings tab.
Revisit conditions: the loss stop is reached, or the owner changes the limits.

### D057: Binance demo results from Binance's own fills, in a Results tab
Date: 2026-11-12.
Status: Accepted by the owner, who asked for win rates, completed trades and profit per coin on the Bot page. They chose Binance demo only, every breakdown offered (by strategy, long and short, by day, a strategy by coin grid), every extra figure offered (average R and profit factor, fees and funding, drawdown and streaks, an equity curve), and a new Results tab.
Context: The page showed orders and open positions, but no results. Binance closes trades at stops and targets itself, and nothing read those closes back. The 15M rule's PEPE trade, opened at 15:00 UTC on 2026-11-11, had closed overnight, and its result was not recorded.
Decision:
- **Copying:** the quant worker copies Binance demo's fills and funding every 5 minutes into append-only tables (migration 0018), because Binance keeps them only 3 months.
- **Rebuilding:** `performance/results.py` rebuilds completed trades, from the opening fill to flat.
  - A fill through flat is split: its profit goes to the closing part, and its fee by size.
  - Funding goes to the trade open on its coin at the time.
  - Fees in another asset are kept apart.
- **The bot's trades only:** a trade is the bot's when Binance's order ID of its opening fill is one of the bot's entry orders. That match also gives its strategy and planned risk, and so its R. Other trades are left out and counted.
- **The figures:** `GET /api/v1/exchange-demo/results?period=7d|30d|all` serves them, built in `performance/report.py`. The Bot page shows them in a Results tab: headline figures beside the chart, and the equity curve, breakdowns and trade list below it.
- **Definitions:** a trade is won when Binance's booked profit, less fees, plus funding, is above zero. Profit factor is wins over losses. The deepest fall is measured on the equity curve after each closed trade, from the period's starting equity.
Consequences:
- **The orders table**, at the owner's next request, shows what each order means in USDT (`performance/orders.py`): its value, a stop's or target's result if it fills (before fees), the entry's profit now or its closed net, and its risk.
- The API still never holds keys: it reads what the worker stored.
- Open trades are not in the results. Closes still show on the chart only as lines disappearing.
- Results are on test funds and few trades, so they are not evidence of an edge yet.
Revisit conditions: Binance's user data stream is built, which would report fills as they happen.

### D056: The news move strategy: a strong 1H move confirmed by news, trading on Binance demo
Date: 2026-11-11.
Status: Accepted by the owner, who chose "Price move + news agree" and "Binance demo now" over the recommended shadow run. **Amends D055**: news may now confirm a Python move, but still never starts a trade alone.
Context: The owner asked whether Python trades when the news signal comes. It did not. They asked for a strategy.
- Research:
  - In stocks, moves with public news tend to continue, and big moves without news tend to reverse (Chan, 2003).
  - For Bitcoin, news sentiment has some value over days and weeks, and no clear intraday edge after costs.
  - There is no labelled news history here, so the news part cannot be backtested.
Decision:
- The rules were pre-registered in [40-NEWS-MOVE-STRATEGY.md](40-NEWS-MOVE-STRATEGY.md) before any code or run. At each 1H close:
  1. Python finds a strong move: a body of at least 1.5 ATR, with a strong close.
  2. The signal service asks the injected news reading (D055) whether it agrees with the move.
  3. If it does, the move trades at market with a 1.5 ATR stop and targets at 2R and 3R. A neutral, opposite or failed reading means no trade.
- It joins the money plan at the smallest share, as an untested strategy (D045). That is 0.5 USDT risk a trade on Binance demo, and 0.25% in the paper money plan. Every trade goes through the risk engine.
- The trading code still never imports the news module: the reading comes through the injected interface. The import rule is renamed "trading reads news only through the injected reading (D055, D056)".
- **Context run once:** the price rules alone on six coins, 2020 to 2025, made +0.017R a trade over 4,555 trades, with a 95% interval of −0.028 to +0.059. That is no edge, so any edge must come from the news check.
- **Stop rule:** after 30 closed paper trades, the strategy is removed if its mean R is below zero with 95% confidence.
Consequences:
- The strategy will trade rarely, mostly BTC and ETH, which most of the news is about.
- A planted or wrong story can confirm a move, but cannot open a trade without one.
Revisit conditions: 30 and 60 closed paper trades (docs/40), or the news signal test (docs/39).

### D055: A news signal, recorded and tested forward, never trading
Date: 2026-11-11.
Status: Accepted by the owner ("yes, get the signal from news too"), after being told that news changes no trade and why a news signal should be tested first.
Context: Finnhub crypto news went live that day and Claude labels each story. The owner asked whether positive news makes the AI tell Python to trade. It does not. They then agreed to record news beside each signal for a test, and asked for a signal from the news as well.
Decision:
- **The reading:** Python adds up Claude's labels on each coin's stories from the last 12 hours, weighted by impact and relevance, by a fixed rule (version 1, `news_intelligence/reading.py`). A score of +1.5 or more is bullish, −1.5 or less bearish, otherwise neutral. A story counts only once it was seen and labelled, so nothing from later is used. Pre-registered in [39-NEWS-SIGNAL.md](39-NEWS-SIGNAL.md) with its pass rule.
- **Every Python signal**, in every account, stores whether the news agreed with it (`news_alignment`) and the reading behind it (`news_context`, migration 0017). The signal service gets this through an injected interface after the risk engine has decided. A failed reading is stored as "unavailable" and loses nothing.
- **At every 4H close**, each coin's reading is stored in `news_readings` with the close price, to be scored forward.
- **No trading code reads news.** A new import rule, "news is evidence only (D055)", keeps the trading, risk, execution, paper trading and backtest code from importing the news module, as D040 does for forecasts.
- **The Bot page** shows the coin's reading now with its stories, labelled untested, and says beside each signal whether the news agreed.
Consequences:
- No cost beyond the labels Claude already makes for the News page.
- A pass lets the owner choose that conflicting news skips or halves a trade. News never starts a trade or raises risk.
Revisit conditions: the docs/39 test runs, at 150 bullish or bearish readings or on 2027-01-31.

### D054: Every strategy trades on Binance demo, limit entries included, and the Bot page shows Binance only
Date: 2026-11-11.
Status: Done at the owner's request: "remove the money plan, 1000 USDT tab and demo, 100 USDT tabs and make sure that all the strategies work in the binance demo". **Amends D048's version 1 limit** of market entries only, and D049's note that the gap strategy is refused on Binance.
Context:
- Three of the four strategies already traded on Binance demo with market entries. The daily trend and the 1H pattern had traded; the 15M rule had had no setup since Binance went live.
- The 4H gap and 15M CHoCH strategy enters with a limit order, and was refused there.
Tested on Binance demo trading on 2026-11-11, with orders far from the price, all cancelled within seconds:
- A GTD limit entry was accepted.
- A whole-position stop was refused while no position was open (`-4509`).
- A reduce-only stop and take-profit with a quantity were accepted.
Decision:
- A limit entry goes to Binance as GTD until its signal expires, so Binance cancels it unfilled. With it go a reduce-only stop for the full planned size and the take-profits. A fill is protected from the first contract, even while the Mac sleeps.
- If that stop is refused, the entry is cancelled, and anything already filled is closed.
- The minute check keeps a waiting entry's stop and targets. It cancels a waiting entry that has lost its stop. Once the entry has expired, it cancels any orders left on a flat coin, as before.
- A waiting entry counts as the coin's trade: no second signal on that coin, and its size and its loss at the stop count toward exposure and open risk. Margin Binance holds for it is not free.
- Limit entries are sized with the taker fee, as on paper.
- Stop entries would still be refused; no strategy uses them.
- The Bot page shows only the Binance demo account. The `Portfolio`, `Demo` and `Paper` accounts keep running. They are the 1% comparison, and Claude's shadow exit advice (D051) reviews their trades.
- The page draws a waiting entry as a dashed "BUY limit, waiting" line with its stop and targets. It gets no arrow until a fill is reported.
Consequences:
- Binance may fill a limit that price only touched, which the paper simulator never assumes. So Binance can fill trades that paper does not.
- If an entry fills only in part and then expires, its targets were sized for the full plan. They are reduce-only, so they close at most what is held; the first target can close a larger share than 50%.
- If price reaches the stop before the entry fills, the stop finds no position and is used up. The minute check then cancels the waiting entry, because it has no stop left.
- A fill is not reported back yet, so the page shows it as the waiting line becoming the position.
Revisit conditions: Binance's user data stream is built, or a strategy needs stop entries.

### D053: Binance demo at 2% a trade, up to 3x exposure, with a 20 USDT loss stop
Date: 2026-11-11.
Status: Accepted by the owner, who chose each option on 2026-11-11 after the numbers below. **Amends D048's limits** for the Binance demo account only.
Context:
- The owner asked whether ×10 leverage on 100 USDT means 1,000 USDT of position and more profit, and set a goal of 10 USDT a day.
- With risk set by the stop, leverage changes only the margin held and how near liquidation sits. Every trade so far had used ×1.
- On 2020 to 2025 backtests (first six coins, 1,389 trades, about 0.65 a day), the three tested strategies averaged +0.146R a trade. That is about 0.1 USDT a day on 100 USDT at 1% risk, so 10 USDT a day would need about 105% risk per trade.
- Replayed from 100 USDT one trade after another, the account ended at:
  - 591 USDT at 1% risk, with its deepest fall 37%;
  - 2,161 at 2% (fall 61%);
  - 7,897 at 5% (fall 93%);
  - 38 USDT at 10%, wiped out.
  - The longest losing run was 21 trades. Overlapping trades were counted one after another, so real falls would be deeper.
- On the liquidation test (2.5% maintenance margin), ×10 liquidates before the stop on 83% of daily trend trades, 12% of 1H pattern trades and none of the 15M gap and CHoCH trades.
Options considered:
- Where: Binance demo first, or real 100 USDT now.
- Risk per trade: 1%, 2%, 5% (above the 2% hard ceiling), or every trade fully at ×10.
- Loss stop: 20, 50 or 100 USDT.
- The 10 USDT goal: grow toward it, every day from 100 USDT, or a daily +10 USDT ceiling.
- Open risk: keep 3% or raise it to 6%.
- Exposure: keep 1× the budget, or allow 3× with ×3 leverage.
Decision:
- The owner chose Binance demo first, 2% per trade, a stop at −20 USDT, growing toward the goal, open risk kept at 3%, and exposure up to 3× with ×3 leverage.
- `EXCHANGE_DEMO_PROFILE` in `trade_signals/portfolio.py`, and version 2 of the account's stored profile (migration 0016):
  - `max_risk_fraction` 0.02;
  - `max_total_exposure_fraction` 3;
  - a new setting, `max_total_loss_fraction` 0.2.
  - Every other limit is unchanged: at most ×3 leverage, 3% open risk, the 3% daily loss limit, the +3% daily stop, and 10 positions.
  - The evidence shares now apply to 2%: the daily trend risks 2%, the 1H pattern and the 4H gap 1%, and the 15M rule 0.5%.
- The loss stop, in the risk engine:
  - A trade is shrunk so that every open stop together cannot take equity below 80 USDT. `LOSS_STOP_REACHED` refuses a trade when no room is left.
  - Once equity is at or below 80 USDT, `exchange_loss_stops` records it against the profile version, and nothing trades until the owner sets a new version.
  - Open trades keep their stops and targets.
- The paper accounts keep 1%, 1× exposure and no loss stop.
Consequences:
- Leverage still never changes what a stop loses. It now lets tight-stop trades hold positions above the budget: up to 300 USDT of position on 100 USDT.
- A crash that skips the stops can lose more than the 20 USDT stop. A sudden 10% move on 3× exposure is about 30 USDT. On 10 October 2025, Binance futures fell between 12.9% (BTC) and 67.6% (PEPE) within about 75 minutes.
- The stop is the account's line, not a guarantee: a stop can fill worse than planned.
- At 2% per trade, the 3% open-risk limit allows about one and a half full-share trades at once, so profit does not simply double.
- 10 USDT a day stays a long-term goal. At the backtested rate it needs an account near 5,000 USDT at 2%.
Revisit conditions: the stop is reached; a month of forward demo results; or the owner wants real money, which needs a new decision replacing D016 and rule 13 in `CLAUDE.md`.

### D052: Two trending coins, and keyed news sources instead of publisher feeds
Date: 2026-11-11.
Status: Accepted by the owner, who chose ZEC and PEPE, trading them right away, and all three news sources offered. The publisher RSS feeds were then refused by their own terms.
Context: The owner asked for more trending coins and a free real-time news API. News came only from the Federal Reserve, and was linked only to BTC and ETH.
Decision:
- Coins:
  - ZECUSDT and 1000PEPEUSDT perpetuals, from the D033 screen on Binance's public data at 06:46 UTC. Their 30-day medians were 1,762M and 297M USDT a day, and their last 7 days 1.41× and 1.37× the month.
  - Both passed every condition: trading, listed in 2020 and 2023, not tagged Alpha, and listed on Binance spot.
  - Migration 0014. That makes eight coins, D033's limit.
- The owner chose to trade them right away, in every account including Binance demo, at the same shares as the six coins. No strategy has been tested on them; docs/33 covered six coins.
- History loaded: 15M and above from listing, and the 90-day window at every timeframe, 796,763 rows. Free disk went from 3.0 to 2.7 GB.
- News, migration 0015:
  - Finnhub's crypto news and Binance's announcement stream are built. Each stays off until its key is set.
  - The five publisher RSS feeds recommended first are not collected. CoinDesk, Cointelegraph, The Block, Decrypt and CryptoSlate each forbid automated collection, caching or AI processing ([crypto-news.md](providers/crypto-news.md)).
- Binance's stream needs a key from the owner's main Binance account, which must be read-only:
  - Before every connection its permissions are checked with Binance. A key that can trade, withdraw or transfer is refused.
  - A test keeps the key to that check and the stream.
  - This amends D016: the project holds one real-account key, and it cannot place orders.
- News is linked to all eight coins by name and contract symbol. The news pipeline runs every 2 minutes instead of 15.
Consequences:
- News stays information only. It changes no trade.
- Classification on Haiku measured $0.00016 an item on 2026-11-11, over 41 items. At about 100 relevant items a day that is about $0.50 a month, within the shared $3 daily limit.
- Binance announcements published while the computer is off are missed, because the stream does not resend them.
- Results on ZEC and PEPE are untested. PEPE has 2.5 years of history before the holdout.
- Each coin adds about 0.5 MB of candles a day.
Revisit conditions: the owner wants the new coins tested (the docs/33 test can run on them), a coin falls below the D033 volume floor for 30 days, or a publisher grants written permission.

### D051: An AI exit manager on Claude Haiku 5.5, in shadow mode
Date: 2026-11-11.
Status: Accepted by the owner ("start"), after D050. They chose the lowest model, Haiku 5.5, to keep tokens low.
Context: The owner wants an AI that can take the current profit when a trade looks unlikely to reach its target. Fixed rules doing that lost R in backtests (D050), and Claude cannot be backtested honestly, so it is measured forward.
Decision:
- At each 15M close, Python checks every open paper trade with the docs/37 checks. When one fires, Haiku 5.5 answers hold, take profit now, or stop to breakeven, with one sentence. The design is in [38-AI-EXIT-MANAGER.md](38-AI-EXIT-MANAGER.md).
- **Shadow only.** The advice is stored with what Claude was shown, and scored when the trade closes by replaying it with the advice applied. Nothing about the trade changes.
- Python computes every number, including the breakeven stop. There is no action that adds risk. The shared $3 daily limit is checked before every call.
- Without an API key, checks are still recorded as "not asked".
Consequences:
- Migration 0013 adds `ai_exit_reviews`.
- Binance demo positions are not reviewed until Binance reports their fills back.
Revisit conditions: about 50 scored answers that were not "hold". Letting Claude act on any account needs a new decision.

### D050: Exit rules that take profit early, tested and not adopted
Date: 2026-11-11.
Status: Studied at the owner's request, as step 1 before an AI exit manager. Not adopted by its own pre-registered rule.
Context: The owner asked for an AI that can take the current profit when a trade looks unlikely to reach its target. Fixed rules can test that idea on 2020 to 2025, which Claude cannot, because the model may remember what prices did next.
Decision:
- The study in [37-EXIT-RULES.md](37-EXIT-RULES.md) added three rules to the daily trend, 1H pattern breakout and 4H gap strategies, on six coins, and compared each with the strategy's own exits on the same entries. The rules were a breakeven stop after +1R, an exit when a trade in profit stalls, and a stop trailing the setup swings. They were committed before any code or run, as `24a2f9f`.
- No rule passed. Eight of nine changes were negative. The best, the swing trail on the daily trend, was +0.009R a trade, with an interval that included zero. The stall exit saved 1.86R on each trade that would have lost, and gave up 1.78R on each trade that would have won.
- The strategies keep their own exits in every account.
Consequences:
- `backtesting/exits.py`, the study and its tests stay, so the run can be reproduced. The shared simulator gained an exit at the next candle's open (docs/10), which no live trade uses yet.
- An AI exit manager must beat the strategies' own exits in shadow mode before it acts. Its checks were measured at about 2 per open trade-day.
Revisit conditions: none for these values. A changed rule is a new trial.

### D047: The stack starts at login and restarts what stops
Date: 2026-11-10.
Status: Accepted by the owner, who wants Python running whenever the computer is on.
Context: The ingestor, quant worker, API and dashboard were started by hand with `nohup`, so a crash or a restart stopped trading until someone noticed. OrbStack, which runs PostgreSQL and Redis, did not start at login.
Decision:
- `scripts/autostart.sh install` (`make autostart`) runs each part as a launchd user agent that starts at login and restarts within 30 seconds if it stops. A fifth agent runs `caffeinate -i -s`, as `scripts/soak.sh` did, and OrbStack is set to start at login.
- The agents hold paths only. The services read `.env` themselves, so no secret is written into them.
Consequences:
- After a reboot, nothing runs until the owner logs in. Automatic login would close that gap, and is the owner's choice.
- Stopping a service by hand no longer works, because launchd starts it again. `scripts/autostart.sh` restarts, rebuilds or removes them.
- The ingestor soak started on 2026-11-06 ended at the switch, and a new run began under launchd.
Revisit conditions: the stack moves to Railway (D026).

### D048: The money plan on Binance demo futures, isolated, with stops and targets on Binance
Date: 2026-11-10.
Status: Accepted by the owner, who chose all four recommended options on 2026-11-10. **Amends D016** for demo trading only.
Context: The owner asked to trade Binance futures with isolated margin, 1% risk and profit targets, and for a Binance API gateway. Research is in [36-BINANCE-FUTURES-EXECUTION.md](36-BINANCE-FUTURES-EXECUTION.md). Risk per trade was already at most 1%, and every trade already had targets, but only in paper accounts.
Options considered:
- Where: Binance demo trading with test funds; demo now with a locked real-money path; or real money now with a cap.
- Strategies: the money plan's three at their evidence shares; the daily trend only; or all three at a flat 1%.
- Targets: three take-profits on Binance plus the daily +3% stop; one take-profit for the whole trade; or three take-profits plus closing everything at +3%.
- Leverage: the lowest that fits, at most 3x; a fixed 2x; or a fixed 5x.
Decision:
- A new `execution` module holds the only code that signs requests or sends orders. Its host is fixed to `https://demo-fapi.binance.com`, and a client pointed elsewhere is refused. Keys come from `.env` (`BINANCE_DEMO_API_KEY`, `BINANCE_DEMO_API_SECRET`) and are filtered from logs. Import contracts keep Claude's analyst, news, forecasts, the API and backtests from reaching it.
- A `Binance demo` account, in the new `exchange_demo` mode, runs the money plan at each 15M close, after the paper plan, with the same setups and evidence shares. Binance's account is the truth: equity, available margin and positions come from Binance, and the day's starting equity is stored once a day.
- The risk engine decides every trade. It now refuses margin the exchange cannot lend (`MARGIN_INSUFFICIENT`), and the trade is sized at leverage 1, then 2, then 3, until the margin fits. Leverage never changes what the stop loses.
- Each approved trade is sent as follows:
  - Isolated margin and the chosen leverage.
  - A market entry.
  - A mark-price stop that closes the whole position.
  - One reduce-only take-profit per target, split 50%, 30% and 20% of what filled.
  - If the stop cannot be placed, the position is closed at once.
- One-way mode, so one position per coin. A coin with a Binance position takes no new signal.
- **A 100 USDT budget**, at the owner's request on 2026-11-10: the demo account holds 5,000 test USDT, but the bot trades it as if it held only 100. The risk engine sees 100 USDT plus the bot's own profit and loss since its first recorded day, and never more free margin than that leaves. So 1% risk is at most 1 USDT a trade, and open positions stay within the budget at 1x. Binance's minimum sizes mean most BTC signals are refused at this size; SOL, BNB, XRP and DOGE trade from 5 USDT.
- Once a minute, orders left on a flat coin are cancelled, and a position without a stop gets its recorded stop back, or is closed if none is known.
- Every request and reply is stored in `exchange_orders`, which cannot be changed (migration 0011). `binance_demo keygen|check|status|flatten` makes a key, tests it, shows the account, and is the kill switch.
Consequences:
- A real-money account is still impossible: the database allows only `paper` and `exchange_demo` accounts, and `TradingMode` still has one member.
- Stops and targets sit on Binance, so demo positions stay protected while the Mac sleeps.
- Keys can be self-generated Ed25519, which the owner chose on 2026-11-10 after the demo site never showed a system-generated secret, or system-generated HMAC. `binance_demo keygen` writes the private key to `~/.config/trading-intel`, readable only by the owner, and prints the public key for Binance. This added the `cryptography` package.
- Version 1 limits:
  - Market entries only.
  - Order state is checked by REST once a minute, not by Binance's user data stream.
  - The dashboard shows the account from a snapshot the quant worker saves once a minute (migration 0012), so the API never holds the keys. Stops and targets that Binance triggers are not reported back yet; they show as the position disappearing.
Revisit conditions: forward demo results per strategy, the owner wants real money (a new decision replacing D016 and rule 13 in `CLAUDE.md`), or the dashboard view is built.
Later: D053 (2026-11-11) changed the account's limits to 2% a trade, up to 3× exposure, and a 20 USDT loss stop. D054 (2026-11-11) added limit entries.

### D049: The 4H gap and 15M CHoCH strategy joins the money plan at a half share
Date: 2026-11-10.
Status: Decided by the rule the owner's request was pre-registered under ([35-FVG-CHOCH-STRATEGY.md](35-FVG-CHOCH-STRATEGY.md)), run once on 2026-11-10 after the owner asked to run it.
Context: The owner asked for a strategy that finds a 4H fair value gap, then a 15M CHoCH, and enters at the 15M gap. The system had the detectors but no such strategy.
Decision:
- The study pooled six coins from 2020 to 2025: +0.020R a trade, 95% interval -0.18 to +0.23, 255 trades. That is above zero, so by its rule it joins the money plan's `Portfolio` account at a half share, beside the 15M rule baseline at each 15M close.
- Its entries are limit orders at the 15M gap, valid for two hours. The shared simulator now counts only the stop in the candle where a limit fills (docs/10).
- Binance demo trading sends market entries only, so it refuses these limit orders with that reason. Since D054 (2026-11-11) they are sent as limit entries.
Consequences:
- The evidence is weak: the result turned negative at 1.5× costs, and only longs made money. Forward paper results decide whether it stays.
- The study's code, tests and report stay so the run can be reproduced.
Revisit conditions: forward paper results per strategy, or Binance demo trading gains limit entries.

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
