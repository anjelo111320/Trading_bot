# Model Forecasts

Date: 2026-11-05. Status: Built under D040. The owner chose option A: forecasts are evidence for Claude, never a source of prices.

## Summary

- Kronos, a pretrained candle model, samples 30 possible paths for the next 24 1H candles.
- A resampling baseline, the time machine, shows how the coin moves when nobody has a view.
- Claude reads both, labelled as an unvalidated model forecast. Neither sets a price, a size or a decision.
- Every forecast is stored before its outcome is known, and the database refuses later edits. A track record compares Kronos with the baseline, and tells Claude how far to trust it.

No model gives exact entries or targets. Entries, stops and targets still come from the Python level catalogue, by ID (D009), and the risk engine still checks every trade.

## Kronos

Kronos is described in Shi et al., *Kronos: A Foundation Model for the Language of Financial Markets* (arXiv 2508.02739, accepted at AAAI 2026). Code and weights are MIT-licensed. It turns candles into tokens and samples future candles one at a time, so each run gives a different possible path.

| Item | Value |
|---|---|
| Model | `NeoQuasar/Kronos-small`, 24.7 million parameters, Hugging Face revision `901c26c` |
| Tokenizer | `NeoQuasar/Kronos-Tokenizer-base`, revision `0e01173` |
| Weights published | 2025-06-30, last changed 2025-09-09, from the Hugging Face record |
| Code | `vendor/Kronos`, commit `67b630e`, ignored by Git |

Its training data ends before 2025-09-09. Earlier days may be in it, so no score from them counts. Later days are new to the model, which is what makes the study below an honest test.

## How It Runs

| Item | Setting |
|---|---|
| Environment | `vendor/Kronos/.venv`, Python 3.12 with PyTorch, separate from the backend's Python 3.14 |
| Call | `forecasting/kronos.py` writes the candles to a temporary CSV and runs `backend/scripts/kronos_forecast.py` as a child process |
| Input | The last 400 closed 1H candles, with no gap |
| Output | 30 paths of 24 candles: seed 7, sampling temperature 1.0, top-p 0.9 |
| Repeatability | Seeded, offline and fixed to 4 threads. Two runs on the same candles gave identical paths |
| Network | None. `HF_HUB_OFFLINE=1`, and the weights are read from the local cache |
| Secrets | None. The child process gets only `PATH`, `HOME` and four fixed settings, which a test checks |
| Time | About 90 seconds per forecast on this Mac. No fee |
| Disk | Environment 729 MB, weights 109 MB, code 25 MB |

The runner refuses to start unless `vendor/Kronos` is at the pinned commit with no local changes. Before anything is used, it checks the output: the echoed model, revisions and seed, the shape, the candle times, the last close, and finite positive prices.

Sampled candles are not always well formed: 9 of 720 in the first SOL run, and 12 and 3 of 720 in the first BTC and ETH runs, had a high below their own open or close. Each path's highest and lowest prices are therefore taken over all four prices, and the count is stored.

## The Baseline

The time machine draws blocks of two consecutive real 1H candles from the coin's last 60 days. It keeps each block's shape relative to its own open, and chains the blocks from the last close: 10,000 paths, seed 19, version 1.

The paths move the way the coin has moved lately, with no view on direction. Kronos adds information only where it differs from this. The idea comes from day-trader-skill's Time Machine, which is MIT-licensed. Nothing else from day-trader-skill is used, because it targets US stocks, reads Yahoo Finance data, and includes a broker that places real orders (D016).

## What Is Stored

Both tables are immutable, enforced by database triggers.

| Table | Contents |
|---|---|
| `model_forecasts` | Market, as-of close, horizon, model and code revisions, seed, reason (`setup`, `manual` or `study`), last close, ATR(14), the 30 paths, and percentiles 1 to 99 of each path's highest price, lowest price and final close, for Kronos and for the baseline, with the baseline's parameters |
| `model_forecast_outcomes` | The real high, low and close over the 24 candles, and both scores |

The same forecast is never made twice: a repeat request returns the stored one.

## How Forecasts Are Scored

Both sources are scored the same way, from their stored percentiles.

| Score | Question | Good value |
|---|---|---|
| Brier score of the share ending higher | When Kronos says 87% of paths end higher, does the price end higher about 87% of the time? | Lower. Always saying 50% scores 0.25 |
| Band coverage | How often the real high, low and close fall between the 10th and 90th percentiles | 80% |
| CRPS of the close | How close the whole close distribution was to the real close, in percent of price | Lower |
| Close position | Where the real close fell among the forecast's closes, in tenths | An even spread |

The track record status is:

- **too few forecasts** below 100 resolved.
- **better than baseline** when the 95% paired bootstrap intervals for both the Brier and CRPS differences lie below zero.
- **worse than baseline** when either interval lies above zero.
- **no difference shown** otherwise.

## What Claude Reads

The ETH forecast from the 01:59 UTC close on 2026-11-05, shortened. Distances are in 1H ATR from the last close (D035). Levels are catalogue IDs, with the share of paths that reach each within 24 hours.

```json
{
  "label": "unvalidated model forecast",
  "model": "NeoQuasar/Kronos-small",
  "horizon_candles": 24,
  "paths": {"model": 30, "baseline": 10000},
  "forecast": {
    "share_ending_higher": 0.03,
    "highest_atr": {"p10": -0.01, "p50": 0.26, "p90": 0.7},
    "lowest_atr": {"p10": -5.11, "p50": -3.46, "p90": -1.85},
    "close_atr": {"p10": -4.07, "p50": -2.59, "p90": -1.22}
  },
  "baseline": {
    "share_ending_higher": 0.49,
    "close_atr": {"p10": -3.26, "p50": -0.08, "p90": 3.24}
  },
  "levels": [{"id": "L1", "reached_share": {"model": 0.12, "baseline": 0.78}}],
  "track_record": {"resolved": 0, "status": "too few forecasts"}
}
```

That forecast is far more certain than ordinary movement: its 10th to 90th percentile close band is under 3 ATR wide and lies wholly below the price. That is either information or overconfidence, and only resolved outcomes can tell which.

## Rules

- Trade signals, paper trading, the risk engine and backtests cannot import `forecasting`. The import contract "model forecasts are evidence only (D040)" enforces it on every check.
- The prompt tells Claude that the forecast counts as a confirmation only once its status is "better than baseline", and is never the reason for a trade.
- Phase 7 validation adds two rules: a BUY or SELL must cite evidence other than the forecast, and `confluence_ids` may include the forecast only when its status is "better than baseline".
- Forecast levels as catalogue entries, or any effect on size, need a new owner decision, and evidence from live forecasts first.

## When It Runs

| Trigger | How |
|---|---|
| A setup | When a pattern setup passes the Claude gates, the analyst worker requests a forecast from the setup close, then calls Claude. This adds about 90 seconds. It is wired with the paper loop and Phase 7, and is not running yet |
| By hand | `forecast run`, from the latest stored close. A close more than two candles old is refused |
| A study | `forecast study`, on stored days after 2025-09-09 whose outcomes end before the holdout (D029) |
| Resolution | `forecast resolve` scores each forecast once its 24 candles are stored. It needs the ingestor or a backfill |

Commands, from `backend/`:

```bash
uv run python -m trading_intel.entrypoints.forecast run BTCUSDT ETHUSDT
uv run python -m trading_intel.entrypoints.forecast study BTCUSDT ETHUSDT --first 2025-09-10 --last 2025-10-31
uv run python -m trading_intel.entrypoints.forecast resolve
uv run python -m trading_intel.entrypoints.forecast report --write ../docs/reports/kronos-study.md
```

## Dashboard View

The Forecast page (`/forecast`) draws the latest forecast over the candles, from `GET /api/v1/forecasts/latest` ([13-API-CONTRACTS.md](13-API-CONTRACTS.md)).

- **Baseline, the projection:** the time machine's band in grey, with a dashed middle line, drawn again by Python from the latest 1H close every hour. The shaded future area and the "next hours" figures start there, so the future always begins at the newest candle.
- **Kronos:** its 30 paths as faint blue lines, with its 10th to 90th percentile band and middle line, from its own close. A run older than the latest close is drawn faded where it was made, labelled with its age, and left out of the "next hours" figures, the level reach shares and the price scale.
- **Python levels:** solid lines for levels price has reacted at, dotted or dashed for calculated ones. Labels sit in an empty margin on the right, so none covers a candle or the forecast.
- **The plan:** a position box, red between entry and stop and green toward the targets, across the time the plan was valid. Its status comes from the shared simulator on the 15M candles that followed.
- **Patterns:** each chart pattern's turning points, measured-move targets and invalidation, in orange.
- **Candle signals:** arrows, one per direction per bar, named in a panel and under the cursor.

Every layer can be switched off from the legend. Candles switch between 15M, 1H, 4H and 1D, and the forecast between its first 4 hours and all 24. On 4H and 1D candles, the hourly forecast is placed proportionally between bars. Side panels list the same values as text: Kronos against the baseline, the track record warning, the plan, the levels with reach shares, recent candle signals and the market context.

Colours were checked on the chart surface with the dataviz palette validator. Kronos blue against pattern orange separates by ΔE 26.8 under colour-blind simulation, and risk and reward always carry text labels.

The chart is live while the ingestor runs. The forming candle updates over the WebSocket, and each closed candle reloads the view. Python's levels, patterns, decisions and the projection are computed at the latest stored 1H close, so they move on every hour without a button. Kronos stays at its own close, and both times are shown above the chart. The status says when prices stop arriving although the connection is open, and a warning appears when the latest 1H close is more than 2 hours old.

The side panels start with **Python's signal**: each strategy's decision at the latest close, with Python's entry, stop and targets when it proposes a trade. A Claude plan follows it, showing Python's decisions at the plan's own close and warning when Claude planned while Python had no signal (D009, [07-CLAUDE-AI-ANALYST.md](07-CLAUDE-AI-ANALYST.md)).

Until 2026-11-06 the chart anchored the future, the baseline and the "next hours" figures at the Kronos run's close, so with a 12-hour-old run nothing was drawn after the newest candle, and reach shares measured from an old price were shown beside distances from the current one.

**Re-analyse** runs a new Kronos forecast from the latest stored 1H close, in the background, about 90 seconds. One analysis runs at a time. A second press gets a clear refusal, and a press at a close that was already analysed keeps the stored forecast. A file lock keeps Kronos to one run at a time across processes, so a study and the button never run it together.

A manual analyst plan, such as the BTC test of 2026-11-05, is labelled as one, because the live system calls Claude only at a setup. That plan's sell limit at 80,982.5 was not filled: the highest price before 07:00 UTC was 80,815.4.

## Study, 2025-09-10 to 2025-10-31

One forecast a day for BTC and ETH, from the 1H close before each day: 104 forecasts, all on days after the weights last changed and before the holdout. Full report: [kronos-study.md](reports/kronos-study.md).

**Result: worse than the baseline**, with 95% confidence on both scores.

| Score | Kronos | Baseline | Target |
|---|---|---|---|
| Brier score of the share ending higher | 0.393 | 0.252 | Below 0.25, the score of always saying 50% |
| Real close inside the 10th to 90th percentile band | 24% | 79% | 80% |
| Real highest price inside its band | 36% | 81% | 80% |
| CRPS of the close, % of price | 2.40 | 1.48 | Lower |

Kronos was confident and often wrong. When it said about 99% of paths end higher, the price ended higher 54% of the time, and when it said about 6%, 43% of the time. 79 of 104 real closes fell in the outer tenths of its paths. In this configuration, it pulled its forecasts toward the average of the 400 input hours, with bands far too narrow.

This meets D040's revisit condition. The configuration was fixed before the study and is not tuned on it: any other configuration must be fixed in advance and tested on days it has not seen.

### Audit, 2026-11-06

The owner asked whether the output was wrong. The call was checked against Kronos's own code: 30 copies of the series go through its batch prediction with one sample each, so paths are never averaged, and each window is normalised by Kronos itself. Across all 113 stored forecasts:

| Measure | Kronos | Baseline | Prices |
|---|---|---|---|
| Share of the gap to the 400-hour mean closed within 24 hours, by regression | 45%, correlation 0.86 | −1% | 12%, correlation 0.19 |
| Median width of the 10th to 90th percentile close band | 3.4 ATR | 8.6 ATR | Median absolute 24-hour move 2.3 ATR |
| Median jump from the last close to the first sampled candle | −0.10 ATR, largest 1.24 | 0 | |

The forecasts mostly say "back toward the average of the last 400 hours", with too much certainty. After the fall of 2026-11-05, the runs from 01:59 and 13:59 UTC on 2026-11-06 forecast rises of 3.8 and 5.2 ATR because the average sits far above the price, not because of new information. The 7 live forecasts from 2026-11-05 all missed falls of 8 to 11 ATR. The errors come from the model in this configuration, not from the wiring.

## Limits

- 30 paths make Kronos's shares move in steps of about 3%, and its tails rough.
- Forecasts made at setups overlap whenever setups come less than 24 hours apart. Overlap makes the bootstrap intervals too narrow.
- A study covers one market period. A score from it may not hold in another regime.
- A better forecast score is not profit. Costs, entries and exits decide that.
- Kronos was trained on data from over 45 exchanges. How much of it was 1H crypto data has not been checked here.
