"""Indicator values and detected patterns."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

STATEMENTS = (
    """CREATE TABLE technical_indicators (
      provider_id          smallint NOT NULL REFERENCES providers,
      instrument_id        integer NOT NULL REFERENCES instruments,
      timeframe            timeframe_t NOT NULL,
      close_time           timestamptz NOT NULL,
      feature_set_version  text NOT NULL,
      values               jsonb NOT NULL,
      computed_at          timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (provider_id, instrument_id, timeframe, close_time, feature_set_version)
    )""",
    """CREATE TABLE detected_patterns (
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
      CHECK (zone_low IS NULL OR zone_high IS NULL OR zone_high >= zone_low),
      UNIQUE (provider_id, instrument_id, timeframe, pattern_type, direction, formed_at, detected_at, rule_version)
    )""",
    "CREATE INDEX detected_patterns_recent_idx ON detected_patterns (instrument_id, timeframe, detected_at DESC)",
    "CREATE INDEX detected_patterns_type_idx ON detected_patterns (pattern_type, detected_at DESC)",
    "REVOKE ALL ON technical_indicators, detected_patterns FROM PUBLIC",
    "GRANT SELECT ON technical_indicators, detected_patterns TO ati_readonly, ati_ingest, ati_app",
    "GRANT INSERT, UPDATE ON technical_indicators, detected_patterns TO ati_app",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE detected_patterns")
    op.execute("DROP TABLE technical_indicators")
