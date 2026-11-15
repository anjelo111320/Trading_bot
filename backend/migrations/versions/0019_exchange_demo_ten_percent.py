"""The owner's Binance demo limits of 2026-11-12 (D058): 10% risk per trade, positions within 80%.

A new risk profile version for the Binance demo account:
- 10% risk per trade, at most 10% across open trades, and a 10% daily loss limit;
- all positions together within 80% of equity;
- every other limit copied from the version before, including the 20% loss stop.

The risk engine's per-trade and daily loss ceilings were raised to 10% in code for this. A
fresh database has no such account yet; the code creates it with the same limits on first use.
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

NEW_VERSION = """
INSERT INTO risk_profiles (account_id, version, max_risk_fraction, min_reward_risk,
  countertrend_extra_rr, max_daily_loss_fraction, max_open_positions,
  max_total_exposure_fraction, max_leverage, max_spread_bps, max_data_age_seconds, settings,
  created_by)
SELECT r.account_id, r.version + 1, {risk}, r.min_reward_risk, r.countertrend_extra_rr,
       {daily}, r.max_open_positions, {exposure}, r.max_leverage, r.max_spread_bps,
       r.max_data_age_seconds, r.settings || {settings}, a.user_id
FROM risk_profiles r JOIN trading_accounts a ON a.id = r.account_id
WHERE a.name = 'Binance demo' AND a.mode = 'exchange_demo'
  AND r.version = (SELECT max(version) FROM risk_profiles WHERE account_id = a.id)
"""


def upgrade() -> None:
    op.execute(
        NEW_VERSION.format(
            risk="0.10",
            daily="0.10",
            exposure="0.8",
            settings="""'{"max_open_risk_fraction": "0.10", "loss_stop_from_high": "False"}'::jsonb""",
        )
    )


def downgrade() -> None:
    """Profiles are append-only, so D053's limits come back as a further version."""
    op.execute(
        NEW_VERSION.format(
            risk="0.02",
            daily="0.03",
            exposure="3",
            settings="""'{"max_open_risk_fraction": "0.03"}'::jsonb""",
        )
    )
