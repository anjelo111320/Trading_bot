"""Claude's daily cost limit as one setting the owner changes on the dashboard (D062).

Before this, the limit was $3 a day, written twice in code: once for news labels and once for
exit advice, both counting every Claude call together. Each change is a new row, so the limit
in force at any time can be read back. The owner chose $0.50 on 2026-11-13.
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

STATEMENTS = (
    """CREATE TABLE ai_budgets (
         id               uuid PRIMARY KEY DEFAULT uuidv7(),
         daily_limit_usd  decimal_t NOT NULL CHECK (daily_limit_usd >= 0),
         changed_by       text NOT NULL,
         note             text,
         created_at       timestamptz NOT NULL DEFAULT now()
       )""",
    "CREATE INDEX ai_budgets_latest ON ai_budgets (created_at)",
    "GRANT SELECT ON ai_budgets TO ati_readonly, ati_ingest, ati_app",
    "GRANT INSERT ON ai_budgets TO ati_app",
    """CREATE TRIGGER ai_budgets_no_mutation BEFORE UPDATE OR DELETE ON ai_budgets
       FOR EACH ROW EXECUTE FUNCTION forbid_mutation()""",
    """INSERT INTO ai_budgets (daily_limit_usd, changed_by, note)
       VALUES (0.50, 'owner', 'D062: chosen on 2026-11-13, down from $3 in code')""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE ai_budgets")
