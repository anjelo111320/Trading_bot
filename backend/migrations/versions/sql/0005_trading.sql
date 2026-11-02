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
CREATE TABLE timeframe_profiles (
  id          uuid PRIMARY KEY DEFAULT uuidv7(),
  user_id     uuid NOT NULL REFERENCES users,
  name        text NOT NULL,
  roles       jsonb NOT NULL,
  is_default  boolean NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, name)
);
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
CREATE TABLE trade_recommendations (
  id                         uuid PRIMARY KEY DEFAULT uuidv7(),
  schema_version             integer NOT NULL,
  analysis_id                uuid,
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
CREATE TABLE signal_events (
  id                 uuid PRIMARY KEY DEFAULT uuidv7(),
  recommendation_id  uuid NOT NULL REFERENCES trade_recommendations,
  from_state         signal_state_t,
  to_state           signal_state_t NOT NULL,
  market_price       decimal_t,
  occurred_at        timestamptz NOT NULL,
  cause              jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE signal_current_state (
  recommendation_id  uuid PRIMARY KEY REFERENCES trade_recommendations,
  account_id         uuid NOT NULL REFERENCES trading_accounts,
  dedupe_key         text NOT NULL,
  state              signal_state_t NOT NULL,
  updated_at         timestamptz NOT NULL DEFAULT now()
);
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
CREATE TABLE dataset_versions (
  id              uuid PRIMARY KEY DEFAULT uuidv7(),
  name            text NOT NULL UNIQUE,
  manifest        jsonb NOT NULL,
  content_sha256  text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);
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
CREATE TABLE backtest_equity_points (
  run_id    uuid NOT NULL REFERENCES backtest_runs ON DELETE CASCADE,
  at        timestamptz NOT NULL,
  equity    decimal_t NOT NULL,
  drawdown  decimal_t NOT NULL,
  PRIMARY KEY (run_id, at)
);
CREATE UNIQUE INDEX timeframe_profiles_one_default_uq ON timeframe_profiles (user_id) WHERE is_default;
CREATE INDEX trade_recommendations_recent_idx ON trade_recommendations (instrument_id, created_at DESC);
CREATE INDEX trade_recommendations_action_idx ON trade_recommendations (action, created_at DESC);
CREATE INDEX risk_assessments_recommendation_idx ON risk_assessments (recommendation_id);
CREATE INDEX signal_events_recommendation_idx ON signal_events (recommendation_id, occurred_at);
CREATE UNIQUE INDEX signal_one_active_per_key_uq
  ON signal_current_state (account_id, dedupe_key)
  WHERE state IN ('CANDIDATE', 'VALIDATED', 'ACTIVE', 'ENTRY_TRIGGERED', 'TP1_HIT', 'TP2_HIT');
CREATE INDEX paper_positions_open_idx ON paper_positions (account_id) WHERE status IN ('pending_entry', 'open');
CREATE INDEX paper_executions_position_idx ON paper_executions (position_id, executed_at);
CREATE INDEX trade_outcomes_resolved_idx ON trade_outcomes (resolved_at DESC);
CREATE INDEX backtest_runs_strategy_idx ON backtest_runs (strategy_configuration_id, split);
CREATE UNIQUE INDEX backtest_holdout_once_uq ON backtest_runs (strategy_configuration_id)
  WHERE split = 'holdout' AND status <> 'failed';
CREATE INDEX backtest_trades_run_idx ON backtest_trades (run_id, signal_time);

INSERT INTO fee_schedules (provider_id, instrument_type, maker_fee, taker_fee, effective_from, source_url)
SELECT id, 'spot', 0.001, 0.001, '2026-11-02T00:00:00Z', 'https://www.binance.com/en/fee/schedule'
FROM providers WHERE code = 'binance_spot';
INSERT INTO fee_schedules (provider_id, instrument_type, maker_fee, taker_fee, effective_from, source_url)
SELECT id, 'linear_perpetual', 0.0002, 0.0005, '2026-11-02T00:00:00Z', 'https://www.binance.com/en/fee/futureFee'
FROM providers WHERE code = 'binance_usdm';

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
GRANT SELECT ON
  trading_accounts, risk_profiles, timeframe_profiles, fee_schedules, strategy_configurations,
  calibration_models, trade_recommendations, trade_targets, recommendation_revisions,
  risk_assessments, signal_events, signal_current_state, alerts, paper_positions,
  paper_executions, trade_outcomes, dataset_versions, backtest_runs, backtest_trades,
  backtest_equity_points
TO ati_readonly, ati_ingest, ati_app;
GRANT INSERT ON
  trading_accounts, risk_profiles, timeframe_profiles, strategy_configurations, calibration_models,
  trade_recommendations, trade_targets, recommendation_revisions, risk_assessments, signal_events,
  signal_current_state, alerts, paper_positions, paper_executions, trade_outcomes,
  dataset_versions, backtest_runs, backtest_trades, backtest_equity_points
TO ati_app;
GRANT UPDATE ON
  trading_accounts, timeframe_profiles, paper_positions, signal_current_state, alerts, backtest_runs
TO ati_app
