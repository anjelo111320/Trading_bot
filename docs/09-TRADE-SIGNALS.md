# Trade Signal Specification

## States
- CANDIDATE
- VALIDATED
- ACTIVE
- ENTRY_TRIGGERED
- TP1_HIT
- TP2_HIT
- TP3_HIT
- STOPPED
- INVALIDATED
- EXPIRED
- REJECTED

## Signal Lifecycle
Candidate -> validation -> active -> monitoring -> outcome.

## Signal Content
Instrument, direction, entry type, entry zone, stop, targets,
quantity, reward/risk, evidence, conflicting evidence,
invalidation, expiry, timestamps and schema version.

## Rules
Every signal has an expiry.
Every signal has invalidation conditions.
Preserve original recommendation.
Record subsequent revisions separately.
Avoid duplicate notifications.
Track actual outcomes independently.
