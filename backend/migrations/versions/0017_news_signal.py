"""The news signal (D055): what the news said beside every signal, and at every 4H close.

Each recommendation keeps its news alignment, already a column, and now the reading behind
it. `news_readings` holds each coin's reading at each 4H close with the close price, so the
pre-registered test in docs/39 can score it forward. Both are append-only.
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

STATEMENTS = (
    "ALTER TABLE trade_recommendations ADD COLUMN news_context jsonb",
    """CREATE TABLE news_readings (
         instrument_id  integer NOT NULL REFERENCES instruments,
         decided_at     timestamptz NOT NULL,
         rule_version   integer NOT NULL CHECK (rule_version > 0),
         direction      text NOT NULL CHECK (direction IN ('bullish', 'bearish', 'neutral')),
         score          decimal_t NOT NULL,
         stories        integer NOT NULL CHECK (stories >= 0),
         close_price    decimal_t NOT NULL CHECK (close_price > 0),
         context        jsonb NOT NULL,
         created_at     timestamptz NOT NULL DEFAULT now(),
         PRIMARY KEY (instrument_id, decided_at, rule_version)
       )""",
    "GRANT SELECT ON news_readings TO ati_readonly, ati_ingest, ati_app",
    "GRANT INSERT ON news_readings TO ati_app",
    """CREATE TRIGGER news_readings_no_mutation BEFORE UPDATE OR DELETE ON news_readings
       FOR EACH ROW EXECUTE FUNCTION forbid_mutation()""",
    """CREATE TRIGGER news_readings_no_truncate BEFORE TRUNCATE ON news_readings
       FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE news_readings")
    op.execute("ALTER TABLE trade_recommendations DROP COLUMN news_context")
