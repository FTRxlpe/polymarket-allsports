"""
Resolves a (market_slug, outcome_name) pair to the specific CLOB token_id
needed to place an order, using Polymarket's public Gamma API.

IMPORTANT: /markets?slug=X is documented to return an empty result for many
real, valid markets — especially individual sub-markets belonging to a
multi-outcome event (e.g. "epl-ars-che-2026-09-06-ars", one of several
markets under the "epl-ars-che-2026-09-06" event). This is a known Polymarket
API quirk, not something specific to our code — confirmed by multiple
independent bug reports against the same endpoint.

The reliable path is /events?slug=X — but X must be the EVENT's own slug,
not the market's. A trade record from the Data API carries both fields
("slug" for the market, "eventSlug" for its parent event) and they are
routinely different strings (e.g. market slug
"us-iran-hormuz-agreement-by-september-15" vs. eventSlug
"us-iran-hormuz-agreement-byptptpt-20260803235957575") — confirmed by
inspecting raw trade JSON after most lookups were silently failing.
Querying /events with the market's own slug instead of eventSlug returns an
empty array even though the market genuinely exists, which is why so many
markets were showing up as "No market found" throughout screening,
discovery and backtesting. Every caller that has a raw trade dict should
pass its "eventSlug" through as `event_slug` here; without it, this falls
back to trying the market slug against /events too (works for single-market
events where the two happen to coincide) and then to /markets?slug=.

No API key required — this is public market metadata.
"""
import json
import logging
import time
from typing import Optional, Dict

import requests

logger = logging.getLogger("market_resolver")

GAMMA_API = "https://gamma-api.polymarket.com"

# Cache resolved markets briefly so we don't hammer the API on every signal.
_CACHE_TTL_SECONDS = 300
_cache: Dict[str, tuple] = {}  # slug -> (timestamp, market_json)


def get_winning_outcome(market: dict):
    """There is no "winningOutcome" field in Polymarket's Gamma API — the
    winner of a resolved market is determined from outcomePrices, which
    settle to ~1.0 for the winning outcome and ~0.0 for the rest once
    resolution completes. Returns None if not confidently resolved yet."""
    outcomes = market.get("outcomes")
    prices = market.get("outcomePrices")
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    if isinstance(prices, str):
        prices = json.loads(prices)
    if not outcomes or not prices or len(outcomes) != len(prices):
        return None
    try:
        prices_f = [float(p) for p in prices]
    except (TypeError, ValueError):
        return None
    winner_idx = prices_f.index(max(prices_f))
    if prices_f[winner_idx] < 0.9:
        return None  # not confidently settled yet, don't guess
    return outcomes[winner_idx]


class MarketResolver:
    def __init__(self):
        self.session = requests.Session()

    def _fetch_with_retry(self, url: str, params: dict, max_retries: int = 3):
        """GET with 429 retry-with-backoff. Returns parsed JSON or None."""
        delay = 1.0
        for attempt in range(max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=10)
                if resp.status_code == 429:
                    logger.warning(f"Rate limited (429) on {url} {params}, retrying in {delay:.1f}s")
                    time.sleep(delay)
                    delay *= 2
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                logger.warning(f"Request failed for {url} {params}: {e}")
                return None
        logger.warning(f"Giving up on {url} {params} after repeated 429s")
        return None

    def _get_market_via_events(self, slug: str, event_slug: str = None) -> Optional[dict]:
        """Primary path: fetch the event containing this market and pull the
        specific market out of its nested markets array. Works even for
        sub-markets that /markets?slug= fails to find.

        `event_slug` (from a raw trade's "eventSlug" field) is queried first
        when given — the event's own slug is frequently a different string
        from the market's slug, and /events?slug= only matches on the
        event's slug, not any of its markets'. Falls back to trying the
        market's own slug against /events (works when they coincide, e.g.
        single-market events)."""
        query_slugs = [s for s in (event_slug, slug) if s]
        for query_slug in query_slugs:
            events = self._fetch_with_retry(f"{GAMMA_API}/events", {"slug": query_slug})
            if not events:
                continue
            for event in events:
                for market in event.get("markets", []):
                    if market.get("slug") == slug:
                        return market
                # Single-market event where only the event matched by slug —
                # return its one market as a reasonable fallback.
                if len(event.get("markets", [])) == 1:
                    return event["markets"][0]

        return None

    def _get_market_via_markets_endpoint(self, slug: str) -> Optional[dict]:
        """Fallback path: the old /markets?slug= lookup. Kept as a fallback
        since it does work for some markets, just not reliably for all."""
        results = self._fetch_with_retry(f"{GAMMA_API}/markets", {"slug": slug})
        if results:
            return results[0]
        return None

    def _get_market(self, slug: str, event_slug: str = None) -> Optional[dict]:
        cached = _cache.get(slug)
        if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

        market = self._get_market_via_events(slug, event_slug)
        if not market:
            market = self._get_market_via_markets_endpoint(slug)

        if not market:
            logger.warning(
                f"No market found on Gamma API for slug={slug} "
                f"(tried /events with event_slug={event_slug!r} and slug={slug!r}, and /markets)"
            )
            # Cache the miss too (shorter TTL than a hit) — without this,
            # the same unresolvable slug (typically a deep prop/total
            # sub-market /events can't find) gets re-fetched from scratch
            # every time a different wallet's screening touches it, which
            # in practice meant thousands of redundant repeated lookups.
            _cache[slug] = (time.time(), None)
            return None

        _cache[slug] = (time.time(), market)
        return market

    def resolve_token_id(self, slug: str, outcome: str, event_slug: str = None) -> Optional[str]:
        """
        Returns the CLOB token_id for the given outcome of a market, or None
        if it can't be confidently resolved (in which case the caller should
        skip the trade rather than guess).
        """
        market = self._get_market(slug, event_slug)
        if not market:
            return None

        outcomes = market.get("outcomes")
        token_ids = market.get("clobTokenIds")

        # Gamma API sometimes returns these as JSON-encoded strings
        import json as _json
        if isinstance(outcomes, str):
            outcomes = _json.loads(outcomes)
        if isinstance(token_ids, str):
            token_ids = _json.loads(token_ids)

        if not outcomes or not token_ids or len(outcomes) != len(token_ids):
            logger.warning(f"Malformed outcomes/tokenIds for {slug}: {market}")
            return None

        # Exact match first, then case-insensitive fallback
        if outcome in outcomes:
            idx = outcomes.index(outcome)
        else:
            lowered = [o.lower() for o in outcomes]
            if outcome.lower() in lowered:
                idx = lowered.index(outcome.lower())
            else:
                logger.warning(
                    f"Outcome '{outcome}' not found in market {slug} "
                    f"(available: {outcomes}) — refusing to guess."
                )
                return None

        token_id = token_ids[idx]
        logger.info(f"Resolved {slug}/{outcome} -> token_id={token_id}")
        return token_id

    def is_market_active(self, slug: str, event_slug: str = None) -> bool:
        """Safety check: refuse to trade a closed/inactive market."""
        market = self._get_market(slug, event_slug)
        if not market:
            return False
        return bool(market.get("active")) and not bool(market.get("closed"))
