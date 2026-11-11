# Crypto News Provider Pack

Date: 2026-11-11
Covers: The free, real-time crypto news sources checked at the owner's request (D052), and the terms that decided each one.
Rules: under D032, each source's terms are read before collection starts. Under D006, everything stays on this computer for the owner, and article pages are never fetched.

## Decision Per Source

| Source | Access | Freshness, measured 2026-11-11 | Terms | Result |
|---|---|---|---|---|
| Finnhub crypto news | REST, free personal key | Not measured: the `.env` entry was empty | Personal use only, no sharing, data deleted when the plan ends | **Built**, off until `FINNHUB_API_KEY` is set |
| Binance announcements | Official CMS WebSocket, needs an API key | Pushed when published | Binance's documented API for account holders | **Built**, off until a read-only key is set |
| CoinDesk RSS | Public feed | Newest item 10.2 hours old | Forbids automated access | Refused |
| Cointelegraph RSS | Public feed | Newest item 47 minutes old | Forbids automated scraping, content pipelines and AI operation without consent | Refused |
| The Block RSS | Public feed | Newest item 25 minutes old | Feed only in an RSS reader; forbids AI processing | Refused |
| Decrypt RSS | Public feed | Newest item 8.0 hours old | Forbids scraping, caching and archiving | Refused |
| CryptoSlate RSS | Public feed | Newest item 57 minutes old | Forbids bots, caching and mining | Refused |
| NewsData.io | REST, owner's free key | **12.0 hours behind**, every item | "For testing and personal projects" (docs/26) | Not real-time; not collected |
| CryptoPanic | REST | | Free plan ended on 1 April 2026; paid plans from $199 a month | Not free |
| CoinDesk Data API | REST | | Free tier retired in May 2026 | Not free |
| Alpaca news (Benzinga) | WebSocket | | Whether the free plan includes news was not stated | Not verified |

## Terms Relied On

### Finnhub

[Terms of service](https://finnhub.io/terms-of-service), read 2026-11-11.

| Clause | Text |
|---|---|
| Personal use | "All plan listed on Finnhub website is strictly for personal use unless explicitly stated otherwise." |
| Business | "Personal plan can't be used by any business even internally without a written approval." |
| Sharing | "You hereby agree to not redistribute or share access to data or derived results" |
| Ending | "All data must be deleted should your subscription to that data ends." The provider row has `delete_on_termination` set |
| Rate | "There is a 30 API calls/second limit on top of all plan's limit." The collector makes one call every 2 minutes |

The terms say nothing about AI processing. Classification by Claude stays on this computer and is never shared, so it falls within personal use.

### Binance announcements

[Announcement topic](https://developers.binance.com/docs/cms/announcement) and [connection rules](https://developers.binance.com/docs/cms/general-info), read 2026-11-11.

| Item | Detail |
|---|---|
| Endpoint | `wss://api.binance.com/sapi/wss`, topic `com_announcement_en` |
| Signing | The key in the `X-MBX-APIKEY` header, and an HMAC SHA256 signature over `random`, `topic`, `recvWindow` and `timestamp`, sorted by name |
| Connection | At most 24 hours; a ping every 30 seconds, or Binance closes it within a minute |
| Limit | 5 messages a second. "Repeated disconnections may result in IP blocking", so a connection that ends within a minute backs off |
| Payload | `catalogId`, `catalogName`, `publishDate` in milliseconds, `title`, `body` and `disclaimer`. There is no link, so the stored link is the catalogue's list page |
| Gap | Announcements published while the stream is down are not resent |

The key comes from the owner's main Binance account. Before every connection the collector calls `GET /sapi/v1/account/apiRestrictions` and refuses a key with any permission on other than reading, IP restriction and FIX read-only. That includes permissions Binance adds later. A regression test keeps the module to that endpoint and the stream.

### Publisher RSS feeds, refused

Each terms page was read on 2026-11-11.

| Publisher | Quoted terms |
|---|---|
| [CoinDesk](https://www.coindesk.com/terms), effective 2026-10-30 | "You agree that you will not use any robot, spider, scraper, or other automated means to access the Services for any purpose" without express written permission |
| [Cointelegraph](https://cointelegraph.com/terms-and-privacy) | "automated scraping, or creation of independent content pipelines based on Cointelegraph reputation is strictly prohibited". Use "for training, fine-tuning, validation, benchmarking or operation of artificial intelligence systems" needs written consent |
| [The Block](https://www.theblock.co/terms-of-service) | "you may not share that feed or use it in any application other than an RSS feed reader", and no "process the Content using artificial intelligence or machine learning... including to summarize" |
| [Decrypt](https://decrypt.co/terms-of-service), updated 2020-10-12 | No "robots, spiders, scripts... designed to data mine or scrape", and no "cache or archive the Content" |
| [CryptoSlate](https://cryptoslate.com/terms/), updated 2026-10-07 | No "bots, spiders, scripts, automated tools, data-mining systems... to access, copy, extract, monitor" without written permission |

A feed would need each publisher's written permission before it could be collected.

## Behaviour Contract

| Behaviour the collectors rely on | Evidence |
|---|---|
| Finnhub returns a JSON list of items with an integer `id` and a `datetime` in Unix seconds | Finnhub documentation; unit tests use made-up items |
| Finnhub's `minId` returns only items above that id | Finnhub documentation; unit test |
| A Finnhub reply that is not a list, such as an error object, is refused | Unit test |
| Binance pushes `{"type": "DATA", "topic": ..., "data": "<JSON string>"}` | Binance documentation; unit tests use made-up payloads |
| Binance answers a subscription with `{"type": "COMMAND", ...}`, which is ignored | Binance documentation; unit test |

Neither key was available on 2026-11-11, so neither source has been probed live. The first run with each key is that probe: the ingestor logs `finnhub_news_failed` with the HTTP status, or `binance_announcements_refused` with the reason.
