"""
Diagnostic tool: shows the raw recent trades of specific wallets, with NO
sport filtering applied. Useful to answer "what are these wallets actually
trading right now?" and to discover the real slug/tag patterns Polymarket
uses for futures/prop markets (vs. game markets), which the sport filter
can then be tuned against.

Usage:
    python check_wallet_activity.py 0xaddress1 0xaddress2 ...

    # Or check the wallets found by a previous auto_discover_wallets.py run:
    python check_wallet_activity.py --from-file found_wallets.txt
"""
import sys
import re
import time
from datetime import datetime, timezone

import requests

import config

# The wallets identified as "sports whales" in earlier discovery runs —
# used as a default if no addresses are given on the command line.
KNOWN_WALLETS = {
    "cigarettes": "0xd218e474776403a330142299f7796e8ba32eb5c9",
    "flawfence": "0x23d81ba9371e576015c1e562db09c689f56b0288",
    "surfandturf": "0x9f2fe025f84839ca81dd8e0338892605702d2ca8",
    "whale-424779": "0x42477970683d4d0a52ec7082fee5d760cc5591c4",
    "sleepy-panda": "0xa49becb692927d455924583b5e3e5788246f4c40",
    "hansama231": "0x381b9294c1b95b61d018ff56312fbcc4897c4d74",
    "Jsram": "0x83720820a8aa6c3f20ad71850e7a1a17d16c5223",
}


def fetch_trades(address: str, limit: int = 30) -> list:
    url = f"{config.POLYMARKET_DATA_API}/trades"
    resp = requests.get(url, params={"user": address, "limit": limit}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def parse_addresses_from_file(path: str) -> dict:
    """Pulls "nickname": "0xaddress" pairs out of a found_wallets.txt-style file."""
    wallets = {}
    pattern = re.compile(r'"([^"]+)":\s*"(0x[a-fA-F0-9]{40})"')
    with open(path) as f:
        for line in f:
            m = pattern.search(line)
            if m:
                wallets[m.group(1)] = m.group(2)
    return wallets


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--from-file":
        wallets = parse_addresses_from_file(sys.argv[2])
        if not wallets:
            print(f"No addresses found in {sys.argv[2]}")
            sys.exit(1)
    elif len(sys.argv) > 1:
        wallets = {f"wallet-{i+1}": addr for i, addr in enumerate(sys.argv[1:])}
    else:
        wallets = KNOWN_WALLETS
        print("No addresses given — using the previously-discovered wallets.\n")

    slug_prefixes_seen = {}

    for nickname, address in wallets.items():
        print(f"\n=== {nickname} ({address}) ===")
        try:
            trades = fetch_trades(address)
        except requests.RequestException as e:
            print(f"  Failed to fetch: {e}")
            continue

        if not trades:
            print("  No recent trades found.")
            continue

        for t in trades[:15]:
            slug = t.get("slug") or t.get("market_slug") or "?"
            side = (t.get("side") or "?").upper()
            outcome = t.get("outcome", "?")
            price = t.get("price", "?")
            size = t.get("size", "?")
            ts = t.get("timestamp")
            when = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d") if ts else "?"
            print(f"  [{when}] {side} '{outcome}' @ {price} x{size}  —  {slug}")

            prefix = slug.split("-")[0] if "-" in slug else slug
            slug_prefixes_seen[prefix] = slug_prefixes_seen.get(prefix, 0) + 1

        time.sleep(0.5)

    print("\n\n=== Slug prefixes seen across all wallets (top-level pattern) ===")
    for prefix, count in sorted(slug_prefixes_seen.items(), key=lambda kv: -kv[1]):
        print(f"  {prefix}: {count} trade(s)")


if __name__ == "__main__":
    main()
