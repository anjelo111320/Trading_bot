"""Model forecasts and their outcomes, kept as evidence (D040). Neither can be changed later."""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

STATEMENTS = (
    """INSERT INTO providers (code, name, kind, terms_url, terms_reviewed_at, notes) VALUES
         ('kronos', 'Kronos forecasting model', 'ai',
          'https://github.com/shiyu-coder/Kronos/blob/master/LICENSE', '2026-11-05',
          'MIT code and weights. Runs offline on this computer from vendor/Kronos.')""",
    """CREATE TABLE model_forecasts (
      id                  uuid PRIMARY KEY DEFAULT uuidv7(),
      provider_id         smallint NOT NULL REFERENCES providers,
      instrument_id       integer NOT NULL REFERENCES instruments,
      timeframe           timeframe_t NOT NULL,
      as_of               timestamptz NOT NULL,
      horizon_candles     integer NOT NULL CHECK (horizon_candles > 0),
      model_provider_id   smallint NOT NULL REFERENCES providers,
      model               text NOT NULL,
      model_revision      text NOT NULL,
      tokenizer           text NOT NULL,
      tokenizer_revision  text NOT NULL,
      code_revision       text NOT NULL,
      seed                integer NOT NULL,
      context_candles     integer NOT NULL CHECK (context_candles > 0),
      reason              text NOT NULL CHECK (reason IN ('setup', 'manual', 'study')),
      last_close          decimal_t NOT NULL CHECK (last_close > 0),
      atr                 double precision NOT NULL CHECK (atr > 0),
      paths               jsonb NOT NULL,
      summary             jsonb NOT NULL,
      baseline            jsonb NOT NULL,
      runtime_ms          integer NOT NULL CHECK (runtime_ms >= 0),
      created_at          timestamptz NOT NULL DEFAULT now(),
      UNIQUE (provider_id, instrument_id, timeframe, as_of, horizon_candles, model, model_revision, seed)
    )""",
    "CREATE INDEX model_forecasts_recent_idx ON model_forecasts (instrument_id, timeframe, as_of DESC)",
    """CREATE TABLE model_forecast_outcomes (
      forecast_id     uuid PRIMARY KEY REFERENCES model_forecasts,
      realized_high   decimal_t NOT NULL,
      realized_low    decimal_t NOT NULL,
      realized_close  decimal_t NOT NULL,
      model_score     jsonb NOT NULL,
      baseline_score  jsonb NOT NULL,
      resolved_at     timestamptz NOT NULL DEFAULT now(),
      CHECK (realized_high >= realized_low)
    )""",
    "REVOKE ALL ON model_forecasts, model_forecast_outcomes FROM PUBLIC",
    "GRANT SELECT ON model_forecasts, model_forecast_outcomes TO ati_readonly, ati_ingest, ati_app",
    "GRANT INSERT ON model_forecasts, model_forecast_outcomes TO ati_app",
)

IMMUTABLE = ("model_forecasts", "model_forecast_outcomes")


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)
    for table in IMMUTABLE:
        op.execute(
            f"""CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION forbid_mutation()"""
        )
        op.execute(
            f"""CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()"""
        )


def downgrade() -> None:
    op.execute("DROP TABLE model_forecast_outcomes")
    op.execute("DROP TABLE model_forecasts")
    op.execute("DELETE FROM providers WHERE code = 'kronos'")
