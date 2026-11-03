"""Backtest reports. Results are labelled as simulated, with their limits stated."""

from trading_intel.backtesting.engine import BacktestResult
from trading_intel.backtesting.metrics import Metrics

STATEMENT = "Simulated results. A profitable backtest is not proof of future profitability."


def _value(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def metrics_table(metrics: Metrics) -> list[str]:
    interval = metrics.expectancy_interval
    return [
        "| Metric | Value |",
        "|---|---|",
        f"| Trades | {metrics.trades} |",
        f"| Net P/L after costs | {metrics.net_pnl:.2f} |",
        f"| Total return | {metrics.total_return:.2%} |",
        f"| Win rate | {_value(metrics.win_rate)} |",
        f"| Expectancy (R) | {_value(metrics.expectancy_r)} |",
        f"| 95% interval for expectancy | {_value(interval[0]) if interval else 'n/a'} to "
        f"{_value(interval[1]) if interval else 'n/a'} |",
        f"| Profit factor | {_value(metrics.profit_factor)} |",
        f"| Maximum drawdown | {metrics.max_drawdown:.2%} |",
        f"| Sharpe (daily, 365 days, no risk-free rate) | {_value(metrics.sharpe)} |",
        f"| Sortino | {_value(metrics.sortino)} |",
        f"| Cost share of gross profit | {_value(metrics.cost_share)} |",
    ]


def render(title: str, result: BacktestResult, notes: list[str]) -> str:
    assert result.metrics is not None
    lines = [f"# {title}", "", STATEMENT, ""]
    lines += metrics_table(result.metrics)
    lines += [
        "",
        f"Decisions checked: {result.decisions}. Signals: {result.signals}. "
        f"Filled and finished: {len(result.trades)}.",
        "",
    ]
    if result.rejections:
        lines += ["Risk engine rejections:", ""]
        lines += [f"- {code.value}: {count}" for code, count in sorted(result.rejections.items())]
        lines.append("")
    lines += [f"- {note}" for note in notes]
    return "\n".join(lines) + "\n"
