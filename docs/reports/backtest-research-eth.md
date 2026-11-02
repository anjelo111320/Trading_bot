# Baseline Backtest: ETHUSDT perpetual

Simulated results. A profitable backtest is not proof of future profitability.

| Metric | Value |
|---|---|
| Trades | 32 |
| Net P/L after costs | 405.72 |
| Total return | 4.06% |
| Win rate | 0.344 |
| Expectancy (R) | 0.153 |
| 95% interval for expectancy | -0.416 to 0.734 |
| Profit factor | 1.188 |
| Maximum drawdown | 6.79% |
| Sharpe (daily, 365 days, no risk-free rate) | 0.987 |
| Sortino | 2.042 |
| Cost share of gross profit | 0.087 |

Decisions checked: 8832. Signals: 75. Filled and finished: 32.

Risk engine rejections:

- EXPOSURE_EXCEEDED: 13
- RR_BELOW_MIN: 14

- Real perpetual candles from before the frozen holdout (D029).
- This window only proves the engine runs. It is far too short to be evidence of edge.
- Instrument rules are today's snapshot, used as a proxy for that period.
- Spread and slippage are conservative assumptions, not recorded values.
- BTC and ETH were chosen with hindsight, which is survivorship bias.
- At 1.5x costs: net P/L 125.24, trades 28, profit factor 1.0659990746404577
- At 2x costs: net P/L -118.87, trades 24, profit factor 0.9278484788867483
