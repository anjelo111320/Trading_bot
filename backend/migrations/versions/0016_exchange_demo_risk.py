"""The owner's limits for Binance demo trading, chosen on 2026-11-11 (D053), and its loss stop.

The Binance demo account gets a new risk profile version: 2% risk per trade, positions up to
3 times its budget, and a loss stop at 20% below its starting budget. Every other limit is
copied from the version before. A fresh database has no such account yet; the code creates
it with the same limits on first use.

A reached loss stop is kept, append-only, against the profile version it was reached under,
so only a new version, the owner's next decision, lets the account trade again.
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

NEW_VERSION = """
INSERT INTO risk_profiles (account_id, version, max_risk_fraction, min_reward_risk,
  countertrend_extra_rr, max_daily_loss_fraction, max_open_positions,
  max_total_exposure_fraction, max_leverage, max_spread_bps, max_data_age_seconds, settings,
  created_by)
SELECT r.account_id, r.version + 1, {risk}, r.min_reward_risk, r.countertrend_extra_rr,
       r.max_daily_loss_fraction, r.max_open_positions, {exposure}, r.max_leverage,
       r.max_spread_bps, r.max_data_age_seconds, {settings}, a.user_id
FROM risk_profiles r JOIN trading_accounts a ON a.id = r.account_id
WHERE a.name = 'Binance demo' AND a.mode = 'exchange_demo'
  AND r.version = (SELECT max(version) FROM risk_profiles WHERE account_id = a.id)
"""

STATEMENTS = (
    NEW_VERSION.format(
        risk="0.02",
        exposure="3",
        settings="""r.settings || '{"max_total_loss_fraction": "0.2"}'::jsonb""",
    ),
    """CREATE TABLE exchange_loss_stops (
         account_id       uuid NOT NULL REFERENCES trading_accounts,
         risk_profile_id  uuid NOT NULL REFERENCES risk_profiles,
         equity           decimal_t NOT NULL,
         floor            decimal_t NOT NULL CHECK (floor > 0),
         reached_at       timestamptz NOT NULL,
         PRIMARY KEY (account_id, risk_profile_id)
       )""",
    "GRANT SELECT ON exchange_loss_stops TO ati_readonly, ati_ingest, ati_app",
    "GRANT INSERT ON exchange_loss_stops TO ati_app",
    """CREATE TRIGGER exchange_loss_stops_no_mutation BEFORE UPDATE OR DELETE
       ON exchange_loss_stops FOR EACH ROW EXECUTE FUNCTION forbid_mutation()""",
    """CREATE TRIGGER exchange_loss_stops_no_truncate BEFORE TRUNCATE ON exchange_loss_stops
       FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Profiles are append-only, so the old limits come back as a further version."""
    op.execute("DROP TABLE exchange_loss_stops")
    op.execute(
        NEW_VERSION.format(
            risk="0.01", exposure="1", settings="r.settings - 'max_total_loss_fraction'"
        )
    )
