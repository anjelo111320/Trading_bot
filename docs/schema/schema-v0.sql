-- AI Trading Intelligence: schema v0
--
-- Design baseline for review. Target: PostgreSQL 18.
-- Tables are introduced by Alembic migrations in the phase that needs them.
-- Once migrations exist they are the source of truth, not this file.
--
-- Conventions:
--   Timestamps are timestamptz and hold UTC.
--   Prices, quantities and money use decimal_t, never float.
--   Event and record keys are uuidv7(). Time series use natural composite keys.
--   Tables listed in the immutability block at the end reject UPDATE, DELETE and TRUNCATE.

BEGIN;

-- ---------------------------------------------------------------------------
-- Types
-- ---------------------------------------------------------------------------

CREATE DOMAIN decimal_t AS numeric(38, 18);

CREATE TYPE instrument_type_t AS ENUM
  ('spot', 'linear_perpetual', 'inverse_perpetual', 'forex', 'equity', 'cfd');
CREATE TYPE timeframe_t AS ENUM ('1m', '5m', '15m', '30m', '1h', '4h', '1d');
CREATE TYPE data_origin_t AS ENUM ('live', 'backfill', 'synthetic');
CREATE TYPE gap_state_t AS ENUM ('detected', 'repairing', 'repaired', 'provider_missing');
CREATE TYPE action_t AS ENUM ('BUY', 'SELL', 'WAIT', 'NO_TRADE');
CREATE TYPE entry_type_t AS ENUM ('MARKET', 'LIMIT', 'STOP');
CREATE TYPE side_t AS ENUM ('LONG', 'SHORT');
CREATE TYPE signal_state_t AS ENUM (
  'CANDIDATE', 'VALIDATED', 'ACTIVE', 'ENTRY_TRIGGERED',
  'TP1_HIT', 'TP2_HIT', 'TP3_HIT', 'STOPPED', 'INVALIDATED', 'EXPIRED', 'REJECTED'
);
CREATE TYPE outcome_t AS ENUM (
  'WIN', 'LOSS', 'BREAKEVEN', 'NOT_FILLED', 'EXPIRED', 'INVALIDATED_BEFORE_ENTRY', 'CANCELLED'
);
CREATE TYPE backtest_split_t AS ENUM ('train', 'validate', 'test', 'walk_forward', 'holdout');

-- ---------------------------------------------------------------------------
-- Identity and accounts
-- ---------------------------------------------------------------------------

CREATE TABLE users (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  email          text NOT NULL,
  password_hash  text NOT NULL,
  role           text NOT NULL DEFAULT 'owner' CHECK (role IN ('owner', 'viewer')),
  is_active      boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_lower_uq ON users (lower(email));

-- The CHECK on mode makes a non-paper account unrepresentable in the initial release.
CREATE TABLE trading_accounts (
  id                uuid PRIMARY KEY DEFAULT uuidv7(),
  user_id           uuid NOT NULL REFERENCES users,
  name              text NOT NULL,
  mode              text NOT NULL DEFAULT 'paper' CHECK (mode = 'paper'),
  base_currency     text NOT NULL,
  starting_balance  decimal_t NOT NULL CHECK (starting_balance > 0),
  is_active         boolean NOT NULL DEFAULT true,
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, name)
);

-- Append-only. Changing a limit inserts a new version.
CREATE TABLE risk_profiles (
  id                          uuid PRIMARY KEY DEFAULT uuidv7(),
  account_id                  uuid NOT NULL REFERENCES trading_accounts,
  version                     integer NOT NULL CHECK (version > 0),
  max_risk_fraction           decimal_t NOT NULL CHECK (max_risk_fraction > 0 AND max_risk_fraction < 1),
  min_reward_risk             decimal_t NOT NULL CHECK (min_reward_risk > 0),
  countertrend_extra_rr       decimal_t NOT NULL DEFAULT 0 CHECK (countertrend_extra_rr >= 0),
  max_daily_loss_fraction     decimal_t NOT NULL CHECK (max_daily_loss_fraction > 0 AND max_daily_loss_fraction < 1),
  max_open_positions          integer NOT NULL CHECK (max_open_positions > 0),
  max_total_exposure_fraction decimal_t NOT NULL CHECK (max_total_exposure_fraction > 0),
  max_leverage                decimal_t NOT NULL CHECK (max_leverage >= 1),
  max_spread_bps              decimal_t NOT NULL CHECK (max_spread_bps > 0),
  max_data_age_seconds        integer NOT NULL CHECK (max_data_age_seconds > 0),
  settings                    jsonb NOT NULL DEFAULT '{}',
  created_by                  uuid REFERENCES users,
  created_at                  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (account_id, version)
);

-- The user can reassign timeframe roles. roles example:
-- {"direction":"1d","structure":"4h","intermediate":"1h","setup":"15m","confirmation":"5m","refinement":"1m"}
CREATE TABLE timeframe_profiles (
  id          uuid PRIMARY KEY DEFAULT uuidv7(),
  user_id     uuid NOT NULL REFERENCES users,
  name        text NOT NULL,
  roles       jsonb NOT NULL,
  is_default  boolean NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, name)
);
CREATE UNIQUE INDEX timeframe_profiles_one_default_uq ON timeframe_profiles (user_id) WHERE is_default;

-- ---------------------------------------------------------------------------
-- Providers and instruments
-- ---------------------------------------------------------------------------

CREATE TABLE providers (
  id                     smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                   text NOT NULL UNIQUE,
  name                   text NOT NULL,
  kind                   text NOT NULL CHECK (kind IN ('market_data', 'news', 'calendar', 'ai', 'notification', 'synthetic')),
  terms_url              text,
  terms_version          text,
  terms_reviewed_at      date,
  delete_on_termination  boolean NOT NULL DEFAULT false,
  is_active              boolean NOT NULL DEFAULT true,
  notes                  text
);

CREATE TABLE instruments (
  id                   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  canonical_symbol     text NOT NULL,
  instrument_type      instrument_type_t NOT NULL,
  base_asset           text NOT NULL,
  quote_asset          text NOT NULL,
  settle_asset         text NOT NULL,
  contract_multiplier  decimal_t NOT NULL DEFAULT 1 CHECK (contract_multiplier > 0),
  is_active            boolean NOT NULL DEFAULT true,
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (canonical_symbol, instrument_type)
);

-- Which provider supports which instrument, and which data. No provider is assumed
-- to support everything. capabilities example:
-- {"candles":true,"bid_ask":true,"depth":true,"funding":false,"open_interest":false,"liquidations":false}
CREATE TABLE provider_instruments (
  provider_id      smallint NOT NULL REFERENCES providers,
  instrument_id    integer NOT NULL REFERENCES instruments,
  provider_symbol  text NOT NULL,
  capabilities     jsonb NOT NULL DEFAULT '{}',
  is_active        boolean NOT NULL DEFAULT true,
  PRIMARY KEY (provider_id, instrument_id),
  UNIQUE (provider_id, provider_symbol)
);

-- Rules cannot be fetched for past dates, so they are recorded forward from day one.
CREATE TABLE instrument_rule_snapshots (
  id                           uuid PRIMARY KEY DEFAULT uuidv7(),
  provider_id                  smallint NOT NULL REFERENCES providers,
  instrument_id                integer NOT NULL REFERENCES instruments,
  valid_from                   timestamptz NOT NULL,
  valid_to                     timestamptz,
  status                       text NOT NULL,
  tick_size                    decimal_t NOT NULL CHECK (tick_size > 0),
  lot_step                     decimal_t NOT NULL CHECK (lot_step > 0),
  min_qty                      decimal_t NOT NULL CHECK (min_qty >= 0),
  max_qty                      decimal_t NOT NULL CHECK (max_qty > 0),
  market_max_qty               decimal_t,
  min_notional                 decimal_t NOT NULL CHECK (min_notional >= 0),
  max_notional                 decimal_t,
  initial_margin_fraction      decimal_t,
  maintenance_margin_fraction  decimal_t,
  raw                          jsonb NOT NULL,
  CHECK (valid_to IS NULL OR valid_to > valid_from),
  UNIQUE (provider_id, instrument_id, valid_from)
);
CREATE UNIQUE INDEX instrument_rule_snapshots_current_uq
  ON instrument_rule_snapshots (provider_id, instrument_id) WHERE valid_to IS NULL;

CREATE TABLE fee_schedules (
  id               uuid PRIMARY KEY DEFAULT uuidv7(),
  provider_id      smallint NOT NULL REFERENCES providers,
  instrument_type  instrument_type_t NOT NULL,
  maker_fee        decimal_t NOT NULL CHECK (maker_fee >= -1 AND maker_fee < 1),
  taker_fee        decimal_t NOT NULL CHECK (taker_fee >= 0 AND taker_fee < 1),
  effective_from   timestamptz NOT NULL,
  source_url       text NOT NULL,
  UNIQUE (provider_id, instrument_type, effective_from)
);

-- ---------------------------------------------------------------------------
-- Market data
-- ---------------------------------------------------------------------------

CREATE TABLE ingest_runs (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  provider_id  smallint NOT NULL REFERENCES providers,
  kind         text NOT NULL CHECK (kind IN ('backfill', 'live', 'repair', 'reconcile')),
  git_sha      text NOT NULL,
  started_at   timestamptz NOT NULL DEFAULT now(),
  finished_at  timestamptz,
  status       text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
  stats        jsonb NOT NULL DEFAULT '{}'
);

-- Closed candles only. Forming candles live in Redis and never reach this table.
CREATE TABLE market_candles (
  provider_id             smallint NOT NULL REFERENCES providers,
  instrument_id           integer NOT NULL REFERENCES instruments,
  timeframe               timeframe_t NOT NULL,
  open_time               timestamptz NOT NULL,
  close_time              timestamptz NOT NULL,
  open                    decimal_t NOT NULL,
  high                    decimal_t NOT NULL,
  low                     decimal_t NOT NULL,
  close                   decimal_t NOT NULL,
  volume                  decimal_t NOT NULL,
  quote_volume            decimal_t NOT NULL,
  taker_buy_base_volume   decimal_t,
  taker_buy_quote_volume  decimal_t,
  trade_count             bigint NOT NULL CHECK (trade_count >= 0),
  first_trade_id          bigint,
  last_trade_id           bigint,
  provider_open_time_raw  bigint NOT NULL,
  data_origin             data_origin_t NOT NULL,
  received_at             timestamptz NOT NULL,
  ingest_run_id           uuid REFERENCES ingest_runs,
  PRIMARY KEY (provider_id, instrument_id, timeframe, open_time),
  CONSTRAINT market_candles_ohlc_high CHECK (high >= open AND high >= close AND high >= low),
  CONSTRAINT market_candles_ohlc_low CHECK (low <= open AND low <= close AND low > 0),
  CONSTRAINT market_candles_volume CHECK (volume >= 0 AND quote_volume >= 0),
  CONSTRAINT market_candles_times CHECK (close_time > open_time)
);

-- A provider correction never overwrites silently. It is recorded here.
CREATE TABLE market_candle_revisions (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  provider_id    smallint NOT NULL REFERENCES providers,
  instrument_id  integer NOT NULL REFERENCES instruments,
  timeframe      timeframe_t NOT NULL,
  open_time      timestamptz NOT NULL,
  previous       jsonb NOT NULL,
  replacement    jsonb NOT NULL,
  reason         text NOT NULL,
  detected_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX market_candle_revisions_lookup_idx
  ON market_candle_revisions (provider_id, instrument_id, timeframe, open_time);

CREATE TABLE market_gaps (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  provider_id    smallint NOT NULL REFERENCES providers,
  instrument_id  integer NOT NULL REFERENCES instruments,
  timeframe      timeframe_t NOT NULL,
  gap_start      timestamptz NOT NULL,
  gap_end        timestamptz NOT NULL,
  state          gap_state_t NOT NULL DEFAULT 'detected',
  cause          text,
  detected_at    timestamptz NOT NULL DEFAULT now(),
  resolved_at    timestamptz,
  CHECK (gap_end > gap_start),
  UNIQUE (provider_id, instrument_id, timeframe, gap_start)
);
CREATE INDEX market_gaps_open_idx ON market_gaps (state) WHERE state IN ('detected', 'repairing');

-- One row per instrument per minute. Raw top-of-book frames are not stored.
-- Spread, open interest and order-book history cannot be fetched later, so a missing
-- minute stays missing.
CREATE TABLE market_snapshots (
  provider_id          smallint NOT NULL REFERENCES providers,
  instrument_id        integer NOT NULL REFERENCES instruments,
  minute_start         timestamptz NOT NULL,
  best_bid             decimal_t,
  best_ask             decimal_t,
  spread_min           decimal_t,
  spread_mean          decimal_t,
  spread_max           decimal_t,
  spread_last          decimal_t,
  sample_count         integer NOT NULL CHECK (sample_count >= 0),
  crossed_book_count   integer NOT NULL DEFAULT 0 CHECK (crossed_book_count >= 0),
  mark_price           decimal_t,
  index_price          decimal_t,
  open_interest        decimal_t,
  depth_imbalance      decimal_t,
  data_origin          data_origin_t NOT NULL,
  received_at          timestamptz NOT NULL,
  PRIMARY KEY (provider_id, instrument_id, minute_start)
);

CREATE TABLE funding_rates (
  provider_id    smallint NOT NULL REFERENCES providers,
  instrument_id  integer NOT NULL REFERENCES instruments,
  funding_time   timestamptz NOT NULL,
  funding_rate   decimal_t NOT NULL,
  mark_price     decimal_t,
  data_origin    data_origin_t NOT NULL,
  received_at    timestamptz NOT NULL,
  PRIMARY KEY (provider_id, instrument_id, funding_time)
);

-- The Binance stream sends at most one order per symbol per second, so this table is a
-- sample of liquidations, not a complete record. Reports must say so.
CREATE TABLE liquidation_samples (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  provider_id    smallint NOT NULL REFERENCES providers,
  instrument_id  integer NOT NULL REFERENCES instruments,
  event_time     timestamptz NOT NULL,
  side           text NOT NULL CHECK (side IN ('BUY', 'SELL')),
  price          decimal_t NOT NULL CHECK (price > 0),
  quantity       decimal_t NOT NULL CHECK (quantity > 0),
  received_at    timestamptz NOT NULL
);
CREATE INDEX liquidation_samples_lookup_idx ON liquidation_samples (provider_id, instrument_id, event_time DESC);

-- ---------------------------------------------------------------------------
-- Strategy and quantitative analysis
-- ---------------------------------------------------------------------------

CREATE TABLE strategy_configurations (
  id            uuid PRIMARY KEY DEFAULT uuidv7(),
  name          text NOT NULL,
  version       integer NOT NULL CHECK (version > 0),
  kind          text NOT NULL CHECK (kind IN ('rule_baseline', 'claude_assisted')),
  parameters    jsonb NOT NULL,
  content_hash  text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name, version)
);

-- Stored for recent history and for candles referenced by a decision. Indicators remain
-- derivable from candles, so older rows may be pruned.
CREATE TABLE technical_indicators (
  provider_id          smallint NOT NULL REFERENCES providers,
  instrument_id        integer NOT NULL REFERENCES instruments,
  timeframe            timeframe_t NOT NULL,
  close_time           timestamptz NOT NULL,
  feature_set_version  text NOT NULL,
  values               jsonb NOT NULL,
  computed_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (provider_id, instrument_id, timeframe, close_time, feature_set_version)
);

CREATE TABLE detected_patterns (
  id                 uuid PRIMARY KEY DEFAULT uuidv7(),
  provider_id        smallint NOT NULL REFERENCES providers,
  instrument_id      integer NOT NULL REFERENCES instruments,
  timeframe          timeframe_t NOT NULL,
  pattern_type       text NOT NULL,
  direction          text CHECK (direction IN ('bullish', 'bearish', 'neutral')),
  price_level        decimal_t,
  zone_low           decimal_t,
  zone_high          decimal_t,
  formed_at          timestamptz NOT NULL,
  detected_at        timestamptz NOT NULL,
  validation_status  text NOT NULL CHECK (validation_status IN ('candidate', 'confirmed', 'invalidated', 'expired')),
  invalidated_at     timestamptz,
  strength_score     numeric(5, 2) CHECK (strength_score BETWEEN 0 AND 100),
  rule_version       text NOT NULL,
  evidence           jsonb NOT NULL,
  CHECK (detected_at >= formed_at),
  CHECK (zone_low IS NULL OR zone_high IS NULL OR zone_high >= zone_low)
);
CREATE INDEX detected_patterns_recent_idx
  ON detected_patterns (instrument_id, timeframe, detected_at DESC);
CREATE INDEX detected_patterns_type_idx ON detected_patterns (pattern_type, detected_at DESC);

-- ---------------------------------------------------------------------------
-- News and economic events
-- ---------------------------------------------------------------------------

CREATE TABLE news_sources (
  id                integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  provider_id       smallint NOT NULL REFERENCES providers,
  name              text NOT NULL,
  domain            text,
  credibility_tier  text NOT NULL CHECK (credibility_tier IN ('official', 'primary_media', 'aggregator', 'social', 'unknown')),
  UNIQUE (provider_id, name)
);

-- Published time, event time and first-seen time stay separate. Backtests use the later
-- of published_at and first_seen_at.
CREATE TABLE news_articles (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  provider_id    smallint NOT NULL REFERENCES providers,
  source_id      integer REFERENCES news_sources,
  external_id    text,
  headline       text NOT NULL,
  url            text NOT NULL,
  snippet        text,
  published_at   timestamptz NOT NULL,
  event_time     timestamptz,
  retrieved_at   timestamptz NOT NULL,
  first_seen_at  timestamptz NOT NULL,
  content_hash   text NOT NULL,
  cluster_id     uuid,
  retain_until   timestamptz,
  raw            jsonb,
  UNIQUE (provider_id, url)
);
CREATE INDEX news_articles_published_idx ON news_articles (published_at DESC);
CREATE INDEX news_articles_cluster_idx ON news_articles (cluster_id);
CREATE INDEX news_articles_hash_idx ON news_articles (content_hash);

CREATE TABLE news_article_instruments (
  article_id       uuid NOT NULL REFERENCES news_articles ON DELETE CASCADE,
  instrument_id    integer NOT NULL REFERENCES instruments,
  relevance_score  numeric(4, 3) NOT NULL CHECK (relevance_score BETWEEN 0 AND 1),
  PRIMARY KEY (article_id, instrument_id)
);

CREATE TABLE economic_events (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  provider_id    smallint NOT NULL REFERENCES providers,
  title          text NOT NULL,
  category       text NOT NULL,
  country        text,
  importance     text NOT NULL CHECK (importance IN ('low', 'medium', 'high')),
  scheduled_at   timestamptz NOT NULL,
  forecast       text,
  previous       text,
  actual         text,
  first_seen_at  timestamptz NOT NULL,
  UNIQUE (provider_id, title, scheduled_at)
);
CREATE INDEX economic_events_upcoming_idx ON economic_events (scheduled_at);

-- ---------------------------------------------------------------------------
-- AI analysis
-- ---------------------------------------------------------------------------

CREATE TABLE prompt_versions (
  id                     uuid PRIMARY KEY DEFAULT uuidv7(),
  name                   text NOT NULL,
  version                integer NOT NULL CHECK (version > 0),
  sha256                 text NOT NULL,
  body                   text NOT NULL,
  output_schema_version  integer NOT NULL,
  created_at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name, version)
);

-- Classifications are append-only so a prompt change never rewrites history.
CREATE TABLE news_classifications (
  id                 uuid PRIMARY KEY DEFAULT uuidv7(),
  article_id         uuid NOT NULL REFERENCES news_articles ON DELETE CASCADE,
  prompt_version_id  uuid NOT NULL REFERENCES prompt_versions,
  model              text NOT NULL,
  event_type         text NOT NULL,
  sentiment          text NOT NULL CHECK (sentiment IN ('bullish', 'bearish', 'neutral')),
  potential_impact   text NOT NULL CHECK (potential_impact IN ('low', 'medium', 'high')),
  certainty          text NOT NULL CHECK (certainty IN ('confirmed', 'reported', 'speculation')),
  possibly_misleading boolean NOT NULL DEFAULT false,
  ai_summary         text NOT NULL,
  classified_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX news_classifications_article_idx ON news_classifications (article_id, classified_at DESC);

CREATE TABLE analysis_triggers (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  trigger_type   text NOT NULL,
  instrument_id  integer NOT NULL REFERENCES instruments,
  timeframe      timeframe_t,
  occurred_at    timestamptz NOT NULL,
  dedupe_key     text NOT NULL UNIQUE,
  disposition    text NOT NULL CHECK (disposition IN (
                   'analysed', 'reused_result', 'skipped_stale_data', 'skipped_outside_hours',
                   'skipped_cooldown', 'skipped_unchanged', 'skipped_no_candidate',
                   'skipped_low_quality', 'skipped_budget')),
  details        jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX analysis_triggers_recent_idx ON analysis_triggers (instrument_id, occurred_at DESC);

-- Exactly what the model saw, so every decision can be audited and replayed.
CREATE TABLE analysis_input_snapshots (
  id                   uuid PRIMARY KEY DEFAULT uuidv7(),
  instrument_id        integer NOT NULL REFERENCES instruments,
  as_of                timestamptz NOT NULL,
  feature_set_version  text NOT NULL,
  change_hash          text NOT NULL,
  provided_sources     jsonb NOT NULL,
  level_catalogue      jsonb NOT NULL,
  payload              jsonb NOT NULL,
  payload_sha256       text NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX analysis_input_snapshots_recent_idx ON analysis_input_snapshots (instrument_id, as_of DESC);

CREATE TABLE ai_analyses (
  id                 uuid PRIMARY KEY DEFAULT uuidv7(),
  trigger_id         uuid NOT NULL REFERENCES analysis_triggers,
  input_snapshot_id  uuid NOT NULL REFERENCES analysis_input_snapshots,
  prompt_version_id  uuid NOT NULL REFERENCES prompt_versions,
  route              text NOT NULL CHECK (route IN ('decision', 'review')),
  model_requested    text NOT NULL,
  model_used         text,
  effort             text NOT NULL,
  stop_reason        text,
  status             text NOT NULL CHECK (status IN ('valid', 'schema_invalid', 'evidence_invalid', 'refused', 'api_error', 'truncated')),
  rejection_detail   text,
  raw_response       jsonb,
  parsed_output      jsonb,
  action             action_t,
  started_at         timestamptz NOT NULL,
  completed_at       timestamptz NOT NULL,
  CHECK (status <> 'valid' OR (parsed_output IS NOT NULL AND action IS NOT NULL))
);
CREATE INDEX ai_analyses_recent_idx ON ai_analyses (completed_at DESC);

-- Dated list prices, so past costs stay correct after a price change.
CREATE TABLE ai_model_prices (
  id                      uuid PRIMARY KEY DEFAULT uuidv7(),
  model                   text NOT NULL,
  input_per_mtok          numeric(12, 6) NOT NULL CHECK (input_per_mtok >= 0),
  output_per_mtok         numeric(12, 6) NOT NULL CHECK (output_per_mtok >= 0),
  cache_read_per_mtok     numeric(12, 6) NOT NULL CHECK (cache_read_per_mtok >= 0),
  cache_write_5m_per_mtok numeric(12, 6) NOT NULL CHECK (cache_write_5m_per_mtok >= 0),
  cache_write_1h_per_mtok numeric(12, 6) NOT NULL CHECK (cache_write_1h_per_mtok >= 0),
  batch_multiplier        numeric(4, 3) NOT NULL DEFAULT 0.5 CHECK (batch_multiplier > 0 AND batch_multiplier <= 1),
  effective_from          timestamptz NOT NULL,
  source_url              text NOT NULL,
  UNIQUE (model, effective_from)
);

-- Tracks every external API, not only Claude. cost_usd is calculated from ai_model_prices.
-- output_tokens includes thinking; thinking_tokens shows that share separately.
CREATE TABLE api_usage (
  id                     uuid PRIMARY KEY DEFAULT uuidv7(),
  provider_id            smallint NOT NULL REFERENCES providers,
  purpose                text NOT NULL,
  route                  text,
  model                  text,
  analysis_id            uuid REFERENCES ai_analyses,
  request_count          integer NOT NULL DEFAULT 1,
  input_tokens           bigint NOT NULL DEFAULT 0,
  output_tokens          bigint NOT NULL DEFAULT 0,
  thinking_tokens        bigint NOT NULL DEFAULT 0,
  cache_read_tokens      bigint NOT NULL DEFAULT 0,
  cache_write_5m_tokens  bigint NOT NULL DEFAULT 0,
  cache_write_1h_tokens  bigint NOT NULL DEFAULT 0,
  is_batch               boolean NOT NULL DEFAULT false,
  latency_ms          integer,
  cost_usd            numeric(18, 8) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
  occurred_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX api_usage_day_idx ON api_usage (provider_id, occurred_at DESC);

-- ---------------------------------------------------------------------------
-- Backtest datasets and calibration
-- ---------------------------------------------------------------------------

CREATE TABLE dataset_versions (
  id              uuid PRIMARY KEY DEFAULT uuidv7(),
  name            text NOT NULL UNIQUE,
  manifest        jsonb NOT NULL,
  content_sha256  text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE calibration_models (
  id                         uuid PRIMARY KEY DEFAULT uuidv7(),
  strategy_configuration_id  uuid NOT NULL REFERENCES strategy_configurations,
  method                     text NOT NULL,
  out_of_sample_start        timestamptz NOT NULL,
  out_of_sample_end          timestamptz NOT NULL,
  sample_size                integer NOT NULL CHECK (sample_size > 0),
  brier_score                numeric(8, 6) NOT NULL,
  parameters                 jsonb NOT NULL,
  created_at                 timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Recommendations
-- ---------------------------------------------------------------------------

-- Immutable. Later changes go to recommendation_revisions and signal_events.
CREATE TABLE trade_recommendations (
  id                         uuid PRIMARY KEY DEFAULT uuidv7(),
  schema_version             integer NOT NULL,
  analysis_id                uuid REFERENCES ai_analyses,
  strategy_configuration_id  uuid NOT NULL REFERENCES strategy_configurations,
  account_id                 uuid NOT NULL REFERENCES trading_accounts,
  provider_id                smallint NOT NULL REFERENCES providers,
  instrument_id              integer NOT NULL REFERENCES instruments,
  timeframe                  timeframe_t NOT NULL,
  action                     action_t NOT NULL,
  entry_type                 entry_type_t,
  market_price               decimal_t NOT NULL CHECK (market_price > 0),
  entry_price                decimal_t,
  entry_zone_low             decimal_t,
  entry_zone_high            decimal_t,
  stop_loss                  decimal_t,
  is_countertrend            boolean NOT NULL DEFAULT false,
  dedupe_key                 text,

  -- Assessments stay separate. None of them is a win probability unless
  -- probability_status is 'calibrated'.
  setup_quality_score        numeric(5, 2) CHECK (setup_quality_score BETWEEN 0 AND 100),
  news_alignment             text NOT NULL CHECK (news_alignment IN ('aligned', 'conflicting', 'neutral', 'unavailable')),
  data_reliability_score     numeric(5, 2) NOT NULL CHECK (data_reliability_score BETWEEN 0 AND 100),
  analyst_assessment         text CHECK (analyst_assessment IN ('low', 'medium', 'high')),
  probability                numeric(6, 5) CHECK (probability BETWEEN 0 AND 1),
  probability_status         text NOT NULL DEFAULT 'unavailable' CHECK (probability_status IN ('unavailable', 'calibrated')),
  calibration_model_id       uuid REFERENCES calibration_models,

  technical_explanation      text NOT NULL,
  fundamental_explanation    text NOT NULL,
  supporting_evidence        jsonb NOT NULL,
  conflicting_evidence       jsonb NOT NULL,
  invalidation_conditions    jsonb NOT NULL,
  data_as_of                 timestamptz NOT NULL,
  data_age_ms                integer NOT NULL CHECK (data_age_ms >= 0),
  created_at                 timestamptz NOT NULL DEFAULT now(),
  expires_at                 timestamptz NOT NULL,

  CONSTRAINT rec_trade_fields_present CHECK (
    action NOT IN ('BUY', 'SELL')
    OR (entry_type IS NOT NULL AND entry_price IS NOT NULL AND stop_loss IS NOT NULL AND dedupe_key IS NOT NULL)
  ),
  CONSTRAINT rec_no_levels_without_trade CHECK (
    action IN ('BUY', 'SELL') OR (entry_price IS NULL AND stop_loss IS NULL AND entry_type IS NULL)
  ),
  CONSTRAINT rec_buy_stop_below_entry CHECK (action <> 'BUY' OR stop_loss < entry_price),
  CONSTRAINT rec_sell_stop_above_entry CHECK (action <> 'SELL' OR stop_loss > entry_price),
  CONSTRAINT rec_expiry_after_creation CHECK (expires_at > created_at),
  CONSTRAINT rec_evidence_required CHECK (
    action NOT IN ('BUY', 'SELL') OR jsonb_array_length(supporting_evidence) > 0
  ),
  CONSTRAINT rec_invalidation_required CHECK (
    action = 'NO_TRADE' OR jsonb_array_length(invalidation_conditions) > 0
  ),
  CONSTRAINT rec_probability_consistent CHECK (
    (probability_status = 'unavailable' AND probability IS NULL AND calibration_model_id IS NULL)
    OR (probability_status = 'calibrated' AND probability IS NOT NULL AND calibration_model_id IS NOT NULL)
  )
);
CREATE INDEX trade_recommendations_recent_idx ON trade_recommendations (instrument_id, created_at DESC);
CREATE INDEX trade_recommendations_action_idx ON trade_recommendations (action, created_at DESC);

-- One to three rows. Targets are never forced when no reachable level exists.
CREATE TABLE trade_targets (
  recommendation_id    uuid NOT NULL REFERENCES trade_recommendations,
  target_no            smallint NOT NULL CHECK (target_no BETWEEN 1 AND 3),
  price                decimal_t NOT NULL CHECK (price > 0),
  allocation_fraction  decimal_t NOT NULL CHECK (allocation_fraction > 0 AND allocation_fraction <= 1),
  net_reward_risk      decimal_t NOT NULL,
  PRIMARY KEY (recommendation_id, target_no)
);

CREATE TABLE recommendation_revisions (
  id                 uuid PRIMARY KEY DEFAULT uuidv7(),
  recommendation_id  uuid NOT NULL REFERENCES trade_recommendations,
  revision_no        integer NOT NULL CHECK (revision_no > 0),
  reason             text NOT NULL,
  changes            jsonb NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (recommendation_id, revision_no)
);

CREATE TABLE risk_assessments (
  id                 uuid PRIMARY KEY DEFAULT uuidv7(),
  recommendation_id  uuid NOT NULL REFERENCES trade_recommendations,
  risk_profile_id    uuid NOT NULL REFERENCES risk_profiles,
  engine_version     text NOT NULL,
  decision           text NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
  rejection_codes    text[] NOT NULL DEFAULT '{}',
  equity             decimal_t NOT NULL,
  risk_budget        decimal_t NOT NULL,
  entry_fill_est     decimal_t,
  stop_fill_est      decimal_t,
  risk_per_unit      decimal_t,
  quantity           decimal_t,
  notional           decimal_t,
  leverage           decimal_t,
  margin_required    decimal_t,
  fees_est           decimal_t,
  spread_est         decimal_t,
  slippage_est       decimal_t,
  funding_est        decimal_t,
  max_account_risk   decimal_t,
  reward_risk_net    decimal_t,
  inputs             jsonb NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT risk_rejection_has_reason CHECK (decision <> 'REJECTED' OR cardinality(rejection_codes) > 0),
  CONSTRAINT risk_approval_has_size CHECK (decision <> 'APPROVED' OR (quantity > 0 AND reward_risk_net IS NOT NULL))
);
CREATE INDEX risk_assessments_recommendation_idx ON risk_assessments (recommendation_id);

-- Append-only history of state changes.
CREATE TABLE signal_events (
  id                 uuid PRIMARY KEY DEFAULT uuidv7(),
  recommendation_id  uuid NOT NULL REFERENCES trade_recommendations,
  from_state         signal_state_t,
  to_state           signal_state_t NOT NULL,
  market_price       decimal_t,
  occurred_at        timestamptz NOT NULL,
  cause              jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX signal_events_recommendation_idx ON signal_events (recommendation_id, occurred_at);

-- Current state as a projection of signal_events. Blocks duplicate active signals.
CREATE TABLE signal_current_state (
  recommendation_id  uuid PRIMARY KEY REFERENCES trade_recommendations,
  account_id         uuid NOT NULL REFERENCES trading_accounts,
  dedupe_key         text NOT NULL,
  state              signal_state_t NOT NULL,
  updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX signal_one_active_per_key_uq
  ON signal_current_state (account_id, dedupe_key)
  WHERE state IN ('CANDIDATE', 'VALIDATED', 'ACTIVE', 'ENTRY_TRIGGERED', 'TP1_HIT', 'TP2_HIT');

CREATE TABLE alerts (
  id                 uuid PRIMARY KEY DEFAULT uuidv7(),
  recommendation_id  uuid REFERENCES trade_recommendations,
  channel            text NOT NULL,
  dedupe_key         text NOT NULL UNIQUE,
  payload            jsonb NOT NULL,
  status             text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  sent_at            timestamptz
);

-- ---------------------------------------------------------------------------
-- Paper trading and outcomes
-- ---------------------------------------------------------------------------

CREATE TABLE paper_positions (
  id                 uuid PRIMARY KEY DEFAULT uuidv7(),
  account_id         uuid NOT NULL REFERENCES trading_accounts,
  recommendation_id  uuid NOT NULL UNIQUE REFERENCES trade_recommendations,
  instrument_id      integer NOT NULL REFERENCES instruments,
  side               side_t NOT NULL,
  status             text NOT NULL CHECK (status IN ('pending_entry', 'open', 'closed', 'cancelled')),
  planned_quantity   decimal_t NOT NULL CHECK (planned_quantity > 0),
  open_quantity      decimal_t NOT NULL DEFAULT 0 CHECK (open_quantity >= 0),
  average_entry      decimal_t,
  realized_pnl       decimal_t NOT NULL DEFAULT 0,
  costs_paid         decimal_t NOT NULL DEFAULT 0,
  opened_at          timestamptz,
  closed_at          timestamptz,
  updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX paper_positions_open_idx ON paper_positions (account_id) WHERE status IN ('pending_entry', 'open');

-- Every simulated fill. The idempotency key prevents a replayed event from filling twice.
-- reconstructed marks fills worked out from 1M candles after the computer was off or asleep.
-- Live spread was unknown at those moments, so reports keep them separate.
CREATE TABLE paper_executions (
  id               uuid PRIMARY KEY DEFAULT uuidv7(),
  position_id      uuid NOT NULL REFERENCES paper_positions,
  kind             text NOT NULL CHECK (kind IN ('entry', 'tp1', 'tp2', 'tp3', 'stop', 'invalidation', 'expiry', 'funding')),
  quantity         decimal_t NOT NULL CHECK (quantity >= 0),
  fill_price       decimal_t,
  fee              decimal_t NOT NULL DEFAULT 0,
  spread_cost      decimal_t NOT NULL DEFAULT 0,
  slippage_cost    decimal_t NOT NULL DEFAULT 0,
  funding          decimal_t NOT NULL DEFAULT 0,
  market_event     jsonb NOT NULL,
  idempotency_key  text NOT NULL UNIQUE,
  simulated        boolean NOT NULL DEFAULT true CHECK (simulated),
  reconstructed    boolean NOT NULL DEFAULT false,
  executed_at      timestamptz NOT NULL
);
CREATE INDEX paper_executions_position_idx ON paper_executions (position_id, executed_at);

-- counts_for_win_rate is derived, so unresolved or unfilled results cannot inflate win rate.
CREATE TABLE trade_outcomes (
  recommendation_id    uuid PRIMARY KEY REFERENCES trade_recommendations,
  outcome              outcome_t NOT NULL,
  counts_for_win_rate  boolean GENERATED ALWAYS AS (outcome IN ('WIN', 'LOSS', 'BREAKEVEN')) STORED,
  gross_pnl            decimal_t,
  costs                decimal_t,
  net_pnl              decimal_t,
  r_multiple           decimal_t,
  max_favourable       decimal_t,
  max_adverse          decimal_t,
  market_regime        text,
  news_category        text,
  resolved_at          timestamptz NOT NULL
);
CREATE INDEX trade_outcomes_resolved_idx ON trade_outcomes (resolved_at DESC);

-- ---------------------------------------------------------------------------
-- Backtests
-- ---------------------------------------------------------------------------

CREATE TABLE backtest_runs (
  id                         uuid PRIMARY KEY DEFAULT uuidv7(),
  strategy_configuration_id  uuid NOT NULL REFERENCES strategy_configurations,
  dataset_version_id         uuid NOT NULL REFERENCES dataset_versions,
  split                      backtest_split_t NOT NULL,
  fold                       integer,
  window_start               timestamptz NOT NULL,
  window_end                 timestamptz NOT NULL,
  cost_model                 jsonb NOT NULL,
  git_sha                    text NOT NULL,
  seed                       bigint NOT NULL,
  trial_number               integer NOT NULL CHECK (trial_number > 0),
  status                     text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
  metrics                    jsonb,
  started_at                 timestamptz NOT NULL DEFAULT now(),
  finished_at                timestamptz,
  CHECK (window_end > window_start)
);
CREATE INDEX backtest_runs_strategy_idx ON backtest_runs (strategy_configuration_id, split);
-- The final holdout can be evaluated once for each strategy version.
CREATE UNIQUE INDEX backtest_holdout_once_uq ON backtest_runs (strategy_configuration_id)
  WHERE split = 'holdout' AND status <> 'failed';

CREATE TABLE backtest_trades (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  run_id         uuid NOT NULL REFERENCES backtest_runs ON DELETE CASCADE,
  instrument_id  integer NOT NULL REFERENCES instruments,
  side           side_t NOT NULL,
  signal_time    timestamptz NOT NULL,
  entry_time     timestamptz,
  exit_time      timestamptz,
  entry_price    decimal_t,
  exit_price     decimal_t,
  quantity       decimal_t,
  exit_reason    text NOT NULL,
  fees           decimal_t NOT NULL DEFAULT 0,
  spread_cost    decimal_t NOT NULL DEFAULT 0,
  slippage_cost  decimal_t NOT NULL DEFAULT 0,
  funding        decimal_t NOT NULL DEFAULT 0,
  net_pnl        decimal_t,
  r_multiple     decimal_t,
  CHECK (entry_time IS NULL OR entry_time >= signal_time)
);
CREATE INDEX backtest_trades_run_idx ON backtest_trades (run_id, signal_time);

CREATE TABLE backtest_equity_points (
  run_id    uuid NOT NULL REFERENCES backtest_runs ON DELETE CASCADE,
  at        timestamptz NOT NULL,
  equity    decimal_t NOT NULL,
  drawdown  decimal_t NOT NULL,
  PRIMARY KEY (run_id, at)
);

-- ---------------------------------------------------------------------------
-- Operations and audit
-- ---------------------------------------------------------------------------

CREATE TABLE system_events (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  occurred_at  timestamptz NOT NULL DEFAULT now(),
  severity     text NOT NULL CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical')),
  component    text NOT NULL,
  event_type   text NOT NULL,
  message      text NOT NULL,
  data         jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX system_events_recent_idx ON system_events (occurred_at DESC);
CREATE INDEX system_events_severity_idx ON system_events (severity, occurred_at DESC) WHERE severity IN ('error', 'critical');

CREATE TABLE audit_log (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  occurred_at  timestamptz NOT NULL DEFAULT now(),
  actor        text NOT NULL,
  action       text NOT NULL,
  object_type  text NOT NULL,
  object_id    text,
  before       jsonb,
  after        jsonb,
  request_id   text,
  ip_address   inet
);
CREATE INDEX audit_log_recent_idx ON audit_log (occurred_at DESC);

-- ---------------------------------------------------------------------------
-- Immutability
-- ---------------------------------------------------------------------------

CREATE FUNCTION forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is not allowed on immutable table %', TG_OP, TG_TABLE_NAME
    USING ERRCODE = 'restrict_violation';
END
$$;

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'risk_profiles',
    'market_candle_revisions',
    'analysis_input_snapshots',
    'ai_analyses',
    'trade_recommendations',
    'trade_targets',
    'recommendation_revisions',
    'risk_assessments',
    'signal_events',
    'paper_executions',
    'trade_outcomes',
    'audit_log'
  ]
  LOOP
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I
         FOR EACH ROW EXECUTE FUNCTION forbid_mutation()', t || '_no_mutation', t);
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE TRUNCATE ON %I
         FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()', t || '_no_truncate', t);
  END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------------

DO $$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['ati_ingest', 'ati_app', 'ati_readonly']
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
    END IF;
  END LOOP;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO ati_readonly;
REVOKE SELECT ON users FROM ati_readonly;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO ati_ingest;
REVOKE SELECT ON users FROM ati_ingest;
GRANT INSERT ON
  market_candles, market_candle_revisions, market_snapshots, funding_rates,
  liquidation_samples, instrument_rule_snapshots, ingest_runs, market_gaps,
  system_events, api_usage
TO ati_ingest;
GRANT UPDATE ON ingest_runs, market_gaps, instrument_rule_snapshots TO ati_ingest;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO ati_app;
GRANT INSERT ON ALL TABLES IN SCHEMA public TO ati_app;
REVOKE INSERT ON market_candles, market_snapshots, funding_rates, liquidation_samples FROM ati_app;
GRANT UPDATE ON
  users, trading_accounts, timeframe_profiles, paper_positions, signal_current_state,
  alerts, backtest_runs, news_articles
TO ati_app;

COMMIT;
