"""Claude's exit advice for the dashboard (D051). Read-only.

The quant worker asks Claude and stores the answers. This router only reads them, and never
calls Claude, so viewing the page spends nothing (docs/24).
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from trading_intel.ai_analyst.exit_review import MODEL
from trading_intel.api.auth import Owner
from trading_intel.api.container import Container, get_container
from trading_intel.api.schemas.ai_reviews import ExitReviewsView, ExitReviewView
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
