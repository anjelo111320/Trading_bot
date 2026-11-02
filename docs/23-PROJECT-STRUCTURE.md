# Project Structure

Date: 2026-11-02
Status: Adopted under D011 and D018. This is the target layout. Folders are created in the phase that needs them, and empty placeholders are not added.

The backend module names come from [brief section 16](21-PROJECT-BRIEF.md). `core`, `domain`, `events`, `api` and `entrypoints` are added because shared contracts, transport, HTTP and process startup need a home that no brief module owns.

## Repository

```text
ai-trading-intelligence/
├── CLAUDE.md
├── README.md
├── Makefile                     bootstrap, check, up, down, reset, test
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── .python-version
├── .nvmrc
├── .github/
│   └── workflows/ci.yml         if GitHub is the chosen remote
├── .claude/
│   ├── agents/
│   └── skills/
├── backend/
├── frontend/
├── infra/
│   ├── docker-compose.yml
│   └── postgres/init/roles.sql
├── data/                        ignored by Git: local exports only
└── docs/
    ├── 00 to 23 numbered specifications
    ├── schema/schema-v0.sql
    ├── providers/binance-spot.md
    ├── benchmarks/
    └── reports/
```

## Backend

```text
backend/
├── pyproject.toml
├── uv.lock
├── alembic.ini
├── migrations/
├── src/trading_intel/
│   ├── core/                    settings, clock, logging, errors, ids
│   ├── domain/                  shared typed contracts
│   │   ├── instruments.py
│   │   ├── candles.py           ClosedCandle, FormingCandle, Timeframe
│   │   ├── market.py            TopOfBook, FundingRate, MarkPrice
│   │   ├── signals.py           actions, states, entry types
│   │   └── events.py            event envelope
│   ├── events/                  Redis Streams and Pub/Sub transport
│   ├── database/                tables, sessions, repositories
│   ├── data_providers/          external market-data adapters
│   │   ├── base.py              protocols and capabilities
│   │   ├── binance/             shared client, parsing, streams, spot and USD-M
│   │   └── synthetic/           labelled synthetic data for development
│   ├── market_data/             normalise, validate, ingest, backfill, gaps,
│   │                            reconcile, health, snapshots, instrument rules
│   ├── technical_analysis/      one module per indicator family
│   │   ├── trend.py
│   │   ├── momentum.py
│   │   ├── volatility.py
│   │   ├── volume.py
│   │   └── pipeline.py
│   ├── market_structure/        swings, BOS, CHoCH, levels, zones, liquidity,
│   │                            multi-timeframe alignment
│   ├── pattern_detection/       candles, FVG, order blocks, breakouts, divergences
│   ├── news_intelligence/       source adapters, dedupe, relevance, classification
│   ├── ai_analyst/              triggers, gates, budget, context, prompts, client,
│   │   │                        validation
│   │   └── prompts/             versioned prompt files
│   ├── risk_management/         sizing, costs, limits, rejection codes
│   │   └── calculators/         spot.py, linear_perpetual.py
│   ├── trade_signals/           level catalogue, rule baseline, quality score,
│   │                            lifecycle, invalidation, expiry
│   ├── backtesting/             replay, walk-forward, metrics, calibration, reports
│   ├── paper_trading/           accounts, positions, execution simulator
│   ├── notifications/           alert routing and channels
│   ├── monitoring/              provider health, freshness, cost and usage reports
│   ├── api/
│   │   ├── app.py
│   │   ├── auth.py
│   │   ├── errors.py
│   │   ├── routers/             one router per REST group
│   │   ├── schemas/             request and response models
│   │   └── websocket/           gateway and connection manager
│   └── entrypoints/             api, ingestor, backfill, quant_worker, news_worker,
│                                analyst_worker, signal_monitor, notifier
└── tests/
    ├── unit/                    mirrors src
    ├── property/
    ├── contract/                adapters against recorded frames
    ├── integration/             real PostgreSQL and Redis
    ├── failure/                 disconnects, dropped frames, restarts
    ├── safety/                  paper-only and live-trading guards
    ├── security/
    └── fixtures/                small, labelled by origin
```

The execution simulator lives in `paper_trading/` and is imported by `backtesting/`, so both use one implementation.

There is deliberately no `execution/` folder. See [02-SYSTEM-ARCHITECTURE.md](02-SYSTEM-ARCHITECTURE.md), Future Execution Isolation.

## Module Dependency Rules

Enforced by `import-linter` in CI.

| Module | May import | Must never import |
|---|---|---|
| `core` | Standard library, Pydantic | Any project module |
| `domain` | `core` | Everything else |
| `events`, `database` | `core`, `domain` | Business modules |
| `data_providers` | `core`, `domain` | `database`, analysis modules |
| `market_data` | `core`, `domain`, `data_providers`, `database`, `events` | Analysis modules |
| `technical_analysis` | `core`, `domain` | `database`, `ai_analyst`, `data_providers` |
| `market_structure` | `core`, `domain`, `technical_analysis` | `database`, `ai_analyst` |
| `pattern_detection` | `core`, `domain`, `technical_analysis`, `market_structure` | `database`, `ai_analyst` |
| `risk_management` | `core`, `domain` | **`ai_analyst`**, `data_providers`, `database` |
| `trade_signals` | `core`, `domain`, `risk_management`, quant modules, `database`, `events` | `ai_analyst` |
| `news_intelligence` | `core`, `domain`, `database`, `events` | `risk_management`, `trade_signals` |
| `ai_analyst` | `core`, `domain`, `database`, `events`, and read-only quant and news types | **`paper_trading`**, `risk_management` internals |
| `paper_trading` | `core`, `domain`, `risk_management`, `database`, `events` | `ai_analyst` |
| `backtesting` | `core`, `domain`, quant modules, `risk_management`, `trade_signals`, `paper_trading` | **`ai_analyst`**, `data_providers` |
| `notifications` | `core`, `domain`, `events`, `database` | Business decisions |
| `monitoring` | `core`, `domain`, `database`, `events` | Business decisions |
| `api` | Application services and schemas | Provider adapters directly |

An orchestrator in `entrypoints/analyst_worker.py` connects `ai_analyst` output to `risk_management`, so neither imports the other. The numerical modules are pure and have no database access, which keeps them testable and shared by live and backtest code.

Critical rules:

- `risk_management` cannot import `ai_analyst`.
- `backtesting` cannot import `ai_analyst`, keeping historical tests free of model leakage.
- Quant modules take data as arguments, so the same code runs live and in simulation.

## Frontend

```text
frontend/
├── package.json
├── pnpm-lock.yaml
├── next.config.ts
├── tsconfig.json
└── src/
    ├── app/
    │   ├── (auth)/login/
    │   ├── dashboard/           main dashboard
    │   ├── recommendations/
    │   ├── news/
    │   ├── performance/
    │   ├── backtests/
    │   ├── costs/               Claude and API cost monitoring
    │   ├── system/              provider health and data quality
    │   └── settings/
    ├── components/
    │   ├── chart/
    │   ├── recommendation/
    │   ├── news/
    │   ├── status/
    │   └── ui/
    ├── features/                data hooks by domain, with no calculations
    └── lib/
        ├── api/                 generated types and typed client
        └── ws/                  WebSocket client, resync and sequence handling
```

The frontend renders values from the backend. Indicators, risk and P/L are never calculated in React, as required by the brief.

## Creation Order

| Phase | Backend folders created |
|---|---|
| 0 | `core`, `domain`, `database`, `api`, `entrypoints` |
| 1A | `data_providers/binance`, `data_providers/synthetic`, `market_data`, `events`, `monitoring` |
| 1B | USD-M support in `data_providers/binance` |
| 2 | `technical_analysis`, `market_structure`, `pattern_detection` |
| 3 | `risk_management`, `trade_signals`, `notifications` |
| 4 | `backtesting` |
| 5 | `paper_trading`, with the execution simulator first built for Phase 4 |
| 6 | `news_intelligence` |
| 7 | `ai_analyst` |

The order follows the accepted roadmap.
