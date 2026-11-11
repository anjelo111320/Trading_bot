"""Two trending perpetuals, chosen by the owner on 2026-11-11 (D033).

ZECUSDT and 1000PEPEUSDT USD-M perpetuals passed the D033 screen on Binance that day: trading,
listed in 2020 and 2023, not tagged Alpha, a 30-day median of 1,762M and 297M USDT a day, and
listed on Binance spot. Perpetuals only (D008). 1000PEPE is Binance's own base asset: one
contract unit is 1,000 PEPE. A downgrade needs their candles removed first, because candles
reference instruments.
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

INSTRUMENTS = """
INSERT INTO instruments (canonical_symbol, instrument_type, base_asset, quote_asset, settle_asset)
VALUES
  ('ZECUSDT', 'linear_perpetual', 'ZEC', 'USDT', 'USDT'),
  ('1000PEPEUSDT', 'linear_perpetual', '1000PEPE', 'USDT', 'USDT')
"""

LISTINGS = """
INSERT INTO provider_instruments (provider_id, instrument_id, provider_symbol, capabilities)
SELECT p.id, i.id, i.canonical_symbol,
       jsonb_build_object('candles', true, 'bid_ask', true, 'funding', true,
                          'open_interest', true, 'liquidations', true)
FROM providers p JOIN instruments i
  ON i.instrument_type = 'linear_perpetual'
 AND i.canonical_symbol IN ('ZECUSDT', '1000PEPEUSDT')
WHERE p.code = 'binance_usdm'
"""


def upgrade() -> None:
    op.execute(INSTRUMENTS)
    op.execute(LISTINGS)


def downgrade() -> None:
    op.execute(
        """DELETE FROM provider_instruments WHERE instrument_id IN (
             SELECT id FROM instruments WHERE instrument_type = 'linear_perpetual'
             AND canonical_symbol IN ('ZECUSDT', '1000PEPEUSDT'))"""
    )
    op.execute(
        """DELETE FROM instruments WHERE instrument_type = 'linear_perpetual'
           AND canonical_symbol IN ('ZECUSDT', '1000PEPEUSDT')"""
    )
