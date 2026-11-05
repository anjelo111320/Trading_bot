# Security Requirements

- Store secrets in environment variables or a secret manager.
- Never expose API keys in browser code.
- Never commit .env.
- Use authentication and authorization.
- Validate all user inputs.
- Apply API rate limits.
- Protect WebSocket connections.
- Verify webhook signatures where applicable.
- Use parameterized database queries.
- Maintain audit logs.
- Restrict provider permissions.
- Use read-only market credentials where possible.
- Treat news and external text as untrusted.
- Protect against prompt injection.
- Do not permit AI output to execute code or orders.
- Maintain dependency security checks.
- Define backup and recovery procedures.

## Security Plan

Status: Updated 2026-11-02. Requirements: [brief section 17](21-PROJECT-BRIEF.md). D006 selected personal use, and D007 runs the platform on the owner's computer.

### Assets

| Asset | Why it matters |
|---|---|
| Anthropic and other API keys | Direct cost, and account abuse |
| Recommendation and outcome history | Its integrity is the point of the project |
| Risk limits | Control the system's behaviour |
| Paper-trading records | Evidence of performance |
| Licensed provider data | Redistribution could breach terms |
| User credentials and sessions | Control of the platform |

There are no exchange credentials, and no real money is reachable from the platform. This is the most important security property, so it must stay true.

### Trust Boundaries

| Zone | Trust | Handling |
|---|---|---|
| Browser | Untrusted | Every input validated. Holds no secrets |
| Market providers | Semi-trusted | Validated, never executed. Bad data is rejected |
| News and web content | **Hostile by default** | Treated as data only |
| Claude output | Untrusted | Schema-checked, verified against inputs, then risk-checked |
| API, workers | Trusted | Least-privilege database roles |
| PostgreSQL, Redis | Trusted, private network | No public ports |

### Threats and Controls

| Threat | Control | Verified by | Phase |
|---|---|---|---|
| Secret committed | `.gitignore`, gitleaks in CI and pre-commit | Fake key fails the check | 0 |
| Secret in logs | Redacting settings type, log filter | Test asserts absence | 0 |
| Secret in browser | Backend holds all keys. Only public API URL in frontend config | Bundle scan | 0 |
| Hidden live trading path | No exchange keys, `TradingMode` has one value, GET-only allow-list, database CHECK on `mode` | Tests fail on signed requests, order paths or a second mode | 0, 1 |
| Stolen session | HttpOnly, Secure, SameSite cookies, short expiry, login rate limit | Auth tests | 1 |
| Cross-site WebSocket hijack | Origin check plus short-lived ticket, since browsers cannot set auth headers | WebSocket tests | 1 |
| SQL injection | Parameterised queries only, no dynamic SQL | Injection tests, lint rule | 1 |
| Abuse of API | Rate limits, request size limits, Pydantic validation | API tests | 1 |
| Bad market data | Validator, staleness checks, database constraints | Unit tests | 1 |
| Tampering with history | Immutable tables by trigger, separated roles | Tested in schema validation | 1 |
| Risk limit tampering | Versioned profiles, audit log, environment hard ceilings the API cannot exceed | API test tries to exceed a ceiling | Risk phase |
| Prompt injection through news | No tools for the analyst, fixed schema, numbers only from Python, risk engine last | Hostile corpus | Analyst phase |
| AI output causing an action | AI output reaches only a validator. It never runs code, SQL or shell | Import rules, tests | Analyst phase |
| Stored XSS from news | React escaping, no raw HTML rendering, strict content security policy, `http` and `https` link schemes only | Component tests | News phase |
| Server-side request forgery | Workers never fetch article URLs. Outbound hosts are allow-listed | Test on allow-list | News phase |
| Cost abuse | Daily AI budget, trigger debounce, authenticated endpoints only | Budget tests | Analyst phase |
| Forged webhook | No inbound webhooks at first. Any later one needs signature verification and replay protection | Tests when added | Later |
| Dependency compromise | Lockfiles, pinned images, `pip-audit`, `pnpm audit`, reviewed updates | CI | 0 |
| Licence breach | Private repository, no data files in Git, provider terms recorded, retention flags | Repository scan | 0 |
| Backup exposure | Encrypted off-host backups, restricted access | Restore test | Hardening |

### Secrets

Secrets come from the environment locally and a secret manager in production. `.env` is never committed. Keys are rotated after any suspected exposure.

| Secret | Used by | Phase |
|---|---|---|
| `DATABASE_URL` per role | All processes | 0 |
| `REDIS_URL` | All processes | 0 |
| `APP_SECRET_KEY` | Sessions, WebSocket tickets | 1 |
| `ANTHROPIC_API_KEY` | `news-worker`, `analyst-worker` only | Analyst phase |
| News provider keys | `news-worker` only | News phase |
| `TELEGRAM_BOT_TOKEN` | `notifier` only | Risk phase |

Exchange keys are deliberately absent. Each process receives only the secrets it needs.

### Authentication and Authorization

Phase 1 uses one owner account (D019). Passwords use a memory-hard hash such as Argon2id. All endpoints except health sit behind one dependency, so multi-user support can replace it without touching routes.

Roles are `owner` and `viewer`. Only `owner` changes settings, and each change reaches `audit_log`. Authentication stays on even on one computer, because a malicious website can reach local services through the browser. If third-party access is ever wanted, D006 must be reopened and this section redesigned, including account isolation.

### Database

| Role | Access |
|---|---|
| `ati_migrator` | Schema changes. Used only by migrations |
| `ati_ingest` | Writes market tables |
| `ati_app` | Writes application tables. Cannot write candles |
| `ati_readonly` | Read-only. Cannot read `users` |

### Frontend

- Next.js is a client of the FastAPI backend and holds no secrets.
- Use a strict content security policy, HTTPS only and secure headers.
- Render external text as text.
- Keep Next.js and React patched, since framework vulnerabilities are outside project control.

### Local Operation

These apply while running on the owner's computer (D007).

- Every service binds to `127.0.0.1` only. No port is exposed to the network.
- Check `Host` and `Origin` headers, to block DNS rebinding and cross-site requests from a browser.
- FileVault is on, which protects `.env`, the database and backups at rest. Confirmed 2026-11-02.
- `.env` stays readable by the owner's user only.
- HTTPS is not needed on `localhost`. It becomes mandatory if the platform moves to a server.
- Backups are encrypted and kept off this computer.
- The Claude key is project-specific, in its own workspace with a spend limit.

### Audit Logging

Record logins, failed logins, settings and risk-profile changes, and any override attempt. Audit records are immutable. Logs must not contain secrets or full API payloads with credentials.

### AI Safety Boundaries

Full design: [07-CLAUDE-AI-ANALYST.md](07-CLAUDE-AI-ANALYST.md).

- Claude has no tools, no network and no database access.
- Its output cannot execute anything.
- Its numbers are ignored; prices come from Python through level IDs.
- It cannot change settings or risk limits.
- A failed analysis produces no trade.
- Kronos, a third-party model, runs as a separate process from a pinned commit and pinned weights, offline, with no secret or database setting in its environment. The runner refuses a modified checkout and validates the output. Its forecasts reach only Claude's context (D040).

### Live Trading Isolation

The initial release contains no way to place a real order. These checks run in CI:

- No exchange credentials in settings.
- No HMAC signing code in `data_providers`.
- No request to order, account or user-data endpoints.
- `TradingMode` has exactly one member.
- Database rejects non-paper accounts.

Any future execution module follows [02-SYSTEM-ARCHITECTURE.md](02-SYSTEM-ARCHITECTURE.md), Future Execution Isolation, and needs a separate security review.

### Incident Response

1. Contain: revoke the exposed key or stop the affected process.
2. Assess: use `audit_log`, `system_events` and `api_usage` to find scope.
3. Recover: rotate keys, restore from backup if records are damaged, and verify integrity.
4. Record: write up what happened and add a regression test.

Spend alerts on the Anthropic account act as an independent backstop to the application's budget.

### Security Gates

| Gate | Requirement |
|---|---|
| Every commit | Lint, tests, secret scan |
| Every pull request | Dependency audit, import rules |
| End of each phase | Run the `security-audit` skill on what was built |
| Before any always-on host | Firewall, HTTPS, no public database or Redis ports, backups |
| Before any third-party access | Full audit, licence review and legal review |

## WebSocket Protection

Status: Specified in [13-API-CONTRACTS.md](13-API-CONTRACTS.md).

- A browser sends cookies on cross-site WebSocket connections, so a cookie alone is not enough.
- The client requests a single-use ticket that lasts 30 seconds, and passes it when connecting.
- The server also checks the `Origin` header against the configured origins.
