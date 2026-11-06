"""Four more core perpetuals, approved by the owner on 2026-11-06 (D033).

SOLUSDT, XRPUSDT, BNBUSDT and DOGEUSDT USD-M perpetuals, checked on Binance the same day:
trading, listed in 2020, and ordinary coins rather than Binance Alpha. Perpetuals only (D008).
A downgrade needs their candles removed first, because candles reference instruments.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

INSTRUMENTS = """
INSERT INTO instruments (canonical_symbol, instrument_type, base_asset, quote_asset, settle_asset)
VALUES
  ('SOLUSDT', 'linear_perpetual', 'SOL', 'USDT', 'USDT'),
  ('XRPUSDT', 'linear_perpetual', 'XRP', 'USDT', 'USDT'),
  ('BNBUSDT', 'linear_perpetual', 'BNB', 'USDT', 'USDT'),
  ('DOGEUSDT', 'linear_perpetual', 'DOGE', 'USDT', 'USDT')
"""

LISTINGS = """
INSERT INTO provider_instruments (provider_id, instrument_id, provider_symbol, capabilities)
SELECT p.id, i.id, i.canonical_symbol,
       jsonb_build_object('candles', true, 'bid_ask', true, 'funding', true,
                          'open_interest', true, 'liquidations', true)
FROM providers p JOIN instruments i
  ON i.instrument_type = 'linear_perpetual'
 AND i.canonical_symbol IN ('SOLUSDT', 'XRPUSDT', 'BNBUSDT', 'DOGEUSDT')
WHERE p.code = 'binance_usdm'
"""


def upgrade() -> None:
    op.execute(INSTRUMENTS)
    op.execute(LISTINGS)


def downgrade() -> None:
    op.execute(
        """DELETE FROM provider_instruments WHERE instrument_id IN (
             SELECT id FROM instruments WHERE instrument_type = 'linear_perpetual'
             AND canonical_symbol IN ('SOLUSDT', 'XRPUSDT', 'BNBUSDT', 'DOGEUSDT'))"""
    )
    op.execute(
        """DELETE FROM instruments WHERE instrument_type = 'linear_perpetual'
           AND canonical_symbol IN ('SOLUSDT', 'XRPUSDT', 'BNBUSDT', 'DOGEUSDT')"""
    )
