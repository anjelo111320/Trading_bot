"""Deterministic relevance. Irrelevant items never reach a paid model call."""

from dataclasses import dataclass
from typing import Final

from trading_intel.news_intelligence.normalize import fingerprint

EVENT_KEYWORDS: Final[dict[str, frozenset[str]]] = {
    "monetary_policy": frozenset(
        {"fomc", "federal", "rate", "rates", "monetary", "powell", "minutes", "dot"}
    ),
    "inflation": frozenset({"cpi", "inflation", "pce", "prices"}),
    "employment": frozenset({"employment", "payrolls", "jobs", "unemployment", "labor"}),
    "regulation": frozenset({"sec", "regulation", "regulatory", "cftc", "enforcement", "bill"}),
    "geopolitical": frozenset({"war", "sanctions", "tariff", "tariffs", "conflict"}),
    "exchange_announcement": frozenset({"listing", "delisting", "binance", "coinbase"}),
    "network_incident": frozenset({"outage", "halted", "fork", "congestion"}),
    "token_unlock": frozenset({"unlock", "unlocks", "vesting"}),
    "security_incident": frozenset({"hack", "exploit", "breach", "stolen", "drained"}),
}
# Names for each traded coin, keyed by its base asset, with its perpetual's symbol so exchange
# notices such as "Binance Futures Will Launch ZECUSDT" match. "Binance" alone names the
# exchange, not BNB, so it is left out.
COIN_NAMES: Final[dict[str, frozenset[str]]] = {
    "BTC": frozenset({"bitcoin", "btc", "btcusdt"}),
    "ETH": frozenset({"ethereum", "ether", "eth", "ethusdt"}),
    "SOL": frozenset({"solana", "sol", "solusdt"}),
    "XRP": frozenset({"xrp", "ripple", "xrpusdt"}),
    "BNB": frozenset({"bnb", "bnbusdt"}),
    "DOGE": frozenset({"dogecoin", "doge", "dogeusdt"}),
    "ZEC": frozenset({"zcash", "zec", "zecusdt"}),
    "1000PEPE": frozenset({"pepe", "1000pepe", "1000pepeusdt", "pepeusdt"}),
}
CRYPTO: Final = frozenset({"crypto", "cryptocurrency", "stablecoin", "stablecoins"})
MACRO_EVENTS: Final = frozenset({"monetary_policy", "inflation", "employment", "geopolitical"})


@dataclass(frozen=True)
class Relevance:
    event_hint: str | None
    assets: dict[str, float]

    @property
    def is_relevant(self) -> bool:
        return bool(self.assets)


def assess_relevance(headline: str, snippet: str | None) -> Relevance:
    """Direct mentions score high. General crypto and macro news reach BTC and ETH, lower."""
    words = fingerprint(f"{headline} {snippet or ''}")
    hits = {name: len(words & keys) for name, keys in EVENT_KEYWORDS.items()}
    best = max(hits, key=lambda name: hits[name])
    hint = best if hits[best] else None

    assets = {asset: 0.9 for asset, names in COIN_NAMES.items() if words & names}
    if not assets and words & CRYPTO:
        assets = {"BTC": 0.6, "ETH": 0.6}
    if not assets and hint in MACRO_EVENTS:
        assets = {"BTC": 0.4, "ETH": 0.4}
    return Relevance(hint, assets)
