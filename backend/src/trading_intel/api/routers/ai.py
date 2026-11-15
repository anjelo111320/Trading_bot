"""Claude's exit advice (D051) and Claude's daily cost limit (D062), for the dashboard.

The quant worker and the ingestor ask Claude and store the answers and the cost. This router
reads them and never calls Claude, so viewing the page spends nothing (docs/24). The one
change it makes is the owner's daily limit, from the dashboard only, logged in the audit log.
"""

from decimal import Decimal
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query, Request

from trading_intel.ai_analyst.exit_review import MODEL
from trading_intel.api.auth import Owner
from trading_intel.api.container import Container, get_container
from trading_intel.api.schemas.ai_reviews import (
    AiBudgetUpdate,
    AiBudgetView,
    ExitReviewsView,
    ExitReviewView,
    UsageView,
)
from trading_intel.core.errors import ForbiddenError, InvalidRequestError
from trading_intel.database.repositories.news import AI_DAILY_LIMIT_CEILING
from trading_intel.domain.candles import Timeframe
from trading_intel.domain.events import plain

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

Services = Annotated[Container, Depends(get_container)]


def _r(value: Decimal | None) -> str | None:
    return None if value is None else plain(value.quantize(Decimal("0.001")))


@router.get("/exit-reviews", response_model=ExitReviewsView)
async def exit_reviews(
    _owner: Owner, services: Services, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> ExitReviewsView:
    summary = await services.ai_reviews.summary()
    rows = await services.ai_reviews.recent(limit)
    return ExitReviewsView(
        model=MODEL,
        asking=bool(services.settings.anthropic_api_key.get_secret_value()),
        statuses=summary["statuses"],
        cost_usd=plain(Decimal(summary["cost"]).quantize(Decimal("0.0001"))),
        scored=summary["scored"],
        scored_not_hold=summary["acted"],
        mean_change_r=_r(summary["change"]),
        reviews=[
            ExitReviewView(
                close_time=row["close_time"],
                symbol=row["symbol"],
                strategy=row["strategy"],
                account=row["account"],
                checks=list(row["checks"]),
                status=row["status"],
                action=row["action"],
                reason=row["reason"],
                progress_r=_r(row["progress_r"]) or "0",
                model=row["model"],
                tokens=row["input_tokens"] + row["output_tokens"],
                cost_usd=plain(Decimal(row["cost_usd"]).normalize()),
                own_r=_r(row["own_r"]),
                advised_r=_r(row["advised_r"]),
            )
            for row in rows
        ],
    )


CENTS: Final = Decimal("0.0001")


def _usd(value: Decimal) -> str:
    return plain(value.quantize(CENTS).normalize())


async def _budget(services: Container) -> AiBudgetView:
    limit, changed_at = await services.news.daily_limit()
    today = await services.news.usage_since(Timeframe.D1.floor(services.clock.now()))
    spent = sum((item.cost_usd for item in today), Decimal(0))
    return AiBudgetView(
        daily_limit_usd=_usd(limit),
        ceiling_usd=_usd(AI_DAILY_LIMIT_CEILING),
        changed_at=changed_at,
        spent_today_usd=_usd(spent),
        calls_today=sum(item.calls for item in today),
        input_tokens_today=sum(item.input_tokens for item in today),
        output_tokens_today=sum(item.output_tokens for item in today),
        reached=spent >= limit,
        by_purpose=[
            UsageView(
                purpose=item.purpose,
                calls=item.calls,
                input_tokens=item.input_tokens,
                output_tokens=item.output_tokens,
                cost_usd=_usd(item.cost_usd),
            )
            for item in today
        ],
    )


@router.get("/budget", response_model=AiBudgetView)
async def budget(_owner: Owner, services: Services) -> AiBudgetView:
    """Claude's daily cost limit, for every call together, and today's spend against it."""
    return await _budget(services)


@router.put("/budget", response_model=AiBudgetView)
async def change_budget(
    owner: Owner, services: Services, body: AiBudgetUpdate, request: Request
) -> AiBudgetView:
    """A new daily limit, used from Claude's next call. Only the dashboard's own origin may set
    it, never above the ceiling; zero stops every call."""
    if request.headers.get("origin") not in services.settings.cors_origins:
        raise ForbiddenError("Claude's limit can be changed only from the dashboard.")
    if not Decimal(0) <= body.daily_limit_usd <= AI_DAILY_LIMIT_CEILING:
        raise InvalidRequestError(
            f"Claude's daily limit must be from $0 to ${plain(AI_DAILY_LIMIT_CEILING)}."
        )
    before, _ = await services.news.daily_limit()
    await services.news.set_daily_limit(body.daily_limit_usd, owner.email)
    await services.audit.record(
        owner.email,
        "ai_daily_limit_changed",
        "ai_budget",
        after={"daily_limit_usd": str(body.daily_limit_usd), "before": str(before)},
        request_id=getattr(request.state, "request_id", None),
    )
    return await _budget(services)
