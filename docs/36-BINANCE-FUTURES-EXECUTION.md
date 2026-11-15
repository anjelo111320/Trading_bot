# Binance Futures Execution

Date: 2026-11-10
Status: Research for the owner's request to trade Binance USDⓈ-M futures with isolated margin, 1% risk and profit targets. **Accepted on 2026-11-10 as D048**, for demo trading with test funds only. See "Owner Decisions" below. **Real money accepted on 2026-11-13 as D060**: the owner's real futures wallet, beside demo trading. See "The Real Account (D060)".

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

Built as designed above, with these version 1 limits: market entries only (limit entries added on 2026-11-11, see below), and a REST check once a minute instead of Binance's user data stream. Keys can be self-generated Ed25519, recommended, or system-generated HMAC. The dashboard does not show the Binance demo account yet.

Since 2026-11-10 the bot trades a **100 USDT budget** of the demo account's 5,000 test USDT: 100 USDT plus its own profit and loss (D048). BTC's smallest order, 0.001 BTC or about 74 USDT, is too large for most of its signals at that size.

Two fixes on 2026-11-11, both found on the first daily trend trade, a SOL short:

- **The daily trend's stop trails on Binance too.** Its exit is the 10-day extreme, moved at each daily close (D039), and only paper stops were moved, so the Binance trade kept its first stop. Now, at each daily close, the worker cancels the trade's stop on Binance and places one at the new level straight after, because Binance holds one whole-position stop per side. If the new stop is refused, the old price goes back. Only if no stop is left at all is the position closed. The stop held afterwards is recorded, so the minute check restores that one. The Bot page lists the cancel as "Stop cancelled".
- **A target outside Binance's price filter is not sent.** On a short, the daily trend's 10R cap can reach past zero, so it is floored at one tick, 0.01 USDT. Binance's lowest SOL price is 0.42, and it refused the order (`-4013`). Price cannot reach such a target, and the stop covers the whole position, so leaving it out changes no exit.

## Owner Decisions, 2026-11-11 (D053)

| Question | Chosen |
|---|---|
| Risk per trade | 2% of the budget, at most 2 USDT a trade. The evidence shares give the daily trend 2%, the 1H pattern and the 4H gap 1%, and the 15M rule 0.5% |
| Open risk | Kept at 3% across open trades |
| Exposure | Positions may total up to 3 times the budget, at the lowest leverage that fits, still at most 3x |
| Loss stop | No new trades once 20 USDT is lost: at 80 USDT, until the owner sets new limits |
| Real money | Not yet. Demo results first |

Leverage still never changes what a stop loses. It lets a tight-stop trade hold a position larger than the budget. Every open stop together is kept above 80 USDT, but a stop that fills badly in a crash can take the account lower. The Bot page shows the stop and how much is left above it.

## Owner Decisions, 2026-11-12 (D058)

| Question | Chosen |
|---|---|
| Risk per trade | 10% of equity, after raising the risk engine's ceiling from 2% |
| Open risk and daily loss | 10% each |
| Positions | All together within 80% of equity. A trade too big is shrunk to fit |
| Loss stop | 20%, measured from the starting budget, or from the highest equity if chosen |
| Changing them | The Bot page's Settings tab. Each save is a new, logged version |

## The Real Account (D060), 2026-11-13

The owner asked to put their real account on the Bot page, to close trades from the system, and to see closes made in the Binance app so their USDT is free for the next trade. They asked that the bot read only the futures balance, never the Overview, Spot or Funding.

| Question | Chosen |
|---|---|
| Account | The main account's USDⓈ-M futures wallet, not a sub-account |
| Capital | Whatever the owner puts in the futures wallet. Transfers in or out change the capital and are never a profit or a loss |
| Limits | The project defaults, with a 20% loss stop: 1% a trade, 3% open risk, 3% daily loss, positions within 100%, up to x3, the +3% daily stop |
| Demo trading | Keeps running beside it, on the same signals. The Bot page switches between Real and Demo |

### What the Bot Reads

Binance has no read-only-futures setting: a key that can read, reads every wallet. So the bot's own code is the limit:
- The real-account gateway reaches `https://fapi.binance.com` only, and only the paths in `FUTURES_PATHS`: the futures account, positions, orders, fills and the futures wallet's own income. Anything else is refused before it is sent.
- Transfers into and out of futures are read from the futures wallet's own income history (`incomeType=TRANSFER`), so no other wallet is ever read.
- One request goes elsewhere: `GET /sapi/v1/account/apiRestrictions` on `api.binance.com`, which reports what the key may do and reads no balance.
- The key itself must not be able to withdraw, transfer or trade anything but futures, so even if it were stolen with its private key, Spot and Funding could not be touched.

### How It Trades

- **Arming:** nothing trades until the owner arms the account: `binance_live arm --yes` in the terminal after its check passes, or the switch on the Bot page with their password (D063). Off stops new trades; open trades keep their stops and targets.
- **The hourly check:** the key's permissions, one-way position mode and single-asset (USDT) margin. Any problem stops new trades and shows on the Bot page, and is checked again every 5 minutes until it is fixed. The bot never changes these settings for the owner.
- **Capital:** the futures wallet's equity is the bot's equity. What the owner put in is the equity first seen plus transfers since. A transfer moves the day's starting equity by as much, so it never trips the daily loss limit or the +3% daily stop. The 20% loss stop sits at 80% of what was put in.
- **The owner's own trades:** the bot touches only its own orders (client IDs starting `ati-`) and the positions of its own open trades. A position the owner opened is never given a stop, moved or closed. It still takes its coin, and its whole value counts as open risk, because the bot knows no stop for it. Since D066, a stop the owner sets in the app on one of the bot's trades protects that trade, and the bot keeps it.
- **Trades ending:** the minute check records each of the bot's trades whose coin is flat on Binance, whether a stop or target filled or the owner closed it in the app. Its fills are copied at once, so the Results tab shows it, and its margin is free for the next trade.
- **Closing from the dashboard:** the Close button stores a request; the quant worker carries it out within seconds. It cancels a waiting entry first, closes the position at market with a reduce-only order, and only then cancels the bot's stop and targets on the coin. If the close is refused, the stop and targets stay.

### Setting Up the Real Account

1. `cd backend && uv run python -m trading_intel.entrypoints.binance_live keygen` writes `~/.config/trading-intel/binance-live-ed25519.pem`, readable only by this user, and prints the public key.
2. On binance.com: API Management, Create API, **Self-generated**. Paste the public key. Tick **Enable Futures** only; Enable Reading is always on. Leave withdrawals, internal and universal transfers, spot and margin, and options off. If the internet connection has a fixed IP, restrict the key to it.
3. Put the API key Binance shows in `.env` as `BINANCE_LIVE_API_KEY`, then `scripts/autostart.sh restart quant-worker`. The log shows `exchange_enabled ... account=Binance real`.
4. Move the USDT the bot may trade into the USDⓈ-M futures wallet. The bot sees it within a minute and makes the account from it (`exchange_account_created`).
5. `binance_live check` shows the futures wallet, the key's permissions and any problem. `binance_live arm` shows the limits; `binance_live arm --yes` arms it.
6. `binance_live status` lists positions, the bot's and the owner's. `binance_live flatten --yes` closes the bot's trades only.

## The Profit Lock and the Owner's Own Stops, 2026-11-14 (D066)

The owner asked to move the stop into profit once a trade is up, and to raise leverage so the trade's money could start new trades.

| Question | Chosen |
|---|---|
| Trigger | Scaled to each trade's stop: at 1.5R beyond the entry fill, the stop moves to 1R beyond it |
| Money it frees | Its risk only: a stop past the entry counts as no open risk. Leverage and the room stay as set |
| Testing | Built on real now, with no backtest first |
| A stop the owner moves in the app | Kept, and the trade stays open |

How it runs:
- **Every minute, on both Binance accounts,** the worker reads each bot position's mark price. At 1.5R beyond the fill it moves the bot's stop to 1R beyond the fill by cancel and replace, as the daily trend's trail does.
  - Binance cannot modify a waiting stop, so this is the only way to move one.
  - The new stop is recorded, so the minute check restores that one if it goes missing.
- **Leverage is left alone.** On isolated margin, raising leverage releases no margin by itself. The margin must be removed in a separate call, and every USDT removed brings liquidation nearer to the stop. The room the owner sets is what limits new trades.
- **Open risk is counted at the stop Binance holds,** the bot's or the owner's, and never below what the trade risked at its first stop (D067). A lock protects its trade but frees no room for another. Under D066 a stop past the entry counted as no risk, until the research report warned that this let same-direction trades stack.
- **A stop the owner sets keeps the trade open.** If it closes the whole position, the bot leaves it and the trade alone. If Binance refuses the bot's stop because one already stands (-4130), nothing is closed.
  - On 2026-11-14 at 02:11 UTC that refusal made the bot close the real SOL short at market. The owner had changed its stop in the app minutes before.

## Results From Binance's Fills, 2026-11-12 (D057)

Binance reports fills, not trades, and keeps them for 3 months. Every 5 minutes the quant worker copies the account's fills (`GET /fapi/v1/userTrades`, per coin the bot has traded) and funding payments (`GET /fapi/v1/income`, `FUNDING_FEE`) into append-only tables (migration 0018).
- **First copy:** 7-day windows from a minute before the bot's first entry on each coin, the longest window Binance allows.
- **Later copies:** onward from the last stored fill ID.

Python rebuilds each completed trade from them. A fill that takes a position through flat is split: its profit goes to the trade it closes, and its fee is split by size. The Bot page's Results tab shows the figures. Binance's IDs keep each fill once, so a repeated copy changes nothing.

## Limit Entries, 2026-11-11 (D054)

The 4H gap and 15M CHoCH strategy enters with a limit order, so it was refused here until the owner asked for every strategy to trade on Binance demo. Binance demo was tested first, with orders far from the price that were all cancelled at once:

| Order, with no position open | Binance |
|---|---|
| Limit entry, GTD | Accepted |
| Stop closing the whole position | Refused, `-4509`: only with an open position |
| Reduce-only stop with a quantity | Accepted |
| Reduce-only take-profit with a quantity | Accepted |

So a limit entry is sent as GTD until its signal expires, together with a reduce-only stop for the full planned size and its take-profits. Whatever fills is protected at once, even while the Mac sleeps. If that stop is refused, the entry is cancelled. The minute check keeps a waiting entry's orders, and cancels an entry that has no stop left. A waiting entry takes its coin and counts toward open risk and exposure. Its fill is not reported back yet, so the Bot page shows it as the dashed waiting line becoming the position.

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
- Binance demo when the owner chose real money (2026-11-13): 1 completed trade, +1.11 USDT (+2.23R), and 4 open, with equity at 101.99 on its 100 USDT budget after three days. Too few trades to show an edge.

## Sources

- Binance USDⓈ-M Futures general info: https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
- Binance derivatives change log: https://developers.binance.com/docs/derivatives/change-log
- New Algo Order: https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order
- User data streams: https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams
- API key types: https://developers.binance.com/docs/binance-spot-api-docs/faqs/api_key_types
