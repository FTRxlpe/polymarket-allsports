"""
Automatically discovers candidate whale wallets using Polymarket's own
official leaderboard API (data-api.polymarket.com/v1/leaderboard) — no
scraping, no guessing, no invented addresses.

The leaderboard's "SPORTS" category covers all sports, not tennis
specifically (Polymarket doesn't expose a tennis-only leaderboard), so this
script:
  1. Pulls the top traders by PnL and by Volume, across several time
     windows, from the SPORTS category.
  2. Deduplicates them into one candidate pool.
  3. Runs each candidate through the same screening used for manual
     candidates (wallet_screening.py) — checking their REAL trade history
     for tennis-specific activity and win rate.
  4. Prints the wallets that both (a) rank highly in Polymarket's own
     sports leaderboard AND (b) independently pass the tennis-specific
     activity/win-rate bar — ready to paste into config.py.

Usage:
    python auto_discover_wallets.py
    python auto_discover_wallets.py --top 80 --output found_wallets.txt
"""
import argparse
import logging
import time
from typing import Dict, List

import requests

import config
from wallet_screening import screen_wallet, MIN_BUYS, MIN_WIN_RATE, LOOKBACK_WEEKS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("auto_discover_wallets")

LEADERBOARD_URL = f"{config.POLYMARKET_DATA_API}/v1/leaderboard"


def fetch_leaderboard(order_by: str, time_period: str, limit: int = 50) -> List[dict]:
    """One page of Polymarket's official SPORTS-category leaderboard."""
    params = {
        "category": "SPORTS",
        "timePeriod": time_period,
        "orderBy": order_by,
        "limit": limit,
        "offset": 0,
    }
    try:
        resp = requests.get(LEADERBOARD_URL, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.warning(f"Leaderboard fetch failed ({order_by}/{time_period}): {e}")
        return []


def gather_candidates() -> Dict[str, dict]:
    """Pull several leaderboard slices and dedupe into one candidate pool,
    keyed by lowercased wallet address."""
    candidates: Dict[str, dict] = {}

    slices = [
        ("PNL", "WEEK"),
        ("PNL", "MONTH"),
        ("PNL", "ALL"),
        ("VOL", "WEEK"),
        ("VOL", "MONTH"),
        ("VOL", "ALL"),
    ]

    for order_by, period in slices:
        entries = fetch_leaderboard(order_by, period)
        logger.info(f"Leaderboard SPORTS/{order_by}/{period}: {len(entries)} entries")
        for entry in entries:
            addr = (entry.get("proxyWallet") or "").lower()
            if not addr:
                continue
            if addr not in candidates:
                candidates[addr] = entry
        time.sleep(0.3)

    return candidates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=50, help="Max number of qualified wallets to output")
    parser.add_argument("--output", type=str, default=None, help="Optional file to also write results to")
    parser.add_argument("--min-buys", type=int, default=MIN_BUYS,
                         help=f"Minimum tennis buys in the last {LOOKBACK_WEEKS} weeks to qualify (default {MIN_BUYS})")
    parser.add_argument("--min-winrate", type=float, default=MIN_WIN_RATE,
                         help=f"Minimum win rate (0-1) on resolved tennis positions to qualify (default {MIN_WIN_RATE})")
    parser.add_argument("--fallback-ranked", action="store_true",
                         help="If nothing qualifies, still output the most tennis-active "
                              "candidates found, ranked by activity, instead of nothing")
    parser.add_argument("--delay", type=float, default=1.0,
                         help="Seconds to wait between each wallet screening call, to "
                              "avoid hitting Polymarket's rate limit (default 1.0)")
    args = parser.parse_args()

    print("Fetching Polymarket's official SPORTS leaderboard "
          "(data-api.polymarket.com/v1/leaderboard)...\n")
    candidates = gather_candidates()
    print(f"{len(candidates)} unique candidate wallets found in the sports leaderboard.\n")

    print(f"Screening each one for real tennis activity:")
    print(f"  - >= {args.min_buys} tennis buys in the last {LOOKBACK_WEEKS} weeks")
    print(f"  - >= {args.min_winrate:.0%} win rate on resolved tennis positions\n")

    all_results = []
    qualified = []
    for i, (addr, lb_entry) in enumerate(candidates.items(), 1):
        result = screen_wallet(addr, min_buys=args.min_buys, min_win_rate=args.min_winrate)
        result["leaderboard_username"] = lb_entry.get("userName", "")
        result["leaderboard_pnl"] = lb_entry.get("pnl")
        result["leaderboard_vol"] = lb_entry.get("vol")

        status = "QUALIFIES" if result["qualifies"] else "skip"
        wr_str = f"{result['win_rate']:.1%}" if result["win_rate"] is not None else "n/a"
        print(
            f"[{i}/{len(candidates)}] {addr} ({result['leaderboard_username'] or 'no username'}) "
            f"— {status} — {result['buys_last_10w']} tennis buys/10w, win rate {wr_str}"
        )

        all_results.append(result)
        if result["qualifies"]:
            qualified.append(result)
        time.sleep(args.delay)  # be polite to the public API and avoid 429s

    # Rank qualified wallets by tennis win rate (ties broken by activity)
    qualified.sort(key=lambda r: (r["win_rate"] or 0, r["buys_last_10w"]), reverse=True)
    qualified = qualified[: args.top]

    print(f"\n{len(qualified)} wallets qualify and rank in the top {args.top}.\n")

    result_set = qualified
    if not qualified:
        print(
            f"No wallets passed both bars (>= {args.min_buys} buys, >= "
            f"{args.min_winrate:.0%} win rate). Polymarket's SPORTS "
            f"leaderboard covers all sports, so genuine tennis specialists "
            f"are a small subset — this is a real result, not necessarily a "
            f"bug. Try: python auto_discover_wallets.py --min-buys 2 "
            f"--min-winrate 0.4 --fallback-ranked"
        )
        if args.fallback_ranked:
            ranked = [r for r in all_results if r["buys_last_10w"] > 0]
            ranked.sort(key=lambda r: (r["buys_last_10w"], r["win_rate"] or 0), reverse=True)
            result_set = ranked[: args.top]
            print(f"\n--fallback-ranked: showing the {len(result_set)} most "
                  f"tennis-active candidates found, even though they didn't "
                  f"clear the bar above. Review these manually before trusting them.\n")
        else:
            return

    lines = []
    print("Add these to WATCHED_WALLETS in config.py:\n")
    for r in result_set:
        nickname = r["leaderboard_username"] or f"whale-{r['address'][2:8]}"
        wr_str = f"{r['win_rate']:.1%}" if r["win_rate"] is not None else "n/a"
        line = f'    "{nickname}": "{r["address"]}",  # win rate {wr_str}, {r["buys_last_10w"]} buys/10w'
        print(line)
        lines.append(line)

    if args.output:
        with open(args.output, "w") as f:
            f.write("WATCHED_WALLETS = {\n")
            f.write("\n".join(lines))
            f.write("\n}\n")
        print(f"\nAlso written to {args.output}")


if __name__ == "__main__":
    main()
