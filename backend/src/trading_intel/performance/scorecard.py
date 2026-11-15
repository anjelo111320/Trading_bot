"""The coin scorecard (D068): for each coin and strategy, what the backtests found, what live
trading did, and how good the entries were. Pure and deterministic, Python's numbers only.

Backtest results are copied from the published study reports, and a test checks every row
against them. A pair no study ran is untested, and says why.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Final

from trading_intel.domain.candles import ClosedCandle
from trading_intel.domain.signals import Side

ZERO: Final = Decimal(0)
FIRST_HOUR: Final = timedelta(hours=1)
# A first hour that went at least half the trade's risk against it.
AGAINST_R: Final = Decimal("0.5")

D = Decimal
REPLICATION: Final = "docs/33"
FVG_STUDY: Final = "docs/35"
NEW_COIN_STUDY: Final = "docs/42"
# The 15M rule and its copy: two years from 2023-11-01, on 15-minute fills, not their 1-minute.
RULE_STUDY: Final = "docs/42, 15-minute fills from 2023-11"


@dataclass(frozen=True)
class Evidence:
    """One strategy's backtest on one coin at normal costs, as its study published it."""

    trades: int
    mean_r: Decimal
    low: Decimal  # The seeded bootstrap 95% interval.
    high: Decimal
    source: str


# From docs/reports/coin-replication.md (the corrected run, docs/33), fvg-choch.md (docs/35) and
# new-coin-study.md (docs/42).
EVIDENCE: Final[Mapping[tuple[str, str], Evidence]] = {
    ("pattern_breakout", "BTCUSDT"): Evidence(162, D("0.136"), D("-0.13"), D("0.42"), REPLICATION),
    ("pattern_breakout", "ETHUSDT"): Evidence(176, D("0.120"), D("-0.14"), D("0.38"), REPLICATION),
    ("pattern_breakout", "SOLUSDT"): Evidence(87, D("-0.016"), D("-0.36"), D("0.36"), REPLICATION),
    ("pattern_breakout", "XRPUSDT"): Evidence(108, D("0.225"), D("-0.13"), D("0.61"), REPLICATION),
    ("pattern_breakout", "BNBUSDT"): Evidence(132, D("0.026"), D("-0.29"), D("0.33"), REPLICATION),
    ("pattern_breakout", "DOGEUSDT"): Evidence(
        125, D("-0.068"), D("-0.35"), D("0.23"), REPLICATION
    ),
    ("daily_trend", "BTCUSDT"): Evidence(71, D("0.439"), D("-0.03"), D("0.98"), REPLICATION),
    ("daily_trend", "ETHUSDT"): Evidence(68, D("0.372"), D("-0.07"), D("0.89"), REPLICATION),
    ("daily_trend", "SOLUSDT"): Evidence(37, D("0.529"), D("-0.13"), D("1.39"), REPLICATION),
    ("daily_trend", "XRPUSDT"): Evidence(52, D("0.317"), D("-0.31"), D("1.04"), REPLICATION),
    ("daily_trend", "BNBUSDT"): Evidence(60, D("0.280"), D("-0.21"), D("0.86"), REPLICATION),
    ("daily_trend", "DOGEUSDT"): Evidence(56, D("0.487"), D("-0.18"), D("1.29"), REPLICATION),
    ("fvg_choch", "BTCUSDT"): Evidence(26, D("0.547"), D("-0.12"), D("1.22"), FVG_STUDY),
    ("fvg_choch", "ETHUSDT"): Evidence(52, D("-0.132"), D("-0.52"), D("0.31"), FVG_STUDY),
    ("fvg_choch", "SOLUSDT"): Evidence(34, D("0.229"), D("-0.35"), D("0.81"), FVG_STUDY),
    ("fvg_choch", "XRPUSDT"): Evidence(41, D("-0.429"), D("-0.82"), D("0.01"), FVG_STUDY),
    ("fvg_choch", "BNBUSDT"): Evidence(40, D("0.260"), D("-0.25"), D("0.79"), FVG_STUDY),
    ("fvg_choch", "DOGEUSDT"): Evidence(62, D("-0.045"), D("-0.41"), D("0.39"), FVG_STUDY),
    ("daily_trend", "ZECUSDT"): Evidence(52, D("0.156"), D("-0.34"), D("0.79"), NEW_COIN_STUDY),
    ("daily_trend", "1000PEPEUSDT"): Evidence(
        36, D("0.360"), D("-0.35"), D("1.27"), NEW_COIN_STUDY
    ),
    ("daily_trend", "HYPEUSDT"): Evidence(6, D("-0.644"), D("-0.91"), D("-0.37"), NEW_COIN_STUDY),
    ("daily_trend", "NEARUSDT"): Evidence(32, D("-0.139"), D("-0.43"), D("0.16"), NEW_COIN_STUDY),
    ("pattern_breakout", "ZECUSDT"): Evidence(
        82, D("0.035"), D("-0.31"), D("0.41"), NEW_COIN_STUDY
    ),
    ("pattern_breakout", "1000PEPEUSDT"): Evidence(
        45, D("0.459"), D("-0.10"), D("1.10"), NEW_COIN_STUDY
    ),
    ("pattern_breakout", "HYPEUSDT"): Evidence(
        13, D("-0.786"), D("-1.05"), D("-0.28"), NEW_COIN_STUDY
    ),
    ("pattern_breakout", "NEARUSDT"): Evidence(
        67, D("-0.105"), D("-0.49"), D("0.33"), NEW_COIN_STUDY
    ),
    ("fvg_choch", "ZECUSDT"): Evidence(56, D("0.077"), D("-0.32"), D("0.50"), NEW_COIN_STUDY),
    ("fvg_choch", "1000PEPEUSDT"): Evidence(56, D("-0.185"), D("-0.57"), D("0.25"), NEW_COIN_STUDY),
    ("fvg_choch", "HYPEUSDT"): Evidence(9, D("-0.039"), D("-0.89"), D("1.05"), NEW_COIN_STUDY),
    ("fvg_choch", "NEARUSDT"): Evidence(41, D("0.478"), D("-0.08"), D("1.03"), NEW_COIN_STUDY),
    ("trend_break_baseline", "BTCUSDT"): Evidence(
        113, D("-0.013"), D("-0.32"), D("0.32"), RULE_STUDY
    ),
    ("trend_break_baseline", "ETHUSDT"): Evidence(
        170, D("-0.082"), D("-0.32"), D("0.17"), RULE_STUDY
    ),
    ("trend_break_baseline", "SOLUSDT"): Evidence(
        212, D("-0.047"), D("-0.28"), D("0.19"), RULE_STUDY
    ),
    ("trend_break_baseline", "XRPUSDT"): Evidence(
        175, D("-0.101"), D("-0.35"), D("0.15"), RULE_STUDY
    ),
    ("trend_break_baseline", "BNBUSDT"): Evidence(
        115, D("-0.190"), D("-0.46"), D("0.11"), RULE_STUDY
    ),
    ("trend_break_baseline", "DOGEUSDT"): Evidence(
        216, D("-0.038"), D("-0.25"), D("0.18"), RULE_STUDY
    ),
    ("trend_break_baseline", "ZECUSDT"): Evidence(
        84, D("0.000"), D("-0.33"), D("0.35"), RULE_STUDY
    ),
    ("trend_break_baseline", "1000PEPEUSDT"): Evidence(
        245, D("0.094"), D("-0.12"), D("0.31"), RULE_STUDY
    ),
    ("trend_break_baseline", "HYPEUSDT"): Evidence(
        58, D("-0.238"), D("-0.60"), D("0.18"), RULE_STUDY
    ),
    ("trend_break_baseline", "NEARUSDT"): Evidence(
        110, D("-0.039"), D("-0.33"), D("0.26"), RULE_STUDY
    ),
    ("trend_break_loose", "BTCUSDT"): Evidence(158, D("0.008"), D("-0.25"), D("0.27"), RULE_STUDY),
    ("trend_break_loose", "ETHUSDT"): Evidence(235, D("-0.144"), D("-0.35"), D("0.07"), RULE_STUDY),
    ("trend_break_loose", "SOLUSDT"): Evidence(290, D("-0.109"), D("-0.29"), D("0.08"), RULE_STUDY),
    ("trend_break_loose", "XRPUSDT"): Evidence(235, D("-0.091"), D("-0.29"), D("0.13"), RULE_STUDY),
    ("trend_break_loose", "BNBUSDT"): Evidence(169, D("-0.189"), D("-0.43"), D("0.06"), RULE_STUDY),
    ("trend_break_loose", "DOGEUSDT"): Evidence(
        319, D("-0.178"), D("-0.35"), D("-0.01"), RULE_STUDY
    ),
    ("trend_break_loose", "ZECUSDT"): Evidence(111, D("-0.010"), D("-0.29"), D("0.27"), RULE_STUDY),
    ("trend_break_loose", "1000PEPEUSDT"): Evidence(
        349, D("0.009"), D("-0.16"), D("0.19"), RULE_STUDY
    ),
    ("trend_break_loose", "HYPEUSDT"): Evidence(
        86, D("-0.413"), D("-0.69"), D("-0.11"), RULE_STUDY
    ),
    ("trend_break_loose", "NEARUSDT"): Evidence(
        143, D("-0.150"), D("-0.41"), D("0.13"), RULE_STUDY
    ),
}

# Why a strategy has no backtest, when no study can run it at all.
NEVER_TESTED: Final[Mapping[str, str]] = {
    "news_move": "Its price rules alone showed no edge; the news part cannot be tested on "
    "history (docs/40).",
}
NOT_ON_COIN: Final = "Not tested on this coin: it was added untested (D052, D059)."


@dataclass(frozen=True)
class EnteredTrade:
    """A trade a signal opened, on paper or on Binance. `r` is set once it closed: the net
    result over the planned risk."""

    symbol: str
    strategy: str
    side: Side
    planned_entry: Decimal
    planned_stop: Decimal
    filled: Decimal
    opened_at: datetime
    r: Decimal | None = None

    @property
    def risk(self) -> Decimal:
        """The planned risk per unit, 1R."""
        return abs(self.planned_entry - self.planned_stop)


def slippage_r(trade: EnteredTrade) -> Decimal | None:
    """How much worse than planned the entry filled, in R. Below zero, it filled better."""
    if trade.risk <= 0:
        return None
    return trade.side.sign * (trade.filled - trade.planned_entry) / trade.risk


def first_hour_r(trade: EnteredTrade, candles: Sequence[ClosedCandle]) -> Decimal | None:
    """The furthest the price went against the trade in the hour after its fill, in R, from
    1-minute candles. The fill's own minute is left out, because part of it traded before the
    fill, as in docs/37."""
    if trade.risk <= 0:
        return None
    end = trade.opened_at + FIRST_HOUR
    window = [c for c in candles if trade.opened_at <= c.open_time < end]
    if not window:
        return None
    if trade.side.sign > 0:
        move = trade.filled - min(c.low for c in window)
    else:
        move = max(c.high for c in window) - trade.filled
    return max(move, ZERO) / trade.risk


@dataclass(frozen=True)
class LiveResult:
    entered: int
    closed: int
    won: int
    mean_r: Decimal | None  # Over the closed trades.


@dataclass(frozen=True)
class EntryQuality:
    trades: int  # Entries with a full first hour of 1-minute candles.
    slippage_r: Decimal | None  # Medians.
    first_hour_r: Decimal | None
    went_against: int  # First hours that went AGAINST_R or more against the trade.


@dataclass(frozen=True)
class Scored:
    """A trade with its entry measured."""

    trade: EnteredTrade
    slippage: Decimal | None
    first_hour: Decimal | None


def live_result(scored: Collection[Scored]) -> LiveResult:
    results = [s.trade.r for s in scored if s.trade.r is not None]
    mean = sum(results, ZERO) / len(results) if results else None
    return LiveResult(len(scored), len(results), sum(1 for r in results if r > 0), mean)


def entry_quality(scored: Iterable[Scored]) -> EntryQuality:
    measured = [s for s in scored if s.first_hour is not None]
    slips = [s.slippage for s in measured if s.slippage is not None]
    hours = [s.first_hour for s in measured if s.first_hour is not None]
    return EntryQuality(
        len(measured),
        median(slips) if slips else None,
        median(hours) if hours else None,
        sum(1 for hour in hours if hour >= AGAINST_R),
    )


@dataclass(frozen=True)
class StrategyCell:
    strategy: str
    evidence: Evidence | None
    untested: str | None  # Why, when there is no evidence.
    left_out: bool  # Lost on this coin with 95% confidence, so it does not trade it.
    live: LiveResult
    entries: EntryQuality


@dataclass(frozen=True)
class CoinCard:
    symbol: str
    live: LiveResult
    entries: EntryQuality
    strategies: tuple[StrategyCell, ...]


def dedupe(trades: Iterable[EnteredTrade]) -> list[EnteredTrade]:
    """One trade per signal moment. The paper accounts and Binance can each trade the same
    setup, and counting it once per account would make one event look like several."""
    seen: dict[tuple[str, str, Side, datetime], EnteredTrade] = {}
    for trade in trades:
        minute = trade.opened_at.replace(second=0, microsecond=0)
        seen.setdefault((trade.symbol, trade.strategy, trade.side, minute), trade)
    return list(seen.values())


def cards(
    symbols: Sequence[str],
    strategies: Sequence[str],
    scored: Collection[Scored],
    left_out: Collection[tuple[str, str]],
) -> list[CoinCard]:
    """A card per coin, with a cell for every strategy, tested or not."""
    result: list[CoinCard] = []
    for symbol in symbols:
        coin = [s for s in scored if s.trade.symbol == symbol]
        cells = []
        for strategy in strategies:
            mine = [s for s in coin if s.trade.strategy == strategy]
            evidence = EVIDENCE.get((strategy, symbol))
            why = None if evidence else NEVER_TESTED.get(strategy, NOT_ON_COIN)
            cells.append(
                StrategyCell(
                    strategy,
                    evidence,
                    why,
                    (strategy, symbol) in left_out,
                    live_result(mine),
                    entry_quality(mine),
                )
            )
        result.append(CoinCard(symbol, live_result(coin), entry_quality(coin), tuple(cells)))
    return result
