---
name: security-audit
description: Audit the trading platform for credential leaks, authentication issues, API vulnerabilities, prompt injection, unsafe data handling and unauthorized trading execution. Use before deployment or security-sensitive changes.
---

# Security Audit Skill

Act as an application security engineer.

Read docs/14-SECURITY.md.

Inspect:
- Secrets and environment variables.
- Authentication.
- Authorization.
- API endpoints.
- WebSocket access.
- Database queries.
- Input validation.
- Rate limiting.
- Dependencies.
- Logging.
- External news content.
- Claude prompt injection risks.
- Provider permissions.
- Trading execution boundaries.

Ensure:
- No credentials in frontend bundles.
- No secrets in Git.
- No unsafe dynamic SQL.
- No external content treated as instructions.
- No AI output directly executes financial actions.
- No hidden path to live trading.

Classify findings by severity.

Provide evidence and remediation steps.

Never claim an audit is complete without inspecting the actual code.
