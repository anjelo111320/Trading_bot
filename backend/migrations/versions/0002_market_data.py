"""Providers, instruments, market data, operations and audit tables."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TERMS_URL = "https://www.binance.com/en/terms"

TABLES = """
CREATE TYPE gap_state_t AS ENUM ('detected', 'repairing', 'repaired', 'provider_missing');

CREATE TABLE users (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  email          text NOT NULL,
  password_hash  text NOT NULL,
  role           text NOT NULL DEFAULT 'owner' CHECK (role IN ('owner', 'viewer')),
  is_active      boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_lower_uq ON users (lower(email));

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

CREATE TABLE provider_instruments (
  provider_id      smallint NOT NULL REFERENCES providers,
  instrument_id    integer NOT NULL REFERENCES instruments,
  provider_symbol  text NOT NULL,
  capabilities     jsonb NOT NULL DEFAULT '{}',
  is_active        boolean NOT NULL DEFAULT true,
  PRIMARY KEY (provider_id, instrument_id),
  UNIQUE (provider_id, provider_symbol)
);

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

CREATE TABLE liquidation_samples (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  provider_id    smallint NOT NULL REFERENCES providers,
  instrument_id  integer NOT NULL REFERENCES instruments,
  event_time     timestamptz NOT NULL,
  side           text NOT NULL CHECK (side IN ('BUY', 'SELL')),
  price          decimal_t NOT NULL CHECK (price > 0),
  quantity       decimal_t NOT NULL CHECK (quantity > 0),
  received_at    timestamptz NOT NULL,
  UNIQUE (provider_id, instrument_id, event_time, side, price, quantity)
);
CREATE INDEX liquidation_samples_lookup_idx ON liquidation_samples (provider_id, instrument_id, event_time DESC);

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
"""

IMMUTABLE = ("market_candle_revisions", "audit_log")

GRANTS = """
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO ati_readonly, ati_ingest, ati_app;
REVOKE SELECT ON users FROM ati_readonly, ati_ingest;

GRANT INSERT ON
  market_candles, market_candle_revisions, market_snapshots, funding_rates,
  liquidation_samples, instrument_rule_snapshots, ingest_runs, market_gaps, system_events
TO ati_ingest;
-- Candles are updated only alongside a market_candle_revisions row, in one transaction.
GRANT UPDATE ON ingest_runs, market_gaps, instrument_rule_snapshots, market_candles, market_snapshots TO ati_ingest;

GRANT INSERT ON users, system_events, audit_log TO ati_app;
GRANT UPDATE ON users TO ati_app;
"""

SEEDS = f"""
INSERT INTO providers (code, name, kind, terms_url, terms_version, terms_reviewed_at, notes) VALUES
  ('binance_spot', 'Binance Spot', 'market_data', '{TERMS_URL}', 'read 2026-11-02', '2026-11-02',
   'Public data, personal use (D006)'),
  ('binance_usdm', 'Binance USD-M Futures', 'market_data', '{TERMS_URL}', 'read 2026-11-02', '2026-11-02',
   'Public data, personal use (D006)'),
  ('synthetic', 'Synthetic development data', 'synthetic', NULL, NULL, NULL,
   'Generated data. Never real market data');

INSERT INTO instruments (canonical_symbol, instrument_type, base_asset, quote_asset, settle_asset) VALUES
  ('BTCUSDT', 'spot', 'BTC', 'USDT', 'USDT'),
  ('ETHUSDT', 'spot', 'ETH', 'USDT', 'USDT'),
  ('BTCUSDT', 'linear_perpetual', 'BTC', 'USDT', 'USDT'),
  ('ETHUSDT', 'linear_perpetual', 'ETH', 'USDT', 'USDT');

INSERT INTO provider_instruments (provider_id, instrument_id, provider_symbol, capabilities)
SELECT p.id, i.id, i.canonical_symbol,
       jsonb_build_object('candles', true, 'bid_ask', true, 'funding', p.code = 'binance_usdm',
                          'open_interest', p.code = 'binance_usdm', 'liquidations', p.code = 'binance_usdm')
FROM providers p JOIN instruments i
  ON (p.code = 'binance_spot' AND i.instrument_type = 'spot')
  OR (p.code = 'binance_usdm' AND i.instrument_type = 'linear_perpetual');

INSERT INTO provider_instruments (provider_id, instrument_id, provider_symbol, capabilities)
SELECT p.id, i.id, 'SYN-' || i.canonical_symbol, '{{"candles": true, "bid_ask": true}}'::jsonb
FROM providers p JOIN instruments i ON p.code = 'synthetic' AND i.instrument_type = 'spot';
"""

DROPPED = (
    "audit_log",
    "system_events",
    "liquidation_samples",
    "funding_rates",
    "market_snapshots",
    "market_gaps",
    "market_candle_revisions",
    "market_candles",
    "ingest_runs",
    "instrument_rule_snapshots",
    "provider_instruments",
    "instruments",
    "providers",
    "users",
)


def run_script(script: str) -> None:
    """asyncpg runs one statement per call."""
    for statement in script.split(";\n"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    run_script(TABLES)
    for table in IMMUTABLE:
        op.execute(
            f"""CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION forbid_mutation()"""
        )
        op.execute(
            f"""CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()"""
        )
    run_script(GRANTS)
    run_script(SEEDS)


def downgrade() -> None:
    for table in DROPPED:
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP TYPE gap_state_t")
