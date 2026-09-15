"""
Determines which market slugs currently belong to a given sport (e.g.
tennis), using Polymarket's official tag system via the Gamma API — not a
guessed slug prefix, since sports market slugs are named after
tournaments/matchups and don't follow one fixed pattern.

The set of active slugs for the sport is refreshed periodically and cached,
so the hot path (checking an incoming trade) is a fast in-memory lookup.
"""
import logging
import time
from typing import Set

import requests

import config

logger = logging.getLogger("sport_filter")

GAMMA_API = "https://gamma-api.polymarket.com"


class SportFilter:
    def __init__(self, tag_slug: str = None, refresh_interval_seconds: int = 300):
        self.tag_slug = tag_slug or config.SPORT_TAG_SLUG
        self.refresh_interval = refresh_interval_seconds
        self._slugs: Set[str] = set()
        self._last_refresh = 0.0
        self.session = requests.Session()

    def _refresh(self):
        try:
            resp = self.session.get(
                f"{GAMMA_API}/events",
                params={"tag": self.tag_slug, "active": "true", "closed": "false", "limit": 200},
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json()
        except requests.RequestException as e:
            logger.warning(f"Failed to refresh '{self.tag_slug}' market list: {e}")
            return

        slugs = set()
        for event in events:
            for market in event.get("markets", []):
                slug = market.get("slug")
                if slug:
                    slugs.add(slug)

        if slugs:
            self._slugs = slugs
            self._last_refresh = time.time()
            logger.info(f"Refreshed '{self.tag_slug}' market list: {len(slugs)} active slugs")
        else:
            logger.warning(
                f"Gamma API returned 0 active '{self.tag_slug}' markets — "
                f"keeping previous list ({len(self._slugs)} slugs) to avoid "
                f"blanking out the filter on a transient API hiccup."
            )

    def is_match(self, slug: str) -> bool:
        if time.time() - self._last_refresh > self.refresh_interval:
            self._refresh()
        return slug in self._slugs
