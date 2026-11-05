# Technology Stack

## Backend
- Python.
- FastAPI.
- Pydantic.
- SQLAlchemy.
- Alembic.
- Pandas.
- NumPy.
- TA-Lib or validated indicator implementations.
- pytest.

## Frontend
- Next.js.
- React.
- TypeScript.
- Tailwind CSS.
- TradingView Lightweight Charts or another licensed chart library.
- TanStack Query.

## Infrastructure
- PostgreSQL.
- TimescaleDB evaluation.
- Redis.
- Docker.
- Background workers.
- Structured logging.

## AI
- Anthropic Claude API.
- Structured output validation.
- Prompt versioning.
- Token and cost tracking.

## Selection Rules
Verify current documentation, maintenance status, pricing and licensing.
Do not add dependencies without a reason.
Pin dependencies and use lockfiles.
Document major technology decisions.

## Technology Selection

Status: Proposed, 2026-11-02. Versions were read from PyPI and npm on that date and are pinned in T0.4 and T0.10. Licensing evidence is in [18-ARCHITECTURE-REVIEW.md](18-ARCHITECTURE-REVIEW.md), section 6.

Each package is added in the phase that first uses it, not all at once.

### Backend

| Need | Selected | Version | Alternatives | Reason | Phase |
|---|---|---|---|---|---|
| Language | Python | 3.14 | 3.13 | Supported to 2030-10. Wheels confirmed for the numeric stack | 0 |
| Package manager | uv | 0.13.6 | pip, Poetry | Fast, lockfile, manages the interpreter | 0 |
| Web framework | FastAPI | 0.162.0 | Litestar | Required by the brief | 0 |
| Validation | Pydantic | 2.14.2 | None | Required; also drives structured Claude output | 0 |
| Settings | pydantic-settings | 2.16.2 | None | Typed environment configuration | 0 |
| ORM and migrations | SQLAlchemy, Alembic | 2.1.6, 1.20.1 | Raw SQL | Required; typed repositories | 0 |
| PostgreSQL driver | asyncpg | 0.32.0 | psycopg 3.3 | Async, and `COPY` for bulk backfill | 0 |
| HTTP client | httpx | 0.28.1 | aiohttp | Async, simple to mock | 1 |
| WebSocket client | websockets | 17.4 | aiohttp | Automatic pong handling, async | 1 |
| Redis client | redis-py | 8.1.0 | None | Streams and Pub/Sub | 1 |
| Logging | structlog | 26.1.0 | stdlib logging | JSON logs and secret filtering | 0 |
| Numeric | NumPy, pandas | 2.5.4, 3.1.0 | Polars | Required by the docs. Consider Polars only if profiling demands it | 2 |
| Indicators | TA-Lib | 0.8.3 | pandas-ta, own code | BSD licence, wheels now bundle the C library. Own implementations are cross-checked against it | 2 |
| Claude SDK | anthropic | 2.3.0 | Raw HTTP | Official SDK is the only permitted path | News or analyst phase |
| Provider access | Direct adapters | Not applicable | ccxt | Fixtures need raw frames, and each adapter is small | 1 |
| Forecasting model | Kronos-small, as a separate process with PyTorch in `vendor/Kronos/.venv` | Commit `67b630e`, weights `901c26c` | None | Owner request. Kept apart because the backend does not install PyTorch | Model forecasts, D040 |

`uvloop` is excluded for now because no macOS arm64 wheel exists for Python 3.14.

### Frontend

| Need | Selected | Version | Alternatives | Reason | Phase |
|---|---|---|---|---|---|
| Framework | Next.js, React | 16.4.3, 19.3.1 | None | Required by the brief | 0 |
| Language | TypeScript | 7.0.2 | 5.x | Confirm Next.js compatibility in T0.10 | 0 |
| Styling | Tailwind CSS | 4.3.3 | None | Required by the brief | 0 |
| Server state | TanStack Query | 5.105.1 | SWR | Already specified | 0 |
| Charts | Lightweight Charts | 5.2.1 | ECharts | Apache 2.0, built for financial charts. Retain licence and NOTICE | 1 |
| API types | openapi-typescript | 7.13.0 | Hand-written types | Generated from OpenAPI, so contracts cannot drift | 0 |
| Package manager | pnpm | 12.16.1 | npm | Strict dependencies, lockfile | 0 |

TradingView's hosted widgets, if ever used, stay a separate visual option and never feed analysis.

### Infrastructure

| Need | Selected | Version | Alternatives | Reason | Phase |
|---|---|---|---|---|---|
| Database | PostgreSQL | 18.6 | None | Required. Native `uuidv7()`, supported to 2030-11 | 0 |
| Time-series extension | None for now | TimescaleDB 2.31 if adopted | Timescale | Speed is not the issue: 1,000 candles read in about 1 ms. Compression could matter on this small disk, so T1.17 measures it | 1 |
| Cache and events | Redis | 8 | Valkey | Required. Unmodified internal use is fine under its licence options. Revisit if ever offered as a hosted service | 0 |
| Background work | Plain worker processes on Redis Streams | Not applicable | Dramatiq 2.2, Taskiq 0.13 | No extra dependency until a need appears. Celery is heavier than this needs | 2 |
| Containers | Docker Compose on OrbStack | Not applicable | Kubernetes, Docker Desktop | One computer. OrbStack is already installed and suits 8 GB of memory | 0 |
| Task runner | Makefile | Not applicable | just | Already available | 0 |
| Metrics | Health endpoints first | Not applicable | Prometheus | Add a metrics backend when there is something to operate | Later |

### Quality and Security

| Need | Selected | Version | Phase |
|---|---|---|---|
| Testing | pytest, pytest-asyncio | 9.2.0, 1.4.1 | 0 |
| Property tests | Hypothesis | 6.170 | 1 |
| HTTP mocking | respx | 0.23.1 | 1 |
| Real services in tests | testcontainers | 4.15.0 | 1 |
| Lint, format | ruff | 0.17.3 | 0 |
| Types | mypy, strict | 2.4.1 | 0 |
| Import rules | import-linter | 2.15 | 0 |
| Secret scan | gitleaks | Pin at T0.11 | 0 |
| Dependency audit | pip-audit, pnpm audit | Pin at T0.11 | 0 |

### External Services

| Purpose | Selected | Notes |
|---|---|---|
| Market data | Binance public data | Perpetuals for simulated trades, spot for long history. Plan in [20-API-INTEGRATION-PLAN.md](20-API-INTEGRATION-PLAN.md) |
| AI reasoning | `claude-opus-5-5` | Brief section 7. Cost design in [24-AI-COST-STRATEGY.md](24-AI-COST-STRATEGY.md) |
| AI classification | `claude-haiku-5-5` | Brief section 18 asks for a cheaper model for simple work |
| News, initial | Official sources | Paid vendor selected in the news phase |
| Notifications | In-app first, Telegram Bot API proposed | Bots can message their users at no cost; about one message per second per chat. Decide in the risk phase |
