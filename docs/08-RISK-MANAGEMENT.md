# Risk Management Specification

## Default Configuration
Maximum risk per trade: 1% of equity.
Minimum reward/risk: 2.0.
Maximum daily loss: 3% of starting daily equity.
Paper trading only.

These values are configurable.

## Position Sizing
Calculate from:
- Equity.
- Risk fraction.
- Entry.
- Stop distance.
- Contract multiplier.
- Quantity step.
- Minimum notional.
- Fees.
- Instrument rules.

Do not apply one universal formula to every instrument.

## Validation
- Correct trade direction.
- Positive valid entry.
- Stop on correct side.
- Targets on correct side.
- Valid reward/risk.
- Valid position size.
- Current data.
- No duplicate active signal.
- Portfolio exposure limits.
- Daily loss limits.

## Execution Assumptions
Include spread, fees, slippage and funding when applicable.
Use conservative assumptions.
Document uncertainty.

## Rejection
Return a structured rejection reason.
Never silently modify an invalid trade.
The AI cannot override this engine.

## Risk Calculation Specification

Status: Proposed, 2026-11-02. Requirements: [brief sections 8 and 9](21-PROJECT-BRIEF.md). Module: `risk_management/`. Worked examples were computed with `Decimal` and are illustrative arithmetic, not market data.

### Principles

- Pure, deterministic functions. Same input, same output.
- `Decimal` throughout. Floats are rejected at the module boundary.
- All rule failures are collected and returned together, so a rejection is fully explained.
- Inputs are never adjusted. An invalid stop is rejected, not moved.
- The engine has no dependency on `ai_analyst` and gives Claude no override path.
- Live, backtest and paper modes all call this same code.

### Configuration

Limits are stored per account in `risk_profiles`, so each change is a new audited version. The environment sets hard ceilings that the API cannot exceed.

| Parameter | Default | Hard ceiling | Source |
|---|---|---|---|
| `max_risk_fraction` | 0.01 | 0.02 | Brief |
| `min_reward_risk` | 2.0 | Floor of 1.0 | Brief |
| `max_daily_loss_fraction` | 0.03 | 0.05 | Brief |
| `max_open_positions` | 3 | Configurable | Proposed |
| `max_total_exposure_fraction` | 1.0 | Configurable | Proposed |
| `max_leverage` | 3 | 5 | Proposed |
| `countertrend_extra_rr` | 0.5 | Configurable | Proposed |
| `max_spread_bps` | 5 | Configurable | Proposed |
| `max_data_age_seconds` | 30 | Configurable | Proposed |
| `target_allocation` | 50/30/20 | Must sum to 1 | Proposed |
| `max_open_risk_fraction` | None. The money plan uses 0.03 | From `max_risk_fraction` to 0.1 | D045 |
| `daily_profit_stop_fraction` | None. The money plan uses 0.03 | Above 0 | D045 |
| `max_total_loss_fraction` | None. Binance demo uses 0.2 | Above 0 and below 1 | D053 |

The proposed defaults are starting points to be reviewed, not validated settings. The D045 and D053 limits are kept in the profile's `settings`, and an account without them behaves as before.

Since D053 the Binance demo account has its own profile: 2% risk per trade, `max_total_exposure_fraction` 3 at up to ×3 leverage, and a loss stop 20% below its 100 USDT budget. Its other limits are the money plan's. The paper accounts are unchanged.

### Inputs and Outputs

Input: account equity, realized and unrealized P/L today, open positions, instrument type and multiplier, rule snapshot, fee schedule, top of book, data age, direction, entry type, entry, stop, targets, expected hold, expiry and risk profile.

Output, stored in `risk_assessments`: `APPROVED` or `REJECTED`, reason codes, fill estimates, risk per unit, quantity, notional, leverage, margin, fees, spread, slippage, funding, maximum account risk and net reward/risk.

### Symbols

| Symbol | Meaning |
|---|---|
| `s` | Side: +1 long, -1 short |
| `Pe`, `Ps`, `Pk` | Planned entry, stop and target `k` |
| `h` | Half the current spread |
| `ge`, `gs` | Estimated slippage on entry and stop |
| `fe`, `fx` | Fee rate on entry and exit |
| `m` | Contract multiplier. 1 for spot and USDT-margined linear contracts |
| `a_k` | Share of the position closed at target `k` |
| `Q` | Quantity |

### Cost Model

Conservative assumptions apply, because costs decide whether a thin setup is real.

| Cost | Rule |
|---|---|
| Spread | Half the live spread on market entries and stops. Live value in paper mode; modelled in backtests |
| Entry slippage | Market and stop entries: `max(2 ticks, 0.05 × ATR14 of 1M)`. Limit entries: 0 |
| Stop slippage | Same rule, and more in fast markets once calibrated |
| Target exits | Limit orders fill at the target, with no spread or slippage |
| Fees | Taker rate unless a limit fill is certain. Rates come from dated `fee_schedules` rows |
| Funding | Perpetuals only. Adverse assumption: `|rate| × S × m × n`, where `n` is the funding times within the expected hold |

Recorded spread data should replace these slippage placeholders once enough history exists.

### Fill Estimates

```text
E = Pe + s × (h + ge)       estimated entry fill
S = Ps - s × (h + gs)       estimated stop fill
```

### Risk Per Unit

```text
Ce = fe × E × m             entry fee per unit
Cs = fx × S × m             stop exit fee per unit
F  = funding estimate per unit, 0 for spot
U  = s × (E - S) × m + Ce + Cs + F
```

`U` is what one unit loses if the stop fills, after every cost. It must be positive.

### Position Size

```text
B = min(equity × max_risk_fraction × w, remaining_daily_loss_budget, open_risk_room)
Q = floor(B / U) to the instrument's lot step
A = Q × U                   maximum account risk
N = Q × E × m               notional
```

`w` is the proposal's `risk_share`, from above 0 to 1, and 1 unless the money plan sets it (D045). It can only lower risk. `open_risk_room` applies only to accounts with `max_open_risk_fraction`: `equity × max_open_risk_fraction - open risk`, where open risk is what every open or pending trade would lose at its current stop.

For an account with a loss stop (D053), `B` is also capped by `equity - open risk - start × (1 - max_total_loss_fraction)`, where `start` is the account's starting balance. All open stops together then cannot take equity below the stop.

Quantity is always rounded down, so actual risk never exceeds the budget. If `Q` falls below the minimum quantity, or notional falls below the minimum notional, the trade is rejected rather than increased.

Formula by instrument type:

| Type | Status | Sizing |
|---|---|---|
| Linear perpetual | Phase 3. The venue for all simulated trades under D008 | `m = 1`, funding included, margin below |
| Spot | Phase 3, as the simple case | `m = 1`, `F = 0`, leverage 1 |
| Inverse perpetual | Not in scope | Profit is non-linear in price and settles in the base asset, so this formula does not apply |
| Forex | Not in scope | Quote-currency P/L must convert to account currency, and lot size is in units |
| Equity | Not in scope | Whole-share rounding, plus overnight and borrow costs |

An instrument type without a calculator is rejected as `INSTRUMENT_NOT_SUPPORTED`. One formula is never stretched to fit.

### Net Reward to Risk

```text
Wk  = s × (Pk - E) × m - Ce - fx × Pk × m - F
RRk = Wk / U
RRw = sum of a_k × RRk
```

The minimum reward/risk rule applies to `RRw`, and `RR1` must be positive. With a countertrend setup, the minimum rises by `countertrend_extra_rr`.

`RRw` assumes every target fills. It is a planning ratio, not an expected value.

When fewer targets exist, the allocations are rescaled to sum to 1. Missing targets stay empty, and a target is never invented to pass the rule.

### Leverage

Leverage changes the capital set aside and the distance to liquidation. **It does not reduce risk.** The dashboard must state this wherever leverage appears.

```text
margin = N / L
Long liquidation  ≈ E × (1 - 1/L + mmr)
Short liquidation ≈ E × (1 + 1/L - mmr)
```

`mmr` is the maintenance margin rate. Binance's exact brackets need an API key, so use the public `maintMarginPercent` from `exchangeInfo` (2.5% for BTCUSDT at review time) as a minimum. Real liquidation depends on brackets and account state, so treat this as an approximation.

The stop must sit inside the liquidation price, separated by at least 1 ATR on the setup timeframe. Otherwise the trade is rejected.

### Daily Loss Limit

- The trading day starts at 00:00 UTC.
- Starting equity is total equity at that moment, including unrealized P/L.
- `loss = starting equity - current equity`, counting unrealized P/L.
- At the limit, new entries are blocked until the next UTC day. Open positions keep their stops.
- Below the limit, `B` is capped by the remaining budget, so one trade cannot breach it by design.

A stop can still gap past its level, so the daily limit is a control, not a guarantee.

### Money Plan Limits

For accounts that set them (D045):

- **Open risk.** What all open and pending trades would lose at their current stops stays at or below `max_open_risk_fraction` of equity. A trade is shrunk to the room left, and refused as `OPEN_RISK_FULL` when none is left. Per trade it is the engine's own `U × Q`, until a stop move makes it the distance to the new stop.
- **Daily profit stop.** Once equity is `daily_profit_stop_fraction` above the day's starting equity, new entries are refused as `DAILY_PROFIT_REACHED` until the next UTC day. Open trades keep their stops and targets. It is a ceiling, not a goal: nothing trades more to reach it.
- **Loss stop (D053).** A trade is shrunk to the room above the stop, and refused as `LOSS_STOP_REACHED` when none is left. Once equity is at or below the stop, the signal service records it against the profile version, and the account takes no new trade until the owner sets a new version. Open trades keep their stops and targets. A stop that fills worse than planned can still take equity below the line.
- **Signals that arrive together** are split before the engine sees them (`risk_management/allocation.py`). Each asks for its strategy's evidence share of the 1% risk. The highest share is served first, and signals with the same share split what is left in proportion, within the open-risk room, the remaining daily loss budget, the exposure room and the free position slots. The engine then checks each one, counting the trades approved before it at the same close.

### Exposure Limits

```text
gross exposure = sum of |Qi × price_i × m_i| / equity
```

A new trade is rejected if it would exceed `max_open_positions` or `max_total_exposure_fraction`. BTC and ETH are highly correlated, so holding both in the same direction is one bet in practice. A later version should add a correlated-exposure limit.

### Signal Rules

| Rule | Definition |
|---|---|
| Duplicate key | Account, instrument, direction, setup timeframe, and entry rounded to 0.5 ATR |
| Duplicate check | Enforced by the engine and by a unique index on active signals |
| Expiry | 8 setup candles by default, 24 maximum. Every trade must have one |
| Invalidation | At least one machine-checkable condition |
| Data checks | Data age, closed-candle freshness, and open gaps on required timeframes |

### Rejection Codes

| Code | Meaning |
|---|---|
| `SCHEMA_INVALID` | Input failed validation |
| `INSTRUMENT_NOT_SUPPORTED` | No calculator for this instrument type |
| `INSTRUMENT_RULES_MISSING` | No rule snapshot in force |
| `FEE_SCHEDULE_MISSING` | No dated fee rate |
| `MARKET_NOT_TRADING` | Instrument status is not trading |
| `DATA_STALE` | Data exceeds the maximum age |
| `DATA_INCOMPLETE` | Open gap on a required timeframe |
| `SPREAD_TOO_WIDE` | Spread above the limit |
| `INVALID_DIRECTION` | Direction and levels disagree |
| `INVALID_ENTRY` | Entry not positive, or impossible for the entry type |
| `STOP_WRONG_SIDE` | Stop on the wrong side of entry |
| `TARGET_WRONG_SIDE` | Target on the wrong side of entry |
| `TARGET_ORDER_INVALID` | Targets not progressively further from entry |
| `NOT_TICK_ALIGNED` | Price is not a multiple of the tick size |
| `NO_TARGET` | No target supplied |
| `RR_BELOW_MIN` | `RRw` below the minimum |
| `TP1_NOT_PROFITABLE` | `RR1` is not positive after costs |
| `QTY_BELOW_MIN` | Quantity under the instrument minimum |
| `QTY_ABOVE_MAX` | Quantity over the instrument maximum |
| `NOTIONAL_BELOW_MIN` | Notional under the instrument minimum |
| `DAILY_LOSS_REACHED` | Daily loss limit hit |
| `DAILY_PROFIT_REACHED` | The money plan's daily profit stop was reached (D045) |
| `OPEN_RISK_FULL` | No room left under the money plan's open-risk limit (D045) |
| `LOSS_STOP_REACHED` | No room left above the account's loss stop once every open stop is counted (D053) |
| `MAX_OPEN_POSITIONS` | Too many positions |
| `EXPOSURE_EXCEEDED` | Exposure limit exceeded |
| `LEVERAGE_EXCEEDED` | Leverage above the limit |
| `LIQUIDATION_INSIDE_STOP` | Liquidation is reachable before the stop |
| `DUPLICATE_ACTIVE_SIGNAL` | Matching signal already active |
| `EXPIRY_INVALID` | Expiry missing or too long |
| `INVALIDATION_MISSING` | No invalidation condition |

### Worked Example A: Spot Long, Approved

Assumptions: equity 10,000, risk 1%, entry 100.00, stop 98.00, spread 0.02, entry slippage 0.02, stop slippage 0.05, taker fee 0.1%, lot step 0.01.

| Step | Calculation | Result |
|---|---|---|
| Budget | 10,000 × 0.01 | 100.00 |
| Entry fill | 100.00 + 0.01 + 0.02 | 100.03 |
| Stop fill | 98.00 - 0.01 - 0.05 | 97.94 |
| Entry fee per unit | 100.03 × 0.001 | 0.10003 |
| Stop fee per unit | 97.94 × 0.001 | 0.09794 |
| Risk per unit | 2.09 + 0.10003 + 0.09794 | 2.28797 |
| Quantity | 100 ÷ 2.28797, floored | 43.70 |
| Maximum account risk | 43.70 × 2.28797 | 99.98 |
| Notional | 43.70 × 100.03 | 4,371.31 |

| Target | Allocation | Gross RR | Net RR |
|---|---|---|---|
| 104.00 | 50% | 2.00 | 1.646 |
| 106.00 | 30% | 3.00 | 2.519 |
| 108.00 | 20% | 4.00 | 3.393 |
| Weighted | | | 2.257 |

Result: approved. Costs take a 2.00 gross ratio on the first target down to 1.646 net, which is why reward/risk is always measured after costs.

### Worked Example B: Perpetual Short, Leverage Does Not Change Risk

Assumptions: equity 10,000, risk 1%, entry 100.00, stop 102.00, same spread and slippage, fee 0.05%, two funding intervals at 0.01%, maintenance margin 2.5%. Fees and funding here are illustrative only.

| Step | Result |
|---|---|
| Entry fill | 99.97 |
| Stop fill | 102.06 |
| Funding per unit | 0.020412 |
| Risk per unit | 2.211427 |
| Quantity | 45.21 |
| Maximum account risk | 99.98 |
| Notional | 4,519.64 |

| Leverage | Margin | Approximate liquidation | Account risk |
|---|---|---|---|
| 1× | 4,519.64 | 197.44 | 99.98 |
| 3× | 1,506.55 | 130.79 | 99.98 |
| 10× | 451.96 | 107.47 | 99.98 |

Risk is 99.98 at every leverage. Higher leverage only frees margin and moves liquidation closer. At 10× it also exceeds the 3× limit, so it is rejected with `LEVERAGE_EXCEEDED`.

Targets 96.00 and 94.00 at 50% each give net ratios of 1.742 and 2.647, weighted 2.194. The 3× trade is approved.

### Worked Example C: Rejected After Costs

Same as Example A, but with a single target at 104.00. Gross reward/risk is exactly 2.00, which looks acceptable. Net reward/risk is 1.646, so the trade is rejected with `RR_BELOW_MIN`.

### Tests

- Every formula, reproducing Examples A, B and C exactly.
- Boundaries: `RRw` exactly at the minimum, risk at the budget, quantity at the lot step, and notional at the minimum.
- Every rejection code has at least one test.
- Multiple simultaneous failures return all codes.
- Property tests: actual risk never exceeds the budget, and quantity is always a multiple of the step.
- Changing leverage never changes `Q` or `A`.
- Long and short symmetry.
- Float input is refused.
- An independent re-implementation checks a sample, per the `risk-engineer` agent.
