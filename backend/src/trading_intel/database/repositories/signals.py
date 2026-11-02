"""Paper accounts, recommendations and their immutable records."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID, uuid7

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from trading_intel.domain.candles import Timeframe
from trading_intel.domain.signals import Action, Side, SignalState
from trading_intel.risk_management.models import (
    FeeRates,
    RiskAssessment,
    RiskProfile,
    TradeProposal,
)

STARTING_BALANCE: Final = Decimal(10000)
ACTIVE_STATES: Final = ("CANDIDATE", "VALIDATED", "ACTIVE", "ENTRY_TRIGGERED", "TP1_HIT", "TP2_HIT")


@dataclass(frozen=True)
class Account:
    id: UUID
    starting_balance: Decimal
    risk_profile_id: UUID
    profile: RiskProfile


@dataclass(frozen=True)
class NewRecommendation:
    strategy_id: UUID
    account: Account
    provider_id: int
    instrument_id: int
    timeframe: Timeframe
    proposal: TradeProposal
    assessment: RiskAssessment
    market_price: Decimal
    equity: Decimal
    dedupe_key: str
    quality_score: Decimal
    data_reliability: Decimal
    technical_explanation: str
    evidence: tuple[str, ...]
    conflicting: tuple[str, ...]
    data_as_of: datetime
    created_at: datetime
    expires_at: datetime
    risk_inputs: dict[str, Any]


class SignalRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def ensure_account(self, email: str) -> Account | None:
        """The single paper account, created on first use with default limits."""
        async with self._engine.begin() as connection:
            user = (
                await connection.execute(
                    text("SELECT id FROM users WHERE lower(email) = lower(:email)"),
                    {"email": email},
                )
            ).scalar_one_or_none()
            if user is None:
                return None
            row = (
                await connection.execute(
                    text(
                        "SELECT id, starting_balance FROM trading_accounts "
                        "WHERE user_id = :user AND name = 'Paper'"
                    ),
                    {"user": user},
                )
            ).one_or_none()
            if row is None:
                row = (
                    await connection.execute(
                        text(
                            """INSERT INTO trading_accounts (user_id, name, base_currency,
                                 starting_balance)
                               VALUES (:user, 'Paper', 'USDT', :balance)
                               RETURNING id, starting_balance"""
                        ),
                        {"user": user, "balance": STARTING_BALANCE},
                    )
                ).one()
                await self._create_profile(connection, row.id, user)
            profile = (
                (
                    await connection.execute(
                        text(
                            """SELECT * FROM risk_profiles WHERE account_id = :account
                           ORDER BY version DESC LIMIT 1"""
                        ),
                        {"account": row.id},
                    )
                )
                .mappings()
                .one()
            )
        return Account(row.id, row.starting_balance, profile["id"], _profile_of(profile))

    async def _create_profile(self, connection: AsyncConnection, account: UUID, user: UUID) -> None:
        defaults = RiskProfile()
        await connection.execute(
            text(
                """INSERT INTO risk_profiles (account_id, version, max_risk_fraction,
                     min_reward_risk, countertrend_extra_rr, max_daily_loss_fraction,
                     max_open_positions, max_total_exposure_fraction, max_leverage,
                     max_spread_bps, max_data_age_seconds, created_by)
                   VALUES (:account, 1, :risk, :rr, :extra, :daily, :positions, :exposure,
                     :leverage, :spread, :age, :user)"""
            ),
            {
                "account": account,
                "risk": defaults.max_risk_fraction,
                "rr": defaults.min_reward_risk,
                "extra": defaults.countertrend_extra_rr,
                "daily": defaults.max_daily_loss_fraction,
                "positions": defaults.max_open_positions,
                "exposure": defaults.max_total_exposure_fraction,
                "leverage": defaults.max_leverage,
                "spread": defaults.max_spread_bps,
                "age": defaults.max_data_age_seconds,
                "user": user,
            },
        )

    async def fee_rates(
        self, provider_id: int, instrument_type: str, at: datetime
    ) -> FeeRates | None:
        """The schedule in force then. Market orders pay the taker rate both ways."""
        async with self._engine.connect() as connection:
            taker = (
                await connection.execute(
                    text(
                        """SELECT taker_fee FROM fee_schedules
                           WHERE provider_id = :provider
                             AND instrument_type = CAST(:kind AS instrument_type_t)
                             AND effective_from <= :at
                           ORDER BY effective_from DESC LIMIT 1"""
                    ),
                    {"provider": provider_id, "kind": instrument_type, "at": at},
                )
            ).scalar_one_or_none()
        return FeeRates(entry=taker, exit=taker) if taker is not None else None

    async def ensure_strategy(self, name: str, version: int, parameters: dict[str, Any]) -> UUID:
        body = json.dumps(parameters, sort_keys=True)
        digest = hashlib.sha256(body.encode()).hexdigest()
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO strategy_configurations (name, version, kind, parameters,
                         content_hash)
                       VALUES (:name, :version, 'rule_baseline', CAST(:body AS jsonb), :digest)
                       ON CONFLICT (name, version) DO NOTHING"""
                ),
                {"name": name, "version": version, "body": body, "digest": digest},
            )
            found: UUID = (
                await connection.execute(
                    text(
                        "SELECT id FROM strategy_configurations "
                        "WHERE name = :name AND version = :version"
                    ),
                    {"name": name, "version": version},
                )
            ).scalar_one()
        return found

    async def is_active(self, account_id: UUID, key: str) -> bool:
        async with self._engine.connect() as connection:
            count = (
                await connection.execute(
                    text(
                        """SELECT count(*) FROM signal_current_state
                           WHERE account_id = :account AND dedupe_key = :key
                             AND state::text = ANY(:states)"""
                    ),
                    {"account": account_id, "key": key, "states": list(ACTIVE_STATES)},
                )
            ).scalar_one()
        return bool(count)

    async def record(self, new: NewRecommendation) -> UUID:
        """Store everything in one transaction. These rows are never edited afterwards."""
        recommendation = uuid7()
        sizing = new.assessment.sizing
        approved = new.assessment.approved
        action = Action.BUY if new.proposal.side is Side.LONG else Action.SELL
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO trade_recommendations (id, schema_version,
                         strategy_configuration_id, account_id, provider_id, instrument_id,
                         timeframe, action, entry_type, market_price, entry_price, stop_loss,
                         is_countertrend, dedupe_key, setup_quality_score, news_alignment,
                         data_reliability_score, technical_explanation, fundamental_explanation,
                         supporting_evidence, conflicting_evidence, invalidation_conditions,
                         data_as_of, data_age_ms, created_at, expires_at)
                       VALUES (:id, 1, :strategy, :account, :provider, :instrument,
                         CAST(:timeframe AS timeframe_t), CAST(:action AS action_t),
                         CAST(:entry_type AS entry_type_t), :market_price, :entry, :stop,
                         :countertrend, :key, :quality, 'unavailable', :reliability, :technical,
                         :fundamental, CAST(:evidence AS jsonb), CAST(:conflicting AS jsonb),
                         CAST(:invalidation AS jsonb), :data_as_of, :age, :created, :expires)"""
                ),
                {
                    "id": recommendation,
                    "strategy": new.strategy_id,
                    "account": new.account.id,
                    "provider": new.provider_id,
                    "instrument": new.instrument_id,
                    "timeframe": new.timeframe,
                    "action": action,
                    "entry_type": new.proposal.entry_type,
                    "market_price": new.market_price,
                    "entry": new.proposal.entry,
                    "stop": new.proposal.stop,
                    "countertrend": new.proposal.is_countertrend,
                    "key": new.dedupe_key,
                    "quality": new.quality_score,
                    "reliability": new.data_reliability,
                    "technical": new.technical_explanation,
                    "fundamental": "News is not used by the rule baseline.",
                    "evidence": json.dumps(list(new.evidence)),
                    "conflicting": json.dumps(list(new.conflicting)),
                    "invalidation": json.dumps(list(new.proposal.invalidation_conditions)),
                    "data_as_of": new.data_as_of,
                    "age": int((new.created_at - new.data_as_of).total_seconds() * 1000),
                    "created": new.created_at,
                    "expires": new.expires_at,
                },
            )
            if sizing is not None and len(sizing.target_reward_risk) == len(new.proposal.targets):
                for number, (price, share, ratio) in enumerate(
                    zip(
                        new.proposal.targets,
                        sizing.allocation,
                        sizing.target_reward_risk,
                        strict=True,
                    ),
                    start=1,
                ):
                    await connection.execute(
                        text(
                            """INSERT INTO trade_targets (recommendation_id, target_no, price,
                                 allocation_fraction, net_reward_risk)
                               VALUES (:id, :number, :price, :share, :ratio)"""
                        ),
                        {
                            "id": recommendation,
                            "number": number,
                            "price": price,
                            "share": share,
                            "ratio": ratio,
                        },
                    )
            await connection.execute(
                text(
                    """INSERT INTO risk_assessments (recommendation_id, risk_profile_id,
                         engine_version, decision, rejection_codes, equity, risk_budget,
                         entry_fill_est, stop_fill_est, risk_per_unit, quantity, notional,
                         leverage, margin_required, fees_est, funding_est, max_account_risk,
                         reward_risk_net, inputs)
                       VALUES (:id, :profile, :engine, :decision, :codes, :equity, :budget, :entry,
                         :stop, :unit, :quantity, :notional, :leverage, :margin, :fees, :funding,
                         :risk, :rr, CAST(:inputs AS jsonb))"""
                ),
                {
                    "id": recommendation,
                    "profile": new.account.risk_profile_id,
                    "engine": new.assessment.engine_version,
                    "decision": "APPROVED" if approved else "REJECTED",
                    "codes": [code.value for code in new.assessment.codes],
                    "equity": new.equity,
                    "budget": sizing.risk_budget if sizing else Decimal(0),
                    "entry": sizing.entry_fill if sizing else None,
                    "stop": sizing.stop_fill if sizing else None,
                    "unit": sizing.risk_per_unit if sizing else None,
                    "quantity": sizing.quantity if sizing else None,
                    "notional": sizing.notional if sizing else None,
                    "leverage": new.proposal.leverage,
                    "margin": sizing.margin if sizing else None,
                    "fees": (sizing.entry_fee + sizing.stop_fee) if sizing else None,
                    "funding": sizing.funding if sizing else None,
                    "risk": sizing.max_account_risk if sizing else None,
                    "rr": sizing.weighted_reward_risk if sizing else None,
                    "inputs": json.dumps(new.risk_inputs, default=str),
                },
            )
            path: tuple[SignalState, ...] = (
                (SignalState.VALIDATED, SignalState.ACTIVE) if approved else (SignalState.REJECTED,)
            )
            previous = SignalState.CANDIDATE
            await self._event(connection, recommendation, None, previous, new)
            for state in path:
                await self._event(connection, recommendation, previous, state, new)
                previous = state
            if approved:
                await connection.execute(
                    text(
                        """INSERT INTO signal_current_state (recommendation_id, account_id,
                             dedupe_key, state)
                           VALUES (:id, :account, :key, 'ACTIVE')"""
                    ),
                    {"id": recommendation, "account": new.account.id, "key": new.dedupe_key},
                )
                await connection.execute(
                    text(
                        """INSERT INTO alerts (recommendation_id, channel, dedupe_key, payload)
                           VALUES (:id, 'in_app', :key, CAST(:payload AS jsonb))"""
                    ),
                    {
                        "id": recommendation,
                        "key": f"signal:{recommendation}",
                        "payload": json.dumps(
                            {"action": action, "explanation": new.technical_explanation}
                        ),
                    },
                )
        return recommendation

    async def _event(
        self,
        connection: AsyncConnection,
        recommendation: UUID,
        previous: SignalState | None,
        state: SignalState,
        new: NewRecommendation,
    ) -> None:
        await connection.execute(
            text(
                """INSERT INTO signal_events (recommendation_id, from_state, to_state,
                     market_price, occurred_at, cause)
                   VALUES (:id, CAST(:previous AS signal_state_t), CAST(:state AS signal_state_t),
                     :price, :at, CAST(:cause AS jsonb))"""
            ),
            {
                "id": recommendation,
                "previous": previous,
                "state": state,
                "price": new.market_price,
                "at": new.created_at,
                "cause": json.dumps({"rejection_codes": [c.value for c in new.assessment.codes]}),
            },
        )

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        query = text(
            """SELECT r.id, r.instrument_id, p.code AS provider, r.timeframe::text AS timeframe,
                      r.action::text AS action, r.entry_type::text AS entry_type, r.entry_price,
                      r.stop_loss, r.market_price, r.setup_quality_score, r.news_alignment,
                      r.data_reliability_score, r.probability_status, r.technical_explanation,
                      r.fundamental_explanation, r.supporting_evidence, r.conflicting_evidence,
                      r.invalidation_conditions, r.created_at, r.expires_at, r.data_as_of,
                      a.decision, a.rejection_codes, a.quantity, a.notional, a.fees_est,
                      a.max_account_risk, a.reward_risk_net, a.funding_est,
                      COALESCE(s.state::text, 'REJECTED') AS state,
                      (SELECT json_agg(json_build_object('price', t.price::text,
                          'allocation', t.allocation_fraction::text,
                          'net_reward_risk', t.net_reward_risk::text) ORDER BY t.target_no)
                       FROM trade_targets t WHERE t.recommendation_id = r.id) AS targets
               FROM trade_recommendations r
               JOIN providers p ON p.id = r.provider_id
               JOIN risk_assessments a ON a.recommendation_id = r.id
               LEFT JOIN signal_current_state s ON s.recommendation_id = r.id
               ORDER BY r.created_at DESC LIMIT :limit"""
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query, {"limit": limit})).mappings().all()
        return [dict(row) for row in rows]


def _profile_of(row: Any) -> RiskProfile:
    return RiskProfile(
        max_risk_fraction=row["max_risk_fraction"],
        min_reward_risk=row["min_reward_risk"],
        max_daily_loss_fraction=row["max_daily_loss_fraction"],
        max_open_positions=row["max_open_positions"],
        max_total_exposure_fraction=row["max_total_exposure_fraction"],
        max_leverage=row["max_leverage"],
        countertrend_extra_rr=row["countertrend_extra_rr"],
        max_spread_bps=row["max_spread_bps"],
        max_data_age_seconds=row["max_data_age_seconds"],
    )
