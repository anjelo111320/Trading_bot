# Binance Futures Execution

Date: 2026-11-10
Status: Research for the owner's request to trade Binance USDⓈ-M futures with isolated margin, 1% risk and profit targets. **Accepted on 2026-11-10 as D048**, for demo trading with test funds only. See "Owner Decisions" below.

## What the System Does Today

- Paper only. `TradingMode` has one value, `PAPER`. No exchange key exists and no order path is written (D016, and rule 13 in `CLAUDE.md`).
- Market data already comes from Binance USDⓈ-M perpetuals, through public endpoints only.
- Every trade already risks at most 1% of equity, through the risk engine. In the money plan a strategy's evidence share can lower that to 0.5% or 0.25% (D045).
- Every trade already has one to three targets, each at least 2R away, closed 50%, 30% and 20%. The money plan also stops new trades for the day at +3%.
- The risk engine already sizes perpetual trades with leverage and checks an approximate isolated-margin liquidation price: the stop must sit at least one ATR before it. Leverage is capped at 3, with a hard ceiling of 5.

So risk and targets exist. What is missing is a way to send them to Binance.

## Can It Trade Binance Futures?

Technically yes. The USDⓈ-M Futures API supports everything needed, but recent changes matter:

| Need | Binance endpoint | Notes |
|---|---|---|
| Isolated margin | `POST /fapi/v1/marginType` with `ISOLATED` | Set per symbol, before any position or order. "No need to change" is not an error |
| Leverage | `POST /fapi/v1/leverage` | Per symbol. The maximum is symbol-specific, from `GET /fapi/v1/leverageBracket` |
| Position mode | `POST /fapi/v1/positionSide/dual` | One-way mode keeps one position per coin, as the system assumes |
| Entry | `POST /fapi/v1/order`, `MARKET` or `LIMIT` | A client order ID makes a retry safe |
| Stop-loss | `POST /fapi/v1/algoOrder`, `STOP_MARKET` | **Since 2025-12-09, stop and take-profit orders go through the Algo Order endpoint.** The old order endpoint rejects them with `-4120` |
| Targets | `POST /fapi/v1/algoOrder`, `TAKE_PROFIT_MARKET`, `reduceOnly` | One per target, for 50%, 30% and 20% of the size |
| Order updates | User data stream: `ORDER_TRADE_UPDATE`, `ALGO_UPDATE`, `ACCOUNT_UPDATE` | A listen key lasts 60 minutes and must be renewed. Stream URLs moved to `/private` paths in March 2026 |
| Practice | Demo trading, `https://demo-fapi.binance.com` and `wss://demo-fstream.binance.com` | The same API with test funds and its own keys |

Other facts that shape the design:

- Untriggered stop and take-profit orders cannot be modified, only cancelled and replaced. Binance runs no margin check before they trigger. At most 200 can be open across all coins.
- Stops trigger on the mark price (`workingType=MARK_PRICE`) with `priceProtect`, so a single wick on the last price does not fire them.
- Orders count against a per-account rate limit: algo orders weigh 1 on the 10-second and 1-minute order limits. Ignoring a 429 response leads to a ban (418) of 2 minutes up to 3 days.
- Signed requests need a timestamp within the receive window of Binance's clock.
- Keys: Binance recommends Ed25519 keys; HMAC keys are deprecated, and an HMAC key without an IP restriction is read-only. Futures must be enabled on the account before the key is made. Withdrawal must never be enabled.
- Fees match the backtests' assumptions at the lowest tier: 0.05% taker and 0.02% maker.
- Binance limits futures in some countries. The owner must confirm their account can trade them.

## Isolated Margin and the 1% Risk

With isolated margin, each trade holds its own margin: position value ÷ leverage. Leverage does **not** change what the stop loses. That is set by the size and the stop distance, which the risk engine fixes at 1% of equity or less. Leverage only changes how much margin is held and how close liquidation sits.

Example on 1,000 USDT, a BTC short with its stop 1.5% above entry: 1% risk is 10 USDT, so the position is about 667 USDT. At leverage 1 it holds 667 USDT of margin. At leverage 3 it holds 222 USDT, and liquidation moves to about 33% above entry, still far beyond the stop. Either way the stop loses about 10 USDT plus costs.

## Proposed Design

1. **A separate module, `execution/`,** holding a `BinanceFuturesGateway`: the signed REST client, the user data stream and reconciliation. It is the only code that holds keys or sends orders. An import-linter contract keeps Claude's code, news and forecasts from importing it.
2. **Only an approved risk assessment can become an order.** The gateway takes the risk engine's sizing, never a price from anywhere else, and never from Claude (D009).
3. **Orders per trade:** set isolated margin and leverage, place the entry, then a mark-price stop for the whole position and one reduce-only take-profit per target. When the stop fills, the remaining targets are cancelled. Stop and targets sit on Binance, so the position stays protected while the Mac sleeps.
4. **Safety:**
   - Client order IDs, so a retry never doubles an order.
   - Reconciliation with Binance at start and every minute.
   - A kill switch that cancels all orders and closes all positions.
   - A cap on the USDT held in trades.
   - Every order and fill is stored.
5. **Keys** live in `.env` only. They are never sent to the frontend or logged.
6. **Stages:** demo trading first. Real money needs a new decision replacing D016, a changed rule 13 in `CLAUDE.md`, and the owner's explicit approval at that time.

## Owner Decisions, 2026-11-10

| Question | Chosen |
|---|---|
| Where orders go | Binance demo trading, test funds only. Real money is a separate, later decision |
| Strategies | The money plan's three, at their evidence shares: daily trend 1%, 1H pattern 0.5%, 15M rule 0.25% |
| Targets | Up to three take-profits on Binance at Python's targets, 50%, 30% and 20%, plus the daily +3% stop on new trades |
| Leverage | Isolated, the lowest that fits, at most 3x |

Built as designed above, with these version 1 limits: market entries only, and a REST check once a minute instead of Binance's user data stream. Keys can be self-generated Ed25519, recommended, or system-generated HMAC. The dashboard does not show the Binance demo account yet.

Since 2026-11-10 the bot trades a **100 USDT budget** of the demo account's 5,000 test USDT: 100 USDT plus its own profit and loss, at most 1 USDT of risk per trade (D048). BTC's smallest order, 0.001 BTC or about 74 USDT, is too large for most of its signals at that size.

Two fixes on 2026-11-11, both found on the first daily trend trade, a SOL short:

- **The daily trend's stop trails on Binance too.** Its exit is the 10-day extreme, moved at each daily close (D039), and only paper stops were moved, so the Binance trade kept its first stop. Now, at each daily close, the worker cancels the trade's stop on Binance and places one at the new level straight after, because Binance holds one whole-position stop per side. If the new stop is refused, the old price goes back. Only if no stop is left at all is the position closed. The stop held afterwards is recorded, so the minute check restores that one. The Bot page lists the cancel as "Stop cancelled".
- **A target outside Binance's price filter is not sent.** On a short, the daily trend's 10R cap can reach past zero, so it is floored at one tick, 0.01 USDT. Binance's lowest SOL price is 0.42, and it refused the order (`-4013`). Price cannot reach such a target, and the stop covers the whole position, so leaving it out changes no exit.

## Setting It Up

1. Run `cd backend && uv run python -m trading_intel.entrypoints.binance_demo keygen`. It writes an Ed25519 private key to `~/.config/trading-intel/binance-demo-ed25519.pem`, readable only by this user and outside the project, and prints the public key. The private key never leaves this computer. Binance needs only the public key.
2. Log in at demo.binance.com, open the profile menu, then Demo Trading API, then Create API, then **Self-generated**. Paste the public key, name the key, pass the security check, and turn on Enable Reading and Enable Futures, with withdrawals off.
3. Copy the API key Binance shows into `.env` as `BINANCE_DEMO_API_KEY`. There is no secret with a self-generated key. A system-generated key also works: put its secret in `BINANCE_DEMO_API_SECRET` instead, and the key file is not needed.
4. Run `cd backend && uv run python -m trading_intel.entrypoints.binance_demo check`. It shows the demo balance and position mode, and never prints the keys.
5. Run `scripts/autostart.sh restart quant-worker`. The log shows `exchange_enabled`, and from the next 15M close the money plan also trades Binance demo.
6. `binance_demo status` shows positions with their stops and targets. `binance_demo flatten --yes` closes everything.

## Evidence Before Real Money

These are simulated results. A profitable backtest is not proof of future profit.

- Daily trend: +0.40R a trade on six coins from 2020 to 2025, 95% interval +0.16 to +0.65 (docs/33, corrected). The only strategy that replicated.
- 1H pattern breakout: +0.08R, interval -0.04 to +0.20. Not proven.
- 15M rule baseline: untested before the holdout, and it showed no edge in its one short test.
- 4H gap and 15M CHoCH: registered, not run yet (docs/35).
- Live paper so far: the money plan has 1 loss and 3 open trades, -0.90 USDT on 1,000.

## Sources

- Binance USDⓈ-M Futures general info: https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
- Binance derivatives change log: https://developers.binance.com/docs/derivatives/change-log
- New Algo Order: https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order
- User data streams: https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams
- API key types: https://developers.binance.com/docs/binance-spot-api-docs/faqs/api_key_types
