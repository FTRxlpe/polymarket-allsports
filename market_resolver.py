"""
Resolves a (market_slug, outcome_name) pair to the specific CLOB token_id
needed to place an order, using Polymarket's public Gamma API.

No API key required — this is public market metadata.
"""
import logging
import time
from typing import Optional, Dict

import requests

logger = logging.getLogger("market_resolver")

GAMMA_API = "https://gamma-api.polymarket.com"

# Cache resolved markets briefly so we don't hammer the API on every signal.
_CACHE_TTL_SECONDS = 300
_cache: Dict[str, tuple] = {}  # slug -> (timestamp, market_json)


class MarketResolver:
    def __init__(self):
        self.session = requests.Session()

    def _get_market(self, slug: str) -> Optional[dict]:
        cached = _cache.get(slug)
        if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

        try:
            resp = self.session.get(
                f"{GAMMA_API}/markets", params={"slug": slug}, timeout=10
            )
            resp.raise_for_status()
            results = resp.json()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch market metadata for {slug}: {e}")
            return None

        if not results:
            logger.warning(f"No market found on Gamma API for slug={slug}")
            return None

        market = results[0]
        _cache[slug] = (time.time(), market)
        return market

    def resolve_token_id(self, slug: str, outcome: str) -> Optional[str]:
        """
        Returns the CLOB token_id for the given outcome of a market, or None
        if it can't be confidently resolved (in which case the caller should
        skip the trade rather than guess).
        """
        market = self._get_market(slug)
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

    def is_market_active(self, slug: str) -> bool:
        """Safety check: refuse to trade a closed/inactive market."""
        market = self._get_market(slug)
        if not market:
            return False
        return bool(market.get("active")) and not bool(market.get("closed"))
