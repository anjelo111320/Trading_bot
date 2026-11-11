"""Claude's exit advice on open paper trades, in shadow mode (D051).

One row per trade and 15M close where a check fired. It keeps exactly what Claude was shown
and its answer, or why it was not asked, and later the score: the trade's R with its own
exits and with the advice applied. Nothing here changes a trade.
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

STATEMENTS = (
    """CREATE TABLE ai_exit_reviews (
         id                 uuid PRIMARY KEY DEFAULT uuidv7(),
         position_id        uuid NOT NULL REFERENCES paper_positions,
         account_id         uuid NOT NULL REFERENCES trading_accounts,
         symbol             text NOT NULL,
         strategy           text NOT NULL,
         close_time         timestamptz NOT NULL,
         checks             text[] NOT NULL,
         targets_hit        integer NOT NULL CHECK (targets_hit >= 0),
         best_at            timestamptz,
         price              decimal_t NOT NULL,
         progress_r         numeric(12, 4) NOT NULL,
         facts              text NOT NULL,
         status             text NOT NULL CHECK (status IN ('advised', 'invalid', 'refused',
                              'error', 'not_asked', 'skipped_budget')),
         prompt_version_id  uuid REFERENCES prompt_versions,
         model              text,
         action             text CHECK (action IN ('hold', 'take_profit_now',
                              'stop_to_breakeven')),
         reason             text,
         input_tokens       integer NOT NULL DEFAULT 0,
         output_tokens      integer NOT NULL DEFAULT 0,
         cost_usd           numeric(18, 8) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
         reply              text,
         asked_at           timestamptz NOT NULL DEFAULT now(),
         own_r              numeric(12, 6),
         advised_r          numeric(12, 6),
         scored_at          timestamptz,
         UNIQUE (position_id, close_time),
         CHECK ((status = 'advised') = (action IS NOT NULL))
       )""",
    "CREATE INDEX ai_exit_reviews_unscored_idx ON ai_exit_reviews (position_id) "
    "WHERE scored_at IS NULL",
    "GRANT SELECT ON ai_exit_reviews TO ati_readonly, ati_ingest, ati_app",
    "GRANT INSERT, UPDATE ON ai_exit_reviews TO ati_app",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE ai_exit_reviews")
