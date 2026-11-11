"""Two news sources chosen by the owner on 2026-11-11 (D032).

Finnhub's crypto news, a licensed API on the owner's free personal key, and Binance's official
announcement stream, on a read-only key from the owner's account. Both stay off until their
key is set. The crypto publishers' RSS feeds were refused that day: CoinDesk, Cointelegraph,
The Block, Decrypt and CryptoSlate each forbid automated collection or AI processing of their
content (docs/providers/crypto-news.md). A downgrade needs these providers' articles removed
first, because articles reference their source.
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

STATEMENTS = (
    """INSERT INTO providers (code, name, kind, terms_url, terms_version, terms_reviewed_at,
         delete_on_termination, notes) VALUES
      ('finnhub', 'Finnhub', 'news', 'https://finnhub.io/terms-of-service', 'read 2026-11-11',
       '2026-11-11', true,
       'Free personal plan: personal use only, never redistributed, deleted if the subscription ends. Crypto news only. Article pages are never fetched'),
      ('binance_announcements', 'Binance announcements', 'news',
       'https://developers.binance.com/docs/cms/announcement', 'documented API, read 2026-11-11',
       '2026-11-11', false,
       'Official CMS WebSocket, topic com_announcement_en, on a read-only key from the owner''s account. Announcements missed while offline are not resent')""",
    """INSERT INTO news_sources (provider_id, name, domain, credibility_tier)
       SELECT id, 'Finnhub crypto news', 'finnhub.io', 'aggregator'
       FROM providers WHERE code = 'finnhub'""",
    """INSERT INTO news_sources (provider_id, name, domain, credibility_tier)
       SELECT id, 'Binance announcements', 'binance.com', 'official'
       FROM providers WHERE code = 'binance_announcements'""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        """DELETE FROM news_sources WHERE provider_id IN (
             SELECT id FROM providers WHERE code IN ('finnhub', 'binance_announcements'))"""
    )
    op.execute("DELETE FROM providers WHERE code IN ('finnhub', 'binance_announcements')")
