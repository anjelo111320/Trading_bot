"""Classifications, usage tracking and dated model prices."""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

PRICES_URL = "https://platform.claude.com/docs/en/about-claude/pricing"

STATEMENTS = (
    """CREATE TABLE news_article_instruments (
      article_id       uuid NOT NULL REFERENCES news_articles ON DELETE CASCADE,
      instrument_id    integer NOT NULL REFERENCES instruments,
      relevance_score  numeric(4, 3) NOT NULL CHECK (relevance_score BETWEEN 0 AND 1),
      PRIMARY KEY (article_id, instrument_id)
    )""",
    """CREATE TABLE economic_events (
      id             uuid PRIMARY KEY DEFAULT uuidv7(),
      provider_id    smallint NOT NULL REFERENCES providers,
      title          text NOT NULL,
      category       text NOT NULL,
      country        text,
      importance     text NOT NULL CHECK (importance IN ('low', 'medium', 'high')),
      scheduled_at   timestamptz NOT NULL,
      forecast       text,
      previous       text,
      actual         text,
      first_seen_at  timestamptz NOT NULL,
      UNIQUE (provider_id, title, scheduled_at)
    )""",
    "CREATE INDEX economic_events_upcoming_idx ON economic_events (scheduled_at)",
    """CREATE TABLE prompt_versions (
      id                     uuid PRIMARY KEY DEFAULT uuidv7(),
      name                   text NOT NULL,
      version                integer NOT NULL CHECK (version > 0),
      sha256                 text NOT NULL,
      body                   text NOT NULL,
      output_schema_version  integer NOT NULL,
      created_at             timestamptz NOT NULL DEFAULT now(),
      UNIQUE (name, version)
    )""",
    """CREATE TABLE news_classifications (
      id                 uuid PRIMARY KEY DEFAULT uuidv7(),
      article_id         uuid NOT NULL REFERENCES news_articles ON DELETE CASCADE,
      prompt_version_id  uuid NOT NULL REFERENCES prompt_versions,
      model              text NOT NULL,
      event_type         text NOT NULL,
      sentiment          text NOT NULL CHECK (sentiment IN ('bullish', 'bearish', 'neutral')),
      potential_impact   text NOT NULL CHECK (potential_impact IN ('low', 'medium', 'high')),
      certainty          text NOT NULL CHECK (certainty IN ('confirmed', 'reported', 'speculation')),
      possibly_misleading boolean NOT NULL DEFAULT false,
      ai_summary         text NOT NULL,
      classified_at      timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX news_classifications_article_idx ON news_classifications (article_id, classified_at DESC)",
    """CREATE TABLE ai_model_prices (
      id                      uuid PRIMARY KEY DEFAULT uuidv7(),
      model                   text NOT NULL,
      input_per_mtok          numeric(12, 6) NOT NULL CHECK (input_per_mtok >= 0),
      output_per_mtok         numeric(12, 6) NOT NULL CHECK (output_per_mtok >= 0),
      cache_read_per_mtok     numeric(12, 6) NOT NULL CHECK (cache_read_per_mtok >= 0),
      cache_write_5m_per_mtok numeric(12, 6) NOT NULL CHECK (cache_write_5m_per_mtok >= 0),
      cache_write_1h_per_mtok numeric(12, 6) NOT NULL CHECK (cache_write_1h_per_mtok >= 0),
      batch_multiplier        numeric(4, 3) NOT NULL DEFAULT 0.5 CHECK (batch_multiplier > 0 AND batch_multiplier <= 1),
      effective_from          timestamptz NOT NULL,
      source_url              text NOT NULL,
      UNIQUE (model, effective_from)
    )""",
    """CREATE TABLE api_usage (
      id                     uuid PRIMARY KEY DEFAULT uuidv7(),
      provider_id            smallint NOT NULL REFERENCES providers,
      purpose                text NOT NULL,
      route                  text,
      model                  text,
      analysis_id            uuid,
      request_count          integer NOT NULL DEFAULT 1,
      input_tokens           bigint NOT NULL DEFAULT 0,
      output_tokens          bigint NOT NULL DEFAULT 0,
      thinking_tokens        bigint NOT NULL DEFAULT 0,
      cache_read_tokens      bigint NOT NULL DEFAULT 0,
      cache_write_5m_tokens  bigint NOT NULL DEFAULT 0,
      cache_write_1h_tokens  bigint NOT NULL DEFAULT 0,
      is_batch               boolean NOT NULL DEFAULT false,
      latency_ms             integer,
      cost_usd               numeric(18, 8) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
      occurred_at            timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX api_usage_day_idx ON api_usage (provider_id, occurred_at DESC)",
    "INSERT INTO providers (code, name, kind, terms_url, terms_reviewed_at) VALUES ('anthropic', 'Anthropic', 'ai', 'https://www.anthropic.com/legal/commercial-terms', '2026-11-02')",
    f"""INSERT INTO ai_model_prices (model, input_per_mtok, output_per_mtok, cache_read_per_mtok,
          cache_write_5m_per_mtok, cache_write_1h_per_mtok, effective_from, source_url) VALUES
        ('claude-opus-5-5', 4, 20, 0.20, 5, 8, '2026-11-02T00:00:00Z', '{PRICES_URL}'),
        ('claude-sonnet-5-5', 2, 10, 0.10, 2.50, 4, '2026-11-02T00:00:00Z', '{PRICES_URL}'),
        ('claude-haiku-5-5', 0.10, 0.50, 0.01, 0.125, 0.20, '2026-11-02T00:00:00Z', '{PRICES_URL}')""",
    """REVOKE ALL ON news_article_instruments, economic_events, prompt_versions,
         news_classifications, ai_model_prices, api_usage FROM PUBLIC""",
    """GRANT SELECT ON news_article_instruments, economic_events, prompt_versions,
         news_classifications, ai_model_prices, api_usage TO ati_readonly, ati_ingest, ati_app""",
    """GRANT INSERT ON news_article_instruments, economic_events, prompt_versions,
         news_classifications, api_usage TO ati_app""",
    "GRANT UPDATE (cluster_id) ON news_articles TO ati_app",
    "GRANT DELETE ON news_article_instruments TO ati_app",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in (
        "api_usage",
        "ai_model_prices",
        "news_classifications",
        "prompt_versions",
        "economic_events",
        "news_article_instruments",
    ):
        op.execute(f"DROP TABLE {table}")
    op.execute("DELETE FROM providers WHERE code = 'anthropic'")
