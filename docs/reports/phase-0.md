# Phase 0 Completion Report

Date: 2026-11-02
Branch: `develop`. Local commits only (D028).

## Exit Gate

| Gate | Result | Evidence |
|---|---|---|
| `make bootstrap && make check` on a clean clone | Passed | Run from a fresh clone: bootstrap took about 5 seconds, then every check through the secret scan passed |
| `make up` starts PostgreSQL 18 and Redis; health reports ready | Passed | PostgreSQL 18.0 and Redis 8.2. A real `GET /api/v1/health` returned `ready: true` |
| Frontend shows backend health with generated types | Passed | Types generated from `backend/openapi.json`; drift fails `make check` |
| Domain, API and event contracts documented | Passed | [13-API-CONTRACTS.md](../13-API-CONTRACTS.md) |
| D006 to D025 recorded | Passed | Also D026 to D028 |
| Binance behaviour and terms documented | Passed | [binance-spot.md](../providers/binance-spot.md) |
| No secrets in history, and only paper mode can be represented | Passed | gitleaks clean; `TradingMode` has one member, enforced by a test |

## Task Status

T0.1 to T0.14 are done. T0.15 is open.

## Differences From the Plan

- T0.15: at least 20 GB free is not met. Under D027 this now blocks only the full history download.
- T0.8: tests use the Compose PostgreSQL rather than testcontainers, to avoid another image.
- T0.10: TypeScript is pinned to 5.9.3, not 7.0.2.
- T0.11: no GitHub Actions, because there is no remote. Checks run through `make` and a pre-commit hook. A fake key was blocked by the hook.
- The Compose image is PostgreSQL 18.0 and the document named 18.6. Moving to a later 18.x is a one-line change.

## Measurements

- A fresh `uv sync` adds 156 MB, and the frontend adds 533 MB of `node_modules`.
- Containers use under 50 MB of memory at rest.
- This computer was using 8.9 GB of swap during the build. Swap lives on the internal disk, so free space moves with whatever else is open.

## Incomplete

- The 20 GB of free disk needed for full history.
- Binance's separate API terms are still unlocated.
