# Database Design

## Core Tables
- users
- instruments
- providers
- market_candles
- market_snapshots
- technical_features
- detected_patterns
- news_articles
- economic_events
- ai_analyses
- trade_recommendations
- recommendation_revisions
- risk_assessments
- paper_accounts
- paper_positions
- paper_executions
- trade_outcomes
- backtest_runs
- backtest_trades
- strategy_configurations
- system_events
- api_usage

## Rules
Use UUID identifiers where appropriate.
Use UTC timestamps.
Use migrations.
Add appropriate indexes.
Use decimal/numeric types for financial values.
Avoid floating-point money storage.
Preserve recommendation history.
Track data provenance.
Apply access control and retention policies.

Evaluate TimescaleDB for candle storage.
Do not add it without measuring its benefit.

## Schema v0

Status: Proposed, 2026-11-02. The full definition is in [schema/schema-v0.sql](schema/schema-v0.sql). It is a design baseline. Alembic migrations add tables in the phase that needs them, and become the source of truth once they exist.

Validation run on 2026-11-02: the file loaded without error, creating 47 tables, 99 indexes and 24 immutability triggers. 22 forbidden operations were rejected by the database and 10 valid ones succeeded. That run used PostgreSQL 14.18 with a temporary `uuidv7()` substitute, because Docker was not running. Repeat it on PostgreSQL 18 in T0.8.

### Requirement Mapping

Names follow the brief, or this document where they agree.

| Brief item | Tables |
|---|---|
| Users | `users` |
| Trading accounts | `trading_accounts`, `risk_profiles` |
| Instruments | `instruments`, `provider_instruments`, `instrument_rule_snapshots` |
| Market candles | `market_candles`, `market_candle_revisions`, `market_gaps` |
| Market snapshots | `market_snapshots`, `funding_rates`, `liquidation_samples` |
| Technical indicators | `technical_indicators` |
| Detected patterns | `detected_patterns` |
| News articles | `news_sources`, `news_articles`, `news_article_instruments`, `news_classifications` |
| Economic events | `economic_events` |
| AI analyses | `analysis_triggers`, `analysis_input_snapshots`, `prompt_versions`, `ai_analyses` |
| Model forecasts (D040) | `model_forecasts`, `model_forecast_outcomes` |
| Trade recommendations | `trade_recommendations`, `recommendation_revisions`, `signal_events`, `signal_current_state` |
| Trade targets | `trade_targets` |
| Risk calculations | `risk_assessments` |
| Paper trades | `paper_positions`, `paper_executions` |
| Trade outcomes | `trade_outcomes` |
| Backtest runs | `backtest_runs`, `backtest_trades`, `backtest_equity_points`, `dataset_versions`, `calibration_models` |
| Strategy configurations | `strategy_configurations`, `timeframe_profiles` |
| System events | `system_events`, `audit_log`, `ingest_runs` |
| API usage and cost | `api_usage`, `ai_model_prices` |
| Supporting tables | `providers`, `fee_schedules`, `alerts` |

The earlier names `technical_features` and `paper_accounts` are replaced by `technical_indicators` and `trading_accounts`, matching the brief.

### Safety Enforced by the Database

These hold even if application code has a bug. Each one was tested.

| Rule | Mechanism |
|---|---|
| No live account can exist | CHECK on `trading_accounts.mode` |
| Candles are consistent | CHECK on OHLC, positive low, non-negative volume |
| One row per candle | Composite primary key |
| A trade has entry, stop and a dedupe key | `rec_trade_fields_present` |
| BUY stop is below entry, SELL stop above | `rec_buy_stop_below_entry`, `rec_sell_stop_above_entry` |
| NO_TRADE and WAIT carry no levels | `rec_no_levels_without_trade` |
| A trade has evidence | `rec_evidence_required` |
| A recommendation has invalidation conditions | `rec_invalidation_required`, exempting NO_TRADE |
| Probability needs a calibration model | `rec_probability_consistent` |
| Recommendations cannot be altered | Triggers reject UPDATE, DELETE and TRUNCATE |
| Risk rejections have reasons | `risk_rejection_has_reason` |
| No duplicate active signal | Partial unique index on `signal_current_state` |
| Win rate excludes unresolved results | `counts_for_win_rate` is a generated column |
| A simulated fill cannot repeat | Unique `idempotency_key` on `paper_executions` |
| Fills are always simulated | CHECK on `paper_executions.simulated` |
| The final holdout runs once per strategy version | Partial unique index on `backtest_runs` |
| Roles are least privilege | The app role cannot write candles; read-only roles cannot read `users` |

Immutable tables: `risk_profiles`, `market_candle_revisions`, `analysis_input_snapshots`, `ai_analyses`, `trade_recommendations`, `trade_targets`, `recommendation_revisions`, `risk_assessments`, `signal_events`, `paper_executions`, `trade_outcomes`, `audit_log`, `model_forecasts`, `model_forecast_outcomes`.

A forecast is stored before its outcome is known, and neither row can change afterwards, so a model's track record cannot be improved after the fact.

The same holds for the signal score (D046). From migration 0010, `trade_recommendations.signal_score` stores its four conditions at the signal's close, before the trade's outcome exists. It is information only and never read by the risk engine. Signals recorded before 2026-11-10 have none.

### Key Design Choices

- Candles use a natural key, not UUIDs. Including `open_time` keeps a later hypertable conversion possible.
- `market_candles` holds closed candles only. Forming candles stay in Redis, so they cannot leak into analysis.
- Prices use `numeric(38,18)`. PostgreSQL does not store trailing zeros, so wide scale costs little. A test on 1 million synthetic rows measured 245.5 bytes per row including the index.
- `uuidv7()` gives time-ordered keys, which keeps inserts local in the index.
- `market_snapshots` is per minute. Raw top-of-book frames arrive at hundreds per second and are not stored.
- `liquidation_samples` is named as a sample because the Binance stream sends at most one order per symbol per second.
- `technical_indicators` uses JSONB by feature version. Indicators are derivable, so old rows can be pruned.
- Analysis inputs are stored in full, so any recommendation can be audited against exactly what the model saw.
- `signal_current_state` is a mutable projection. The immutable `signal_events` table stays the record.

### Data Volume

Row counts come from verified start dates, seven timeframes, and 1,903 candles per day per series.

| Series | First candle | Rows to 2026-11-02 |
|---|---|---|
| BTCUSDT spot | 2017-08-17 | 6,401,692 |
| ETHUSDT spot | 2017-08-17 | 6,401,692 |
| BTCUSDT perpetual | 2019-09-08 | 4,970,636 |
| ETHUSDT perpetual | 2019-11-27 | 4,818,396 |
| Total | | 22,592,416 |

Growth is about 2.8 million rows a year across the four series. At the measured 245.5 bytes per row, the full set is about 5.5 GB. Gaps from exchange outages will reduce the counts slightly. Real data may differ a little from the synthetic rows measured.

### Local Storage Profile

Status: Proposed under D024.

The owner's computer has limited disk, and candles can be downloaded again at any time. So storage favours what cannot be recovered.

| Data | Stored locally | Rows | Size |
|---|---|---|---|
| Perpetual candles, all seven timeframes from listing | Yes | 9,789,032 | 2.40 GB |
| Spot history, 15M and above from 2017 | Yes | 1,177,400 | 0.29 GB |
| Spot history, 1M and 5M | No. Download later if a strategy needs it | Not stored | Saves 2.85 GB |
| Spot live candles, all timeframes from go-live | Yes | Growing | See below |

Starting size is about 2.7 GB. Growth is about 0.7 GB a year for candles and about 0.4 GB a year for per-minute snapshots across four series, assuming about 200 bytes per snapshot row.

Disk budget for the first year, with the tooling, backup and overhead figures being estimates:

| Item | Size |
|---|---|
| Database at start | 2.7 GB |
| One year of growth | 1.1 GB |
| Temporary load overhead | 2 GB |
| Docker runtime and images | 2 GB |
| Python and Node dependencies | 2.5 GB |
| One compressed backup | 1 GB |
| Total | About 11 GB |
| macOS working room | 10 GB |
| **Free disk needed** | **At least 20 GB** |

### Indexing

- Time-series reads use the primary key: instrument, timeframe, then time.
- Recent-activity views use descending time indexes.
- Partial indexes cover only live work, such as open gaps, open positions and active signals.
- Add further indexes only for a measured slow query.

### Retention

| Data | Retention | Recoverable | Backup priority |
|---|---|---|---|
| `market_candles` | Indefinite | Yes, while the provider allows | Low |
| `market_snapshots`, `funding_rates`, `liquidation_samples`, `instrument_rule_snapshots` | Indefinite | **No**, except funding and one month of open interest | High |
| `technical_indicators` | 90 days, plus rows referenced by a decision | Yes | Low |
| `detected_patterns` | Indefinite | Yes, if rule versions are kept | Medium |
| `news_articles` | Per provider licence, through `retain_until` | **No** | High |
| `analysis_input_snapshots`, `ai_analyses` | Indefinite, subject to provider terms | **No** | High |
| `model_forecasts`, `model_forecast_outcomes` | Indefinite. About 28 KB per forecast, measured on 2026-11-05 | Forecasts from a pinned model can be rerun. Their time order cannot | Medium |
| Recommendations, risk, signals, paper, outcomes | Indefinite | **No** | Highest |
| `backtest_*` | Keep summaries indefinitely; trades and equity points 2 years | Yes, from dataset version and code | Low |
| `system_events` | 90 days | No | Low |
| `api_usage`, `audit_log` | Indefinite | No | Medium |

Retention jobs run daily and log what they delete. A provider with `delete_on_termination` set has its data removed when the subscription ends.

### TimescaleDB

Not adopted for now. Nearly all reads are a range on one instrument and timeframe, which a B-tree serves directly: the latest 1,000 of 1 million rows read in about 1 ms in testing. T1.17 measures both options on the real dataset, including disk use, because compression could matter on a small disk. Revisit if raw trades or full order-book data are stored.

### Backup and Recovery

Daily `pg_dump`, compressed and encrypted, stored off this computer on an external drive or private cloud storage. Candle tables can be left out, since they can be downloaded again, which keeps backups small. Recovery point 24 hours, recovery time 4 hours. Restore is tested in the hardening phase, and earlier if real paper-trading history has accumulated.
