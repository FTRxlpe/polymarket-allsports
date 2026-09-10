"""
Quick diagnostic: builds the historical UFC slug set the same way
wallet_screening.py does, then checks whether specific slugs we KNOW were
traded (from check_wallet_activity.py output) are actually in it. If they
aren't, prints samples of what IS in the set so we can spot the mismatch.

Usage:
    python debug_slug_match.py
"""
from sport_filter import SportFilter
import config

KNOWN_TRADED_SLUGS = [
    "ufc-chi1-joe-2026-08-15",
    "ufc-nei-ram2-2026-08-15",
    "ufc-isl-ian1-2026-08-15",
    "ufc-dar3-yad-2026-08-08",
    "ufc-ama3-ale57-2026-08-08",
    "ufc-tre6-kur2-2026-09-05",
    "ufc-mic32-nur1-2026-09-05",
    "ufc-ale7-sum-2026-08-29",
    "ufc-dan6-salpar-2026-09-05-totals-2pt5",
]

sf = SportFilter(tag_slug=config.SPORT_TAG_SLUG)

print(f"Building historical slug set for '{config.SPORT_TAG_SLUG}'...\n")
matched = 0
for slug in KNOWN_TRADED_SLUGS:
    result = sf.is_match_historical(slug)
    print(f"  {'MATCH' if result else 'no match'}: {slug}")
    if result:
        matched += 1

print(f"\n{matched}/{len(KNOWN_TRADED_SLUGS)} known-traded slugs matched.")
print(f"Total slugs in the historical set: {len(sf._historical_slugs) + len(sf._slugs)}")

print("\nSample of 20 slugs actually in the historical set:")
all_found = sorted(sf._historical_slugs | sf._slugs)
for s in all_found[:20]:
    print(f"  {s}")

# Also show any slug in the set that starts with "ufc" to compare naming patterns
ufc_prefixed = [s for s in all_found if s.startswith("ufc")]
print(f"\n{len(ufc_prefixed)} slugs in the set start with 'ufc':")
for s in ufc_prefixed[:20]:
    print(f"  {s}")
