"""The latest Binance demo snapshot per account, for the dashboard (D048).

The quant worker writes it once a minute, after its stop check, so the API can show the
account without ever holding exchange keys. Only the latest row is kept; every order stays
in the append-only `exchange_orders`.
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

STATEMENTS = (
    """CREATE TABLE exchange_status (
         account_id  uuid PRIMARY KEY REFERENCES trading_accounts,
         taken_at    timestamptz NOT NULL,
         body        jsonb NOT NULL
       )""",
    "GRANT SELECT ON exchange_status TO ati_readonly, ati_ingest, ati_app",
    "GRANT INSERT, UPDATE ON exchange_status TO ati_app",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE exchange_status")
