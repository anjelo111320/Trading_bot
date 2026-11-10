"""Binance demo trading (D048): an account mode for test funds, and every exchange order kept.

A real-money account stays unrepresentable: the mode check allows paper and exchange demo
only. Orders and the day's starting equity are append-only, like paper fills.
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

STATEMENTS = (
    "ALTER TABLE trading_accounts DROP CONSTRAINT trading_accounts_mode_check",
    """ALTER TABLE trading_accounts ADD CONSTRAINT trading_accounts_mode_check
       CHECK (mode IN ('paper', 'exchange_demo'))""",
    """CREATE TABLE exchange_orders (
         id                 uuid PRIMARY KEY DEFAULT uuidv7(),
         account_id         uuid NOT NULL REFERENCES trading_accounts,
         recommendation_id  uuid REFERENCES trade_recommendations,
         symbol             text NOT NULL,
         kind               text NOT NULL
                            CHECK (kind IN ('entry', 'stop', 'tp1', 'tp2', 'tp3', 'close')),
         client_id          text NOT NULL,
         trade_key          text,
         stop_price         decimal_t CHECK (stop_price > 0),
         request            jsonb NOT NULL,
         response           jsonb,
         error              text,
         created_at         timestamptz NOT NULL DEFAULT now()
       )""",
    "CREATE INDEX exchange_orders_account_symbol ON exchange_orders (account_id, symbol, created_at)",
    """CREATE TABLE exchange_equity_days (
         account_id  uuid NOT NULL REFERENCES trading_accounts,
         day         date NOT NULL,
         equity      decimal_t NOT NULL CHECK (equity > 0),
         created_at  timestamptz NOT NULL DEFAULT now(),
         PRIMARY KEY (account_id, day)
       )""",
    "GRANT SELECT ON exchange_orders, exchange_equity_days TO ati_readonly, ati_ingest, ati_app",
    "GRANT INSERT ON exchange_orders, exchange_equity_days TO ati_app",
    """CREATE TRIGGER exchange_orders_no_mutation BEFORE UPDATE OR DELETE ON exchange_orders
       FOR EACH ROW EXECUTE FUNCTION forbid_mutation()""",
    """CREATE TRIGGER exchange_orders_no_truncate BEFORE TRUNCATE ON exchange_orders
       FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()""",
    """CREATE TRIGGER exchange_equity_days_no_mutation BEFORE UPDATE OR DELETE
       ON exchange_equity_days FOR EACH ROW EXECUTE FUNCTION forbid_mutation()""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Fails while an exchange demo account exists, rather than deleting its history."""
    op.execute("DROP TABLE exchange_equity_days")
    op.execute("DROP TABLE exchange_orders")
    op.execute("ALTER TABLE trading_accounts DROP CONSTRAINT trading_accounts_mode_check")
    op.execute(
        "ALTER TABLE trading_accounts ADD CONSTRAINT trading_accounts_mode_check "
        "CHECK (mode = 'paper')"
    )
