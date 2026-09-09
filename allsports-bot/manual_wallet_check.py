"""
Screens candidate addresses YOU supply in a text file, one per line.
For automatic discovery from Polymarket's own leaderboard instead, use
auto_discover_wallets.py.

Usage:
    python manual_wallet_check.py candidates.txt
"""
import sys
import time

import config
from wallet_screening import screen_wallet, MIN_BUYS, MIN_WIN_RATE, LOOKBACK_WEEKS


def main():
    if len(sys.argv) != 2:
        print("Usage: python manual_wallet_check.py candidates.txt")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        candidates = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    print(f"Screening {len(candidates)} candidate wallets against:")
    print(f"  - >= {MIN_BUYS} {config.SPORT_TAG_SLUG} buys in the last {LOOKBACK_WEEKS} weeks")
    print(f"  - >= {MIN_WIN_RATE:.0%} win rate on resolved positions\n")

    qualified = []
    for addr in candidates:
        result = screen_wallet(addr)
        status = "QUALIFIES" if result["qualifies"] else "does not qualify"
        wr_str = f"{result['win_rate']:.1%}" if result["win_rate"] is not None else "n/a (no resolved markets yet)"
        print(
            f"{addr}: {status} — {result['buys_last_10w']} buys/10w, "
            f"win rate {wr_str} ({result['wins']}W/{result['losses']}L)"
        )
        if result["qualifies"]:
            qualified.append(result)
        time.sleep(0.5)

    print(f"\n{len(qualified)}/{len(candidates)} candidates qualify.")
    if qualified:
        print("\nAdd these to WATCHED_WALLETS in config.py:")
        for r in qualified:
            print(f'    "nickname-here": "{r["address"]}",')


if __name__ == "__main__":
    main()
