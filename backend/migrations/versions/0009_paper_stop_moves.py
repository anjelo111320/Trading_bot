"""Tightened stops for open paper positions, for strategies that trail their stop (D039).

A move is decided at a candle close and takes effect from the next candle, as in backtests.
Rows are never changed afterwards, so a replay of a paper trade always gives the same fills.
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

STATEMENTS = (
    """CREATE TABLE paper_stop_moves (
         position_id      uuid NOT NULL REFERENCES paper_positions,
         effective_after  timestamptz NOT NULL,
         stop_price       decimal_t NOT NULL CHECK (stop_price > 0),
         reason           text NOT NULL,
         created_at       timestamptz NOT NULL DEFAULT now(),
         PRIMARY KEY (position_id, effective_after)
       )""",
    "GRANT SELECT ON paper_stop_moves TO ati_readonly, ati_ingest, ati_app",
    "GRANT INSERT ON paper_stop_moves TO ati_app",
    """CREATE TRIGGER paper_stop_moves_no_mutation BEFORE UPDATE OR DELETE ON paper_stop_moves
       FOR EACH ROW EXECUTE FUNCTION forbid_mutation()""",
    """CREATE TRIGGER paper_stop_moves_no_truncate BEFORE TRUNCATE ON paper_stop_moves
       FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE paper_stop_moves")
