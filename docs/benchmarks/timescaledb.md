# TimescaleDB Benchmark

Date: 2026-11-02
Status: Plain PostgreSQL measured. The TimescaleDB comparison was not run.
Hardware: MacBook Air M1, 8 GB memory, under heavy swap. PostgreSQL 18.0 in OrbStack, capped at 1 GB.

## Plain PostgreSQL

Measured by `backend/scripts/benchmark_reads.py` on 685,214 real candles, 200 samples per query.

| Query | Result | Target |
|---|---|---|
| Last 1,000 candles, p50 | 20.3 ms | |
| Last 1,000 candles, p95 | 25.3 ms | Under 100 ms |
| Last 500 hourly candles, p95 | 13.4 ms | |
| 115,200 candles over 80 days | 2.5 s | |
| Storage | 212.6 bytes per row | About 250 |

These timings include building typed models in Python, which is most of the cost. Reads on this dataset met the target, on a computer under memory pressure.

## Decision

Stay on plain PostgreSQL (D012). The adoption rule was to move only if PostgreSQL missed the target or a large benefit was measured, and it did not miss.

## Not Done

The comparison needs the full dataset and another large container image, and neither fits this computer. Compression may still matter for full history, so repeat this if the platform moves to a host with room.
