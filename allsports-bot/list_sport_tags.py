"""
Diagnostic: the 'sports' umbrella tag_slug in config.py resolves to a
tag_id (101867 as of this writing) that returns unrelated, non-sports
markets from Gamma's /events endpoint — sport_filter.py's sanity check
correctly rejects it, but that means the "all sports combined" filter
currently matches ZERO markets, so no wallet's trades ever count.

This script pulls the full /tags list and prints every tag whose slug or
label looks sport-related, so we can find the *actual* correct tag_id (or
confirm there isn't a single umbrella one and we need to union several
per-sport tags instead).

Usage:
    python list_sport_tags.py
"""
import requests

GAMMA_API = "https://gamma-api.polymarket.com"

SPORT_KEYWORDS = [
    "sport", "nba", "nfl", "mlb", "nhl", "ufc", "mma", "tennis", "soccer",
    "football", "basketball", "baseball", "hockey", "golf", "boxing", "f1",
    "formula", "cricket", "rugby", "nascar", "esports", "epl", "champions",
    "olympic",
]


def main():
    offset = 0
    page_size = 100
    found = []

    for _ in range(20):  # up to 2000 tags
        resp = requests.get(
            f"{GAMMA_API}/tags", params={"limit": page_size, "offset": offset}, timeout=15
        )
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break

        for tag in page:
            slug = (tag.get("slug") or "").lower()
            label = (tag.get("label") or "").lower()
            if any(kw in slug or kw in label for kw in SPORT_KEYWORDS):
                found.append(tag)

        if len(page) < page_size:
            break
        offset += page_size

    print(f"{len(found)} sport-related tags found:\n")
    for tag in sorted(found, key=lambda t: (t.get("label") or "")):
        print(f"  id={tag.get('id'):<8} slug={tag.get('slug'):<25} label={tag.get('label')}")


if __name__ == "__main__":
    main()
