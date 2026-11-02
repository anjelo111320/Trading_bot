# Baseline Backtest: BTCUSDT perpetual

Simulated results. A profitable backtest is not proof of future profitability.

| Metric | Value |
|---|---|
| Trades | 9 |
| Net P/L after costs | -559.10 |
| Total return | -5.59% |
| Win rate | 0.111 |
| Expectancy (R) | -0.694 |
| 95% interval for expectancy | -1.099 to 0.095 |
| Profit factor | 0.276 |
| Maximum drawdown | 5.59% |
| Sharpe (daily, 365 days, no risk-free rate) | -3.203 |
| Sortino | -4.053 |
| Cost share of gross profit | 0.325 |

Decisions checked: 8832. Signals: 58. Filled and finished: 9.

Risk engine rejections:

- EXPOSURE_EXCEEDED: 42
- RR_BELOW_MIN: 27

- Real perpetual candles from before the frozen holdout (D029).
- This window only proves the engine runs. It is far too short to be evidence of edge.
- Instrument rules are today's snapshot, used as a proxy for that period.
- Spread and slippage are conservative assumptions, not recorded values.
- BTC and ETH were chosen with hindsight, which is survivorship bias.
- At 1.5x costs: net P/L -476.19, trades 8, profit factor 0.29659476126829226
- At 2x costs: net P/L -667.75, trades 7, profit factor 0.0
