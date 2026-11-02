# Phase 1 Completion Report

Date: 2026-11-02
Status: Code complete. The 72-hour soak and full history remain open, so this phase is not yet proven (D028).

## Exit Gates: Phase 1A

| Gate | Result | Evidence |
|---|---|---|
| Full history stored, with counts reconciled to gaps | **Open.** 90-day test window only (D027) | 685,080 rows, exactly the expected count, 0 gaps. Full history needs 20 GB free |
| Live path meets its latency target | Met so far | p95 0.51 s against a 5 s target, on a small sample. The one exception is below |
| 72-hour soak | **Running** | Started 2026-11-02 09:46:58 UTC |
| Dashboard: live candles, forming distinct, stale warning | Passed | Checked in a real browser against live data |
| Rule snapshots and spread capture running since ingestion began | Passed | 4 rule rows; spread rows every minute while running |
| TimescaleDB decision recorded | Passed, with limits | [timescaledb.md](../benchmarks/timescaledb.md). Comparison not run |
| All tests, lint and type checks pass | Passed | 332 backend and 39 frontend tests |

## Exit Gates: Phase 1B

| Gate | Result | Evidence |
|---|---|---|
| Perpetual candles and funding backfilled and reconciled | Test window only | 342,540 candles, 0 gaps, 540 funding rates. The backfill took 179 seconds |
| Seven days of capture, with downtime reported | **Running** | Runs with the soak |
| Silent-stream detection proven | Passed | Regression test |

## Failure Drill

`scripts/failure_drill.sh` ran on the real stack while streaming from Binance. Everything recovered with no manual action.

| Fault | Result |
|---|---|
| Graceful stop | Stopped cleanly |
| Second instance | Refused by the advisory lock |
| Redis restart | Healthy again. 14 publish failures logged, and storage continued |
| PostgreSQL restart | Healthy again, with no process crash |
| `kill -9`, then 75 seconds down | Repaired on restart |
| Frozen process for 80 seconds | Recovered. Candles in that minute stored about 60 seconds late |

Afterwards, `backend/scripts/soak_report.py` compared storage with Binance: 52 live-window rows, 0 missing ranges, 0 value mismatches, 0 unresolved gaps. Three spread minutes were lost during the outages, and they stayed missing as designed.

This drill is not the soak. It covers about 12 minutes, and T1.18 still needs two 24-hour rollovers.

## Task Status

| Task | Status |
|---|---|
| T1.1 to T1.16, T1.20, T1.21, T1.24, T1.25 | Done, with tests |
| T1.17 | Partly done: plain PostgreSQL measured, no comparison |
| T1.18 | Running |
| T1.22 | Done. Real events arrived on `/market/stream`, which settles the open route question |
| T1.23 | Not started. P2, and no strategy needs it yet |

## Differences From the Plan

- One Binance adapter serves both venues, and one `stream_market` method replaces separate streams.
- BLS schedule dates are not collected yet. Only Federal Reserve feeds are archived.
- Disk-space rule changed by D027. Reports from the test window say so.
- The liquidation table gained a uniqueness rule, so replays cannot duplicate samples.

## Defects Found and Fixed

| Defect | Found by | Fix |
|---|---|---|
| Lock stayed held after a clean stop | Test | Explicit release |
| Spot provider attempted funding calls | Real backfill, stopped by the allow-list | Capability check |
| A brief database outage would crash the ingestor | Code review before the drill | Retry, then repair |
| Failed repair could report healthy | Same review | Stays RECOVERING until it succeeds |
| Crashes and stream drops missing from downtime | Soak report | Now recorded |
| PostgreSQL write-ahead log could use 1 GB | Disk review | Capped at 128 MB |

## Incomplete

- 72-hour soak and seven-day capture.
- Full history, which needs 20 GB free or a move to a host.
- A real sleep test of wake recovery, with at least 30 minutes asleep. Only simulated so far.
- Railway connection test (D026).
- Binance's separate API terms remain unlocated.
