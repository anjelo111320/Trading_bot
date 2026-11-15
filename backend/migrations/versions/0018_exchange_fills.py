"""Binance demo's own fills and funding, kept for the Bot page's results (D057).

Binance keeps them for 3 months, so the quant worker copies them here as they happen. Both are
append-only, keyed by Binance's own IDs, so a repeated copy changes nothing.
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

STATEMENTS = (
    """CREATE TABLE exchange_fills (
         account_id        uuid NOT NULL REFERENCES trading_accounts,
         symbol            text NOT NULL,
         trade_id          bigint NOT NULL,
         order_id          bigint NOT NULL,
         side              text NOT NULL CHECK (side IN ('BUY', 'SELL')),
         price             decimal_t NOT NULL CHECK (price > 0),
         quantity          decimal_t NOT NULL CHECK (quantity > 0),
         realized_pnl      decimal_t NOT NULL,
         commission        decimal_t NOT NULL,
         commission_asset  text NOT NULL,
         maker             boolean NOT NULL,
         filled_at         timestamptz NOT NULL,
         raw               jsonb NOT NULL,
         PRIMARY KEY (account_id, symbol, trade_id)
       )""",
    "CREATE INDEX exchange_fills_time ON exchange_fills (account_id, filled_at)",
    """CREATE TABLE exchange_funding (
         account_id  uuid NOT NULL REFERENCES trading_accounts,
         tran_id     bigint NOT NULL,
         symbol      text NOT NULL,
         amount      decimal_t NOT NULL,
         asset       text NOT NULL,
         paid_at     timestamptz NOT NULL,
         PRIMARY KEY (account_id, tran_id)
       )""",
    "GRANT SELECT ON exchange_fills, exchange_funding TO ati_readonly, ati_ingest, ati_app",
    "GRANT INSERT ON exchange_fills, exchange_funding TO ati_app",
    """CREATE TRIGGER exchange_fills_no_mutation BEFORE UPDATE OR DELETE ON exchange_fills
       FOR EACH ROW EXECUTE FUNCTION forbid_mutation()""",
    """CREATE TRIGGER exchange_fills_no_truncate BEFORE TRUNCATE ON exchange_fills
       FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()""",
    """CREATE TRIGGER exchange_funding_no_mutation BEFORE UPDATE OR DELETE ON exchange_funding
       FOR EACH ROW EXECUTE FUNCTION forbid_mutation()""",
    """CREATE TRIGGER exchange_funding_no_truncate BEFORE TRUNCATE ON exchange_funding
       FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE exchange_funding")
    op.execute("DROP TABLE exchange_fills")
