"""Real money on the owner's Binance USDⓈ-M futures wallet (D060), and closes from the dashboard.

- An `exchange_live` account mode, beside paper and demo trading.
- `exchange_trade_ends`: when the bot saw each of its trades end. On the real account, a
  position on a coin without an open trade of the bot's is the owner's own, never the bot's.
- `exchange_close_requests`: the owner's closes from the dashboard. The quant worker carries
  them out, because the API never holds a key. A request is finished once, then kept.
- `exchange_arming`: whether the real account may open trades, set only from the terminal.
- `exchange_transfers`: USDT the owner moved into or out of the futures wallet, so a transfer
  is never counted as a profit or a loss.

Every table is append-only but the close request's outcome, which is written once.
"""

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

STATEMENTS = (
    "ALTER TABLE trading_accounts DROP CONSTRAINT trading_accounts_mode_check",
    """ALTER TABLE trading_accounts ADD CONSTRAINT trading_accounts_mode_check
       CHECK (mode IN ('paper', 'exchange_demo', 'exchange_live'))""",
    """CREATE TABLE exchange_trade_ends (
         account_id  uuid NOT NULL REFERENCES trading_accounts,
         trade_key   text NOT NULL,
         symbol      text NOT NULL,
         how         text NOT NULL CHECK (how IN ('flat_on_binance', 'closed_from_dashboard')),
         ended_at    timestamptz NOT NULL DEFAULT now(),
         PRIMARY KEY (account_id, trade_key)
       )""",
    """CREATE TABLE exchange_close_requests (
         id            uuid PRIMARY KEY DEFAULT uuidv7(),
         account_id    uuid NOT NULL REFERENCES trading_accounts,
         symbol        text NOT NULL CHECK (symbol ~ '^[A-Z0-9]{2,30}$'),
         requested_by  text NOT NULL,
         requested_at  timestamptz NOT NULL DEFAULT now(),
         done_at       timestamptz,
         outcome       text
                       CHECK (outcome IN ('closed', 'nothing_open', 'not_the_bots', 'failed')),
         detail        text,
         CHECK ((done_at IS NULL) = (outcome IS NULL))
       )""",
    """CREATE UNIQUE INDEX exchange_close_requests_one_waiting
       ON exchange_close_requests (account_id, symbol) WHERE done_at IS NULL""",
    """CREATE TABLE exchange_arming (
         id          uuid PRIMARY KEY DEFAULT uuidv7(),
         account_id  uuid NOT NULL REFERENCES trading_accounts,
         armed       boolean NOT NULL,
         changed_by  text NOT NULL,
         note        text,
         created_at  timestamptz NOT NULL DEFAULT now()
       )""",
    "CREATE INDEX exchange_arming_latest ON exchange_arming (account_id, created_at)",
    """CREATE TABLE exchange_transfers (
         account_id  uuid NOT NULL REFERENCES trading_accounts,
         tran_id     bigint NOT NULL,
         amount      decimal_t NOT NULL,
         asset       text NOT NULL,
         moved_at    timestamptz NOT NULL,
         PRIMARY KEY (account_id, tran_id)
       )""",
    """GRANT SELECT ON exchange_trade_ends, exchange_close_requests, exchange_arming,
       exchange_transfers TO ati_readonly, ati_ingest, ati_app""",
    """GRANT INSERT ON exchange_trade_ends, exchange_close_requests, exchange_arming,
       exchange_transfers TO ati_app""",
    "GRANT UPDATE (done_at, outcome, detail) ON exchange_close_requests TO ati_app",
    """CREATE TRIGGER exchange_trade_ends_no_mutation BEFORE UPDATE OR DELETE
       ON exchange_trade_ends FOR EACH ROW EXECUTE FUNCTION forbid_mutation()""",
    """CREATE TRIGGER exchange_arming_no_mutation BEFORE UPDATE OR DELETE ON exchange_arming
       FOR EACH ROW EXECUTE FUNCTION forbid_mutation()""",
    """CREATE TRIGGER exchange_transfers_no_mutation BEFORE UPDATE OR DELETE
       ON exchange_transfers FOR EACH ROW EXECUTE FUNCTION forbid_mutation()""",
    """CREATE TRIGGER exchange_close_requests_finished_once BEFORE UPDATE
       ON exchange_close_requests FOR EACH ROW WHEN (OLD.done_at IS NOT NULL)
       EXECUTE FUNCTION forbid_mutation()""",
    """CREATE TRIGGER exchange_close_requests_no_delete BEFORE DELETE ON exchange_close_requests
       FOR EACH ROW EXECUTE FUNCTION forbid_mutation()""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Fails while a real account exists, rather than deleting its history."""
    for table in (
        "exchange_transfers",
        "exchange_arming",
        "exchange_close_requests",
        "exchange_trade_ends",
    ):
        op.execute(f"DROP TABLE {table}")
    op.execute("ALTER TABLE trading_accounts DROP CONSTRAINT trading_accounts_mode_check")
    op.execute(
        "ALTER TABLE trading_accounts ADD CONSTRAINT trading_accounts_mode_check "
        "CHECK (mode IN ('paper', 'exchange_demo'))"
    )
