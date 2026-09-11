"""
Standalone diagnostic: looks up ONE market slug via market_resolver.py's real
lookup path (same one backtest.py / resolution_watcher.py use) and prints
exactly what it found — whether /events or /markets returned anything,
closed/active status, and outcomes/outcomePrices. Use this to debug why a
specific slug shows up as "unresolved/unknown" in a backtest.

Usage:
    python debug_market_lookup.py <market-slug>
"""
import json
import sys

from market_resolver import MarketResolver, get_winning_outcome


def main():
    if len(sys.argv) != 2:
        print("Usage: python debug_market_lookup.py <market-slug>")
        sys.exit(1)

    slug = sys.argv[1]
    resolver = MarketResolver()

    print(f"Trying /events?slug={slug} ...")
    market = resolver._get_market_via_events(slug)
    print(f"  -> {'FOUND' if market else 'not found'}")

    if not market:
        print(f"\nTrying /markets?slug={slug} ...")
        market = resolver._get_market_via_markets_endpoint(slug)
        print(f"  -> {'FOUND' if market else 'not found'}")

    if not market:
        print(f"\nNEITHER endpoint found a market for slug={slug!r}.")
        print("This is why backtest.py / resolution_watcher.py report it as unresolved.")
        sys.exit(0)

    print("\n=== Raw market fields relevant to resolution ===")
    print(f"slug: {market.get('slug')}")
    print(f"question: {market.get('question')}")
    print(f"active: {market.get('active')}")
    print(f"closed: {market.get('closed')}")
    print(f"outcomes: {market.get('outcomes')}")
    print(f"outcomePrices: {market.get('outcomePrices')}")

    if not market.get("closed"):
        print("\n-> Market is not 'closed' yet on Gamma's side, so it will "
              "always show as unresolved regardless of real-world outcome.")
    else:
        winner = get_winning_outcome(market)
        if winner is None:
            print("\n-> Market IS closed, but outcomePrices aren't confidently "
                  "settled yet (max price < 0.9) — get_winning_outcome() "
                  "returns None, so this still counts as 'unresolved'.")
        else:
            print(f"\n-> Resolved winner: {winner!r}")


if __name__ == "__main__":
    main()
