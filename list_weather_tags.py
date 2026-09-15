"""
Diagnostic: there is no WEATHER category in Polymarket's leaderboard API
(confirmed: discover_top50_alltime.py's --category only accepts OVERALL,
POLITICS, SPORTS, CRYPTO, CULTURE, ECONOMICS, TECH, FINANCE). To test a
weather-consensus strategy we'd need the same workaround built for sports
(see list_sport_tags.py / config.SPORT_TAG_SLUGS): find the real Gamma tag(s)
for weather markets, then screen a broad wallet pool (e.g. OVERALL) filtered
down to just weather-tagged markets, instead of pulling wallets from a
leaderboard category that doesn't exist.

This script pulls the full /tags list and prints every tag whose slug or
label looks weather-related, so we can find the actual tag_id(s) to build a
sport_filter.py-style MultiSportFilter equivalent for weather.

Usage:
    python list_weather_tags.py
"""
import requests

GAMMA_API = "https://gamma-api.polymarket.com"

WEATHER_KEYWORDS = [
    "weather", "temperature", "temp", "rain", "rainfall", "snow", "snowfall",
    "hurricane", "storm", "tornado", "climate", "heat", "cold", "wind",
    "precipitation", "drought", "flood", "typhoon", "cyclone", "el-nino",
    "la-nina", "noaa", "celsius", "fahrenheit",
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
            if any(kw in slug or kw in label for kw in WEATHER_KEYWORDS):
                found.append(tag)

        if len(page) < page_size:
            break
        offset += page_size

    print(f"{len(found)} weather-related tags found:\n")
    for tag in sorted(found, key=lambda t: (t.get("label") or "")):
        print(f"  id={tag.get('id'):<8} slug={tag.get('slug'):<25} label={tag.get('label')}")

    if not found:
        print("No weather tags found at all — Polymarket likely doesn't have "
              "enough weather market volume to build a leaderboard category "
              "or a dedicated tag around. If so, this domain isn't worth "
              "pursuing for a whale-consensus strategy.")


if __name__ == "__main__":
    main()
