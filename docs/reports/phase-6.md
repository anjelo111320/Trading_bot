# Phase 6 Completion Report

Date: 2026-11-02
Status: Built, except that Claude classification has never run against the real API, because no key exists yet.

## Exit Gate

| Gate | Result | Evidence |
|---|---|---|
| Timestamps preserved | Passed | Published, retrieved and first-seen times stay separate, and the API role cannot rewrite them |
| No future news | Passed | An item is invisible before the later of publication and first sighting. A label is invisible before it was made |
| Injection tests pass | Passed for what can be tested offline | See below |
| Costs controlled | Passed | Each story is classified once, irrelevant items never reach a model, and the daily limit is checked before each call |
| Real classification quality | **Open** | Needs an API key, then an evaluation set |

## Built

- Federal Reserve archive, collecting every 15 minutes.
- Cleaning, story clustering, keyword relevance and instrument linking.
- Claude Haiku classifier with a strict schema, prompt version, model and cost recorded on each call.
- News screen and `GET /api/v1/news`.

Without `ANTHROPIC_API_KEY`, everything still runs and items show as not classified. No money can be spent.

## Injection Defences

| Attack | Defence | Tested |
|---|---|---|
| Article tells the model to change its answer | Text sits in an untrusted block, and the prompt forbids following it | Prompt reviewed. Real model behaviour is untested |
| Article closes its block early | Angle brackets are neutralised | Yes |
| Model is tricked into adding a trade | The schema has no such field, and extra fields are refused | Yes |
| Model returns prose or links | Refused, and usage is still recorded | Yes |
| Hostile XML feed | `defusedxml` refuses entity attacks | Yes |
| Hostile headline in the browser | Rendered as text, and only https links become clickable | Yes |
| Article URL used to reach internal services | Article pages are never fetched | Yes |

Even a fully successful injection can only produce wrong labels, and those reach no trading code today.

## Defect Found

SDK tests first reached the real Anthropic API, because the SDK uses a separate `httpx2` client that the mock did not cover. Only the literal string `test-key` was sent. Tests now use a local transport, and a guard fails any test that tries to reach an outside host.

## Not Done

- Paid news vendors. The owner must confirm terms and cost first.
- BLS and other economic calendar dates, so `economic_events` is empty.
- Exchange announcements, because no official API was found.
- "Already reflected in the market" analysis, which belongs to Phase 7.
- Classification evaluation set.
