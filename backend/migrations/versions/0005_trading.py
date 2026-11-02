"""Accounts, recommendations, risk records, paper trading and backtests."""

from pathlib import Path

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

SQL = (Path(__file__).parent / "sql" / "0005_trading.sql").read_text()

IMMUTABLE = (
    "risk_profiles",
    "trade_recommendations",
    "trade_targets",
    "recommendation_revisions",
    "risk_assessments",
    "signal_events",
    "paper_executions",
    "trade_outcomes",
)

TABLES = (
    "backtest_equity_points",
    "backtest_trades",
    "backtest_runs",
    "dataset_versions",
    "trade_outcomes",
    "paper_executions",
    "paper_positions",
    "alerts",
    "signal_current_state",
    "signal_events",
    "risk_assessments",
    "recommendation_revisions",
    "trade_targets",
    "trade_recommendations",
    "calibration_models",
    "strategy_configurations",
    "fee_schedules",
    "timeframe_profiles",
    "risk_profiles",
    "trading_accounts",
)

TYPES = (
    "backtest_split_t",
    "outcome_t",
    "signal_state_t",
    "side_t",
    "entry_type_t",
    "action_t",
)


def upgrade() -> None:
    for statement in SQL.split(";\n"):
        if statement.strip():
            op.execute(statement)
    for table in IMMUTABLE:
        op.execute(
            f"""CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION forbid_mutation()"""
        )
        op.execute(
            f"""CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()"""
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE {table}")
    for name in TYPES:
        op.execute(f"DROP TYPE {name}")
