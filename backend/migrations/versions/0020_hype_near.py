"""Two more coins, chosen by the owner on 2026-11-12 (D059): HYPEUSDT and NEARUSDT perpetuals.

Both passed the D033 screen on Binance's public data that day: trading, listed in 2025 and
2020, not tagged Alpha, a 30-day median of 526M and 550M USDT a day, and listed on Binance
spot. That makes ten coins; the owner lifted D033's limit of eight for more chances to trade.
Perpetuals only (D008). A downgrade needs their candles removed first.
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

INSTRUMENTS = """
INSERT INTO instruments (canonical_symbol, instrument_type, base_asset, quote_asset, settle_asset)
VALUES
  ('HYPEUSDT', 'linear_perpetual', 'HYPE', 'USDT', 'USDT'),
  ('NEARUSDT', 'linear_perpetual', 'NEAR', 'USDT', 'USDT')
"""

LISTINGS = """
INSERT INTO provider_instruments (provider_id, instrument_id, provider_symbol, capabilities)
SELECT p.id, i.id, i.canonical_symbol,
       jsonb_build_object('candles', true, 'bid_ask', true, 'funding', true,
                          'open_interest', true, 'liquidations', true)
FROM providers p JOIN instruments i
  ON i.instrument_type = 'linear_perpetual'
 AND i.canonical_symbol IN ('HYPEUSDT', 'NEARUSDT')
WHERE p.code = 'binance_usdm'
"""


def upgrade() -> None:
    op.execute(INSTRUMENTS)
    op.execute(LISTINGS)


def downgrade() -> None:
    op.execute(
        """DELETE FROM provider_instruments WHERE instrument_id IN (
             SELECT id FROM instruments WHERE instrument_type = 'linear_perpetual'
             AND canonical_symbol IN ('HYPEUSDT', 'NEARUSDT'))"""
    )
    op.execute(
        """DELETE FROM instruments WHERE instrument_type = 'linear_perpetual'
           AND canonical_symbol IN ('HYPEUSDT', 'NEARUSDT')"""
    )
