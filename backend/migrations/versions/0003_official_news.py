"""Timestamped news archive. It cannot be created later, so collection starts early."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

STATEMENTS = (
    """CREATE TABLE news_sources (
      id                integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      provider_id       smallint NOT NULL REFERENCES providers,
      name              text NOT NULL,
      domain            text,
      credibility_tier  text NOT NULL CHECK (credibility_tier IN ('official', 'primary_media', 'aggregator', 'social', 'unknown')),
      UNIQUE (provider_id, name)
    )""",
    """CREATE TABLE news_articles (
      id             uuid PRIMARY KEY DEFAULT uuidv7(),
      provider_id    smallint NOT NULL REFERENCES providers,
      source_id      integer REFERENCES news_sources,
      external_id    text,
      headline       text NOT NULL,
      url            text NOT NULL,
      snippet        text,
      published_at   timestamptz NOT NULL,
      event_time     timestamptz,
      retrieved_at   timestamptz NOT NULL,
      first_seen_at  timestamptz NOT NULL,
      content_hash   text NOT NULL,
      cluster_id     uuid,
      retain_until   timestamptz,
      raw            jsonb,
      UNIQUE (provider_id, url)
    )""",
    "CREATE INDEX news_articles_published_idx ON news_articles (published_at DESC)",
    "CREATE INDEX news_articles_cluster_idx ON news_articles (cluster_id)",
    "CREATE INDEX news_articles_hash_idx ON news_articles (content_hash)",
    """INSERT INTO providers (code, name, kind, terms_url, terms_version, terms_reviewed_at, notes) VALUES
      ('federal_reserve', 'Federal Reserve Board', 'news', 'https://www.federalreserve.gov/disclaimer.htm',
       'read 2026-11-02', '2026-11-02', 'Public RSS feeds only. Article pages are never fetched')""",
    """INSERT INTO news_sources (provider_id, name, domain, credibility_tier)
       SELECT id, 'Federal Reserve Board', 'federalreserve.gov', 'official'
       FROM providers WHERE code = 'federal_reserve'""",
    "REVOKE ALL ON news_sources, news_articles FROM PUBLIC",
    "GRANT SELECT ON news_sources, news_articles TO ati_readonly, ati_ingest, ati_app",
    "GRANT INSERT ON news_articles TO ati_ingest",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE news_articles")
    op.execute("DROP TABLE news_sources")
    op.execute("DELETE FROM providers WHERE code = 'federal_reserve'")
