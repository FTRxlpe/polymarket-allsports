"""
Diagnostic: for a given Gamma tag_id (found via list_sport_tags.py), fetch
a handful of real events and print their market slugs — so we know the
ACTUAL slug prefix before adding a tag to config.SPORT_TAG_SLUGS.

Why this matters: sport_filter.py's sanity check expects the tag's own
name to appear as a substring in its markets' slugs (the pattern nba/nfl/
mlb/nhl/ufc/tennis all follow). Some tags almost certainly don't follow
this — e.g. "formula-one" markets are plausibly slugged "f1-..." — and
guessing wrong means the tag silently contributes zero markets instead of
raising an error, which is easy to miss. This script gives ground truth
instead of guessing.

Usage:
    python sample_sport_slugs.py 100280        # formula-one's tag_id
    python sample_sport_slugs.py 1234 636 1355  # multiple tag_ids at once
"""
import sys

import requests

GAMMA_API = "https://gamma-api.polymarket.com"


def sample(tag_id: int, limit: int = 15):
    resp = requests.get(
        f"{GAMMA_API}/events",
        params={"tag_id": tag_id, "limit": limit, "order": "startDate", "ascending": "false"},
        timeout=15,
    )
    resp.raise_for_status()
    events = resp.json()

    slugs = []
    for event in events:
        for market in event.get("markets", []):
            slug = market.get("slug")
            if slug:
                slugs.append(slug)

    print(f"tag_id={tag_id}: {len(events)} events, {len(slugs)} market slugs")
    for s in slugs[:20]:
        print(f"    {s}")
    if not slugs:
        print("    (no active events for this tag_id right now — try closed=true "
              "or a busier tag_id)")
    print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python sample_sport_slugs.py <tag_id> [<tag_id> ...]")
        sys.exit(1)
    for arg in sys.argv[1:]:
        sample(int(arg))


if __name__ == "__main__":
    main()
