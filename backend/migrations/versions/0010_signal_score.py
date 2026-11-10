"""The signal score's conditions, stored with each recommendation as information (D046).

The score failed its pre-registered test (docs/34), so it sets no size. Recording it forward
lets live results test it on data it was never fitted on. Rows from before have no score.
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE trade_recommendations ADD COLUMN signal_score jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE trade_recommendations DROP COLUMN signal_score")
