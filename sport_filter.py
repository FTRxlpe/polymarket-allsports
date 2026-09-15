"""
Determines which market slugs currently belong to a given sport (e.g. nba,
tennis), using Polymarket's official tag system via the Gamma API.

IMPORTANT: the Gamma /events endpoint filters by *numeric* `tag_id`, not by
a tag slug string. An earlier version of this file passed `tag=<slug>` as
the query param, which Gamma silently ignored — it returned the same
generic "top active events" list regardless of the value, which meant the
sport filter wasn't actually filtering anything. This version resolves the
tag slug to its numeric ID first (via GET /tags?slug=...), then filters
events with that ID (GET /events?tag_id=...), which is the officially
documented approach.
"""
import logging
import time
from typing import Optional, Set

import requests

import config

logger = logging.getLogger("sport_filter")

GAMMA_API = "https://gamma-api.polymarket.com"

# Version marker so it's obvious in the logs which version of this file is
# actually running — avoids confusion after multiple zip re-uploads.
_MODULE_VERSION = "sport_filter.py v7 (tag_slug direct query first, then series_id, then tag_id — all sanity-checked)"
logger.info(f"Loaded {_MODULE_VERSION}")


class SportFilter:
    def __init__(self, tag_slug: str = None, refresh_interval_seconds: int = 300,
                 sanity_keywords: Optional[list] = None):
        self.tag_slug = tag_slug or config.SPORT_TAG_SLUG
        self.refresh_interval = refresh_interval_seconds
        # Per-instance override for _sanity_check_slugs, for tags whose slug
        # prefix doesn't literally match the tag name (e.g. tag "formula-one"
        # but slugs prefixed "f1-"). Falls back to config.SANITY_CHECK_KEYWORDS,
        # then to [tag_slug] if neither is set.
        self._sanity_keywords = sanity_keywords
        self._slugs: Set[str] = set()               # active-only, for live trading
        self._historical_slugs: Set[str] = set()     # active + recently closed, for screening
        self._last_refresh = 0.0
        self._last_historical_refresh = 0.0
        self._tag_id: Optional[int] = None
        self._series_id: Optional[str] = None
        self._resolution_mode: Optional[str] = None  # "series" or "tag"
        self.session = requests.Session()

    def _resolve_series_id(self) -> Optional[str]:
        """For automated leagues (NBA, NFL, MLB, NHL...), Polymarket groups
        game markets under a `series_id` rather than a generic content tag.
        GET /sports returns each league's series id. This is the officially
        recommended path for these leagues — falling back to /tags (a
        content tag, not necessarily linked to active game events) can
        silently return zero markets even though the sport is fully active."""
        try:
            resp = self.session.get(f"{GAMMA_API}/sports", timeout=15)
            resp.raise_for_status()
            sports = resp.json()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch /sports metadata: {e}")
            return None

        for entry in sports:
            sport_name = (entry.get("sport") or "").lower()
            if sport_name == self.tag_slug.lower():
                series = entry.get("series")
                if series:
                    logger.info(
                        f"Resolved '{self.tag_slug}' -> series_id={series} via /sports"
                    )
                    return series
        logger.info(
            f"'{self.tag_slug}' not found in /sports (not an automated league "
            f"— e.g. tennis, UFC, golf) — will use tag_id instead."
        )
        return None

    def _resolve_tag_id(self) -> Optional[int]:
        """Look up the numeric tag_id for self.tag_slug. Cached for the life
        of this instance since a sport's tag_id doesn't change."""
        if self._tag_id is not None:
            return self._tag_id

        # Try direct slug lookup first. NOTE: confirmed in practice that
        # Gamma's /tags?slug=X silently ignores the filter for some values
        # and returns an unrelated generic tag instead of erroring or
        # returning empty — so the response must be validated against what
        # was actually asked for, not trusted blindly (this bug used to
        # make every unresolved tag_slug, e.g. "tennis", "sports", collapse
        # onto the same wrong tag_id).
        try:
            resp = self.session.get(
                f"{GAMMA_API}/tags", params={"slug": self.tag_slug}, timeout=15
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                entry = results[0] if isinstance(results, list) else results
                returned_slug = (entry.get("slug") or "").lower()
                if entry.get("id") and returned_slug == self.tag_slug.lower():
                    self._tag_id = int(entry["id"])
                    logger.info(f"Resolved tag '{self.tag_slug}' -> tag_id={self._tag_id}")
                    return self._tag_id
                else:
                    logger.warning(
                        f"/tags?slug={self.tag_slug} returned a mismatched "
                        f"tag (slug={returned_slug!r}, id={entry.get('id')}) "
                        f"— Gamma's slug filter appears to be ignored here; "
                        f"falling back to a full tag-list scan instead."
                    )
        except (requests.RequestException, ValueError, KeyError) as e:
            logger.warning(f"Direct tag slug lookup failed for '{self.tag_slug}': {e}")

        # Fallback: paginate through /tags and match slug or label
        # case-insensitively (some sport tags may not resolve via ?slug=).
        offset = 0
        page_size = 100
        for _ in range(10):  # up to 1000 tags scanned, generous ceiling
            try:
                resp = self.session.get(
                    f"{GAMMA_API}/tags",
                    params={"limit": page_size, "offset": offset},
                    timeout=15,
                )
                resp.raise_for_status()
                page = resp.json()
            except requests.RequestException as e:
                logger.warning(f"Tag listing failed at offset {offset}: {e}")
                break

            if not page:
                break

            for tag in page:
                slug = (tag.get("slug") or "").lower()
                label = (tag.get("label") or "").lower()
                if slug == self.tag_slug.lower() or label == self.tag_slug.lower():
                    self._tag_id = int(tag["id"])
                    logger.info(
                        f"Resolved tag '{self.tag_slug}' -> tag_id={self._tag_id} "
                        f"(via full tag list scan, label='{tag.get('label')}')"
                    )
                    return self._tag_id

            offset += page_size

        logger.error(
            f"Could not resolve a tag_id for '{self.tag_slug}' — the sport "
            f"filter will not match any markets until this is fixed. Check "
            f"the exact tag slug/label via https://gamma-api.polymarket.com/tags"
        )
        return None

    def _refresh(self, include_closed: bool = False):
        if include_closed:
            self._last_historical_refresh = time.time()
        else:
            self._last_refresh = time.time()

        # Method 1 (tried first): direct tag_slug query. Simplest and most
        # direct — no numeric ID resolution step means no opportunity for
        # Polymarket's /sports or /tags metadata to point us at a
        # mislabeled series_id or tag_id (observed in practice for 'ufc').
        if self._resolution_mode in (None, "slug"):
            all_slugs = self._fetch_all_slugs(tag_slug=self.tag_slug, include_closed=include_closed)
            if all_slugs and self._sanity_check_slugs(all_slugs):
                self._resolution_mode = "slug"
                self._store_result(all_slugs, include_closed, "tag_slug")
                return
            elif self._resolution_mode == "slug":
                # Was working before, now returning nothing — treat as
                # transient, don't permanently abandon this mode.
                logger.warning(
                    f"tag_slug='{self.tag_slug}' query returned no valid "
                    f"results this time — will retry next interval."
                )
                return
            else:
                logger.info(
                    f"tag_slug='{self.tag_slug}' direct query didn't pan out "
                    f"(0 results or failed sanity check) — trying series_id/tag_id instead."
                )

        # Method 2: series_id (for automated leagues like NBA, NFL, MLB, NHL)
        if self._resolution_mode is None:
            series_id = self._resolve_series_id()
            if series_id:
                self._series_id = series_id
                self._resolution_mode = "series"
            else:
                self._resolution_mode = "tag"

        if self._resolution_mode == "series":
            all_slugs = self._fetch_all_slugs(series_id=self._series_id, include_closed=include_closed)
            if not all_slugs:
                logger.warning(
                    f"series_id={self._series_id} for '{self.tag_slug}' returned "
                    f"0 events — falling back to tag_id resolution instead."
                )
                self._resolution_mode = "tag"
            elif not self._sanity_check_slugs(all_slugs):
                logger.warning(
                    f"series_id={self._series_id} for '{self.tag_slug}' returned "
                    f"{len(all_slugs)} slugs but NONE contain '{self.tag_slug}' in "
                    f"their name (sample: {sorted(all_slugs)[:3]}) — this series_id "
                    f"looks mislabeled. Falling back to tag_id resolution instead."
                )
                self._resolution_mode = "tag"
                all_slugs = set()
            else:
                self._store_result(all_slugs, include_closed, "series_id")
                return

        # Method 3 (last resort): numeric tag_id resolution
        if self._resolution_mode == "tag":
            tag_id = self._resolve_tag_id()
            if tag_id is None:
                logger.error(
                    f"Every resolution method failed for '{self.tag_slug}' "
                    f"(tag_slug query, series_id, tag_id). Consider hardcoding "
                    f"a known-good filter manually in config.py."
                )
                return
            all_slugs = self._fetch_all_slugs(tag_id=tag_id, include_closed=include_closed)
            if all_slugs and not self._sanity_check_slugs(all_slugs):
                logger.error(
                    f"tag_id={tag_id} for '{self.tag_slug}' also returned "
                    f"{len(all_slugs)} slugs with NONE containing '{self.tag_slug}' "
                    f"(sample: {sorted(all_slugs)[:5]}). All automated resolution "
                    f"methods are mislabeled for this sport on Polymarket's side. "
                    f"Verify manually at https://gamma-api.polymarket.com/tags?limit=500 "
                    f"and consider hardcoding the right tag_id in config.py instead."
                )
                all_slugs = set()

        self._store_result(all_slugs, include_closed, self._resolution_mode)

    def _store_result(self, all_slugs: Set[str], include_closed: bool, mode: str):
        label = "active+recent" if include_closed else "active"
        if all_slugs:
            if include_closed:
                self._historical_slugs = all_slugs
            else:
                self._slugs = all_slugs
            logger.info(
                f"Refreshed '{self.tag_slug}' market list "
                f"(mode={mode}, {label}): {len(all_slugs)} slugs"
            )
        else:
            logger.warning(
                f"Gamma API returned 0 {label} '{self.tag_slug}' markets "
                f"(mode={mode}) — keeping previous list. Will retry at the "
                f"next refresh interval ({self.refresh_interval}s) rather "
                f"than immediately."
            )

    def _sanity_check_slugs(self, slugs: Set[str], sample_size: int = 50) -> bool:
        """Quick plausibility check: do at least some of these slugs contain
        an expected keyword? Real Polymarket sport slugs consistently use
        this convention (confirmed empirically: 'ufc-...', 'cfb-...',
        'epl-...', 'nba-...'). If literally none do, something upstream
        resolved to the wrong series/tag.

        Not every domain follows a slug-prefix convention (e.g. political
        market slugs are one-off phrases like 'will-trump-win-2024' with no
        shared prefix, and FOMC-related markets say 'fed' rather than
        'fomc'). For those, set config.SANITY_CHECK_KEYWORDS to a list of
        expected substrings, or config.DISABLE_SANITY_CHECK = True to skip
        this check entirely."""
        if getattr(config, "DISABLE_SANITY_CHECK", False):
            return True

        keywords = (self._sanity_keywords
                    or getattr(config, "SANITY_CHECK_KEYWORDS", None)
                    or [self.tag_slug.lower()])
        sample = list(slugs)[:sample_size]
        return any(kw.lower() in s.lower() for s in sample for kw in keywords)

    def _fetch_all_slugs(self, tag_id: int = None, series_id: str = None,
                          tag_slug: str = None,
                          include_closed: bool = False, max_pages: int = 20) -> Set[str]:
        """Paginate /events with tag_slug, tag_id, or series_id as the
        filter, collecting every market slug found.

        include_closed=False (default): only currently active, tradeable
        markets — this is what the live trading path needs.
        include_closed=True: ALSO fetches recently closed/settled events
        (most recent first), needed for historical wallet screening."""
        all_slugs: Set[str] = set()

        # Active markets (always fetched — needed in both modes)
        offset = 0
        page_size = 100
        for _ in range(max_pages):
            params = {"active": "true", "closed": "false", "limit": page_size, "offset": offset}
            if tag_slug is not None:
                params["tag_slug"] = tag_slug
            if tag_id is not None:
                params["tag_id"] = tag_id
            if series_id is not None:
                params["series_id"] = series_id

            page_events = self._fetch_events_page(params)
            if not page_events:
                break
            for event in page_events:
                for market in event.get("markets", []):
                    slug = market.get("slug")
                    if slug:
                        all_slugs.add(slug)
            if len(page_events) < page_size:
                break
            offset += page_size

        if include_closed:
            offset = 0
            for _ in range(max_pages):
                params = {
                    "closed": "true",
                    "limit": page_size,
                    "offset": offset,
                    "order": "startDate",
                    "ascending": "false",
                }
                if tag_slug is not None:
                    params["tag_slug"] = tag_slug
                if tag_id is not None:
                    params["tag_id"] = tag_id
                if series_id is not None:
                    params["series_id"] = series_id

                page_events = self._fetch_events_page(params)
                if not page_events:
                    break
                for event in page_events:
                    for market in event.get("markets", []):
                        slug = market.get("slug")
                        if slug:
                            all_slugs.add(slug)
                if len(page_events) < page_size:
                    break
                offset += page_size

        return all_slugs

    def _fetch_events_page(self, params: dict):
        """One page of /events with the given params, retrying with backoff
        on 429. Returns None if it gives up after retries."""
        delay = 2.0
        for attempt in range(4):
            try:
                resp = self.session.get(f"{GAMMA_API}/events", params=params, timeout=15)
                if resp.status_code == 429:
                    logger.warning(
                        f"Rate limited (429) fetching events (offset={params.get('offset')}), "
                        f"retrying in {delay:.1f}s (attempt {attempt + 1}/4)"
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                logger.warning(f"Failed to fetch events page: {e}")
                return None
        logger.warning(f"Giving up on events page (offset={params.get('offset')}) after repeated 429s")
        return None

    def is_match(self, slug: str) -> bool:
        """For LIVE TRADING: is this slug a currently active/tradeable
        market for this sport? Only considers active markets."""
        if time.time() - self._last_refresh > self.refresh_interval:
            self._refresh(include_closed=False)
        return slug in self._slugs

    def is_match_historical(self, slug: str) -> bool:
        """For WALLET SCREENING: was this slug ever an active market for
        this sport, including ones that have since closed/resolved? A
        wallet's trade on a match from 3 weeks ago should still count
        toward its activity/win-rate stats even though that match's market
        is no longer active."""
        if time.time() - self._last_historical_refresh > self.refresh_interval:
            self._refresh(include_closed=True)
        return slug in self._historical_slugs or slug in self._slugs


class MultiSportFilter:
    """Unions several single-tag SportFilters.

    Confirmed via list_sport_tags.py against the live Gamma API: Polymarket
    has NO generic umbrella tag for "all sports combined" — the closest
    match for tag_slug="sports" is "fox-sports" (a broadcaster tag, not
    sport content), and the numeric tag_id it was resolving to pointed at
    unrelated non-sports markets. So "all sports" has to be built as a
    union of the real per-sport tags (each of which already resolves
    correctly and independently, the same way tennis/nba/ufc's single-tag
    bots do) rather than one tag lookup.

    Coverage is necessarily partial for domains Polymarket tags per
    competition rather than per sport (soccer especially: dozens of
    country/competition-specific tags like "soccer-auc", "champions-league"
    instead of one "soccer" tag) — config.SPORT_TAG_SLUGS should be
    refined/expanded based on what list_sport_tags.py finds over time.
    """

    def __init__(self, tag_slugs, refresh_interval_seconds: int = 300):
        """`tag_slugs`: list of either a plain tag slug string (sanity check
        defaults to expecting that slug itself in results), or a
        (tag_slug, [expected_keywords]) tuple for tags whose real market
        slug prefix differs from the tag name."""
        self._filters = []
        for entry in tag_slugs:
            if isinstance(entry, (tuple, list)):
                slug, keywords = entry[0], entry[1]
            else:
                slug, keywords = entry, None
            self._filters.append(SportFilter(
                tag_slug=slug, refresh_interval_seconds=refresh_interval_seconds,
                sanity_keywords=keywords,
            ))

    def is_match(self, slug: str) -> bool:
        return any(f.is_match(slug) for f in self._filters)

    def is_match_historical(self, slug: str) -> bool:
        return any(f.is_match_historical(slug) for f in self._filters)
