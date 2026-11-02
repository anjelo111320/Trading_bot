# Technical Analysis Specification

## Indicators

Trend:
- EMA 9, 20, 50, 100, 200.
- SMA 50 and 200.
- VWAP.
- ADX.

Momentum:
- RSI.
- MACD.
- Stochastic RSI.
- CCI.
- Rate of Change.

Volatility:
- ATR.
- Bollinger Bands.
- Historical volatility.
- Keltner Channels.

Volume:
- Volume SMA.
- Relative volume.
- Volume spikes.
- OBV.
- Volume delta only when reliable trade data exists.

## Market Structure
- Swing highs and lows.
- HH, HL, LH and LL.
- BOS.
- CHoCH.
- Support and resistance.
- Supply and demand.
- Liquidity sweeps.
- Fair Value Gaps.
- Order blocks.
- Breakouts and false breakouts.
- Bullish and bearish engulfing.
- Pin bars.
- Doji patterns.
- Trend reversals.
- Consolidation zones.
- Divergences.

## Requirements
Every pattern must have explicit detection rules.
Record pattern type, instrument, timeframe, price level, detection timestamp, validation status, strength score and evidence.
Document assumptions and confidence limitations where a pattern is subjective.
Avoid look-ahead when identifying swing points.
Allow patterns to be invalidated.
Keep calculations deterministic.

## Multi-Timeframe
1D: broad direction.
4H: major structure.
1H: intermediate structure.
15M: setup.
5M: entry confirmation.
1M: optional refinement.

These roles are defaults. The user can change them.
Countertrend setups are allowed but need stronger evidence and a clear statement of the added risk.

## Research
Document assumptions.
Test each indicator against reference calculations.
Do not assume an indicator predicts future prices.
