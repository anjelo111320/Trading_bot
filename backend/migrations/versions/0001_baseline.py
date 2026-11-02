"""Shared types and the immutability function."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE DOMAIN decimal_t AS numeric(38, 18)")
    op.execute(
        """CREATE TYPE instrument_type_t AS ENUM
           ('spot', 'linear_perpetual', 'inverse_perpetual', 'forex', 'equity', 'cfd')"""
    )
    op.execute("CREATE TYPE timeframe_t AS ENUM ('1m', '5m', '15m', '30m', '1h', '4h', '1d')")
    op.execute("CREATE TYPE data_origin_t AS ENUM ('live', 'backfill', 'synthetic')")
    op.execute(
        """CREATE FUNCTION forbid_mutation() RETURNS trigger
           LANGUAGE plpgsql AS $$
           BEGIN
             RAISE EXCEPTION '% is not allowed on immutable table %', TG_OP, TG_TABLE_NAME
               USING ERRCODE = 'restrict_violation';
           END
           $$"""
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION forbid_mutation()")
    op.execute("DROP TYPE data_origin_t")
    op.execute("DROP TYPE timeframe_t")
    op.execute("DROP TYPE instrument_type_t")
    op.execute("DROP DOMAIN decimal_t")
