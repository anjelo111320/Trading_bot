"""Chronological splits, and the frozen holdout. Time series are never shuffled."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from trading_intel.core.errors import AppError

# Frozen by D029 before any strategy research. Moving it would invalidate the holdout.
HOLDOUT_START: Final = datetime(2025, 11, 1, tzinfo=UTC)
MONTH: Final = timedelta(days=30)


class HoldoutViolationError(AppError):
    code = "holdout_violation"


def refuse_holdout(start: datetime, end: datetime, *, holdout_run: bool = False) -> None:
    """Research can never read the holdout, and a holdout run reads nothing else."""
    if holdout_run:
        if start < HOLDOUT_START:
            raise HoldoutViolationError("a holdout run must start at the holdout date")
        return
    if end > HOLDOUT_START:
        raise HoldoutViolationError(
            f"window ending {end.isoformat()} touches the frozen holdout, which starts "
            f"{HOLDOUT_START.isoformat()}"
        )


@dataclass(frozen=True)
class Fold:
    number: int
    train_start: datetime
    train_end: datetime
    validate_start: datetime
    validate_end: datetime
    test_start: datetime
    test_end: datetime


def walk_forward(
    start: datetime,
    end: datetime,
    *,
    train: timedelta = MONTH * 24,
    validate: timedelta = MONTH * 6,
    test: timedelta = MONTH * 6,
    embargo: timedelta = timedelta(days=7),
) -> list[Fold]:
    """Rolling folds, separated by an embargo, that never reach the holdout."""
    limit = min(end, HOLDOUT_START)
    folds: list[Fold] = []
    cursor = start
    while True:
        train_end = cursor + train
        validate_start = train_end + embargo
        validate_end = validate_start + validate
        test_start = validate_end + embargo
        test_end = test_start + test
        if test_end > limit:
            return folds
        folds.append(
            Fold(
                len(folds) + 1,
                cursor,
                train_end,
                validate_start,
                validate_end,
                test_start,
                test_end,
            )
        )
        cursor += test
