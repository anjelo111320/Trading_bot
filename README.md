# AI Trading Intelligence

An AI-powered live market analysis and trading research platform.

## Objectives

- Real-time authorized market data.
- Multi-timeframe technical analysis.
- Price-action and market structure detection.
- Financial news intelligence.
- Claude-powered market reasoning.
- Deterministic risk management.
- Entry, stop-loss and take-profit recommendations.
- Historical backtesting.
- Paper trading.
- Performance analytics.

## Operating Modes

1. Development.
2. Historical research.
3. Live analysis.
4. Paper trading.

Live execution is excluded from the initial release.

## Running It

Needs Docker (OrbStack on this computer), uv, pnpm and gitleaks.

```sh
make bootstrap     # Install everything and create .env
make up            # Start PostgreSQL and Redis
make migrate       # Create the database tables
make backfill      # Load 90 days of history
make soak          # Start live market data, keeping the computer awake on mains power
make quant         # Compute indicators, patterns, signals and paper trades
make api           # API on http://127.0.0.1:8000
cd frontend && pnpm build && pnpm start   # Dashboard on http://127.0.0.1:3000
```

Log in with `OWNER_EMAIL` and `OWNER_PASSWORD` from `.env`.

To keep it running instead, `make autostart` runs the ingestor, quant worker, API and dashboard as launchd agents. They start at every login, restart within 30 seconds if one stops, and keep the computer awake as `make soak` did. OrbStack is set to start at login, which brings PostgreSQL and Redis back. Logs go to `data/logs`.

```sh
scripts/autostart.sh status              # What is running
scripts/autostart.sh restart quant-worker   # After a backend change: also api, ingestor
scripts/autostart.sh rebuild-web         # After a frontend change
scripts/autostart.sh uninstall           # Stop everything and start nothing at login
```

After a reboot nothing runs until you log in, so turn on automatic login if the computer should recover alone.

Checks:

```sh
make check         # Lint, types, import rules, all tests and the secret scan
make audit         # Dependency vulnerabilities
make drill         # Inject real faults into the running stack
make soak-report SINCE=2026-11-02T09:47:00Z   # Compare stored data with Binance
```

To stop everything: `scripts/autostart.sh uninstall` if it was installed, otherwise `pkill -f entrypoints` and stop the dashboard, then `make down`. Data is kept unless you run `make reset`.

## Status

Phases 0 to 6 are built. Claude analysis is not, and news classification stays off until `ANTHROPIC_API_KEY` is set. See `docs/16-DEVELOPMENT-ROADMAP.md`, and `docs/reports/` for what is proven and what is still open.

The rule baseline has shown **no edge**. Signals are for research only and are not financial advice.

## Documentation

See the docs/ directory.

## Claude Code

Project rules: CLAUDE.md

Skills: .claude/skills/

Specialist agents: .claude/agents/

## Safety

This software is a research and decision-support tool.
It does not guarantee profits or trading accuracy.
