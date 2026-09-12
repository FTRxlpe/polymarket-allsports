"""
Fetches top wallets from Polymarket's official leaderboard for whichever
category is requested (--category, or config.LEADERBOARD_CATEGORY if not
given — SPORTS, ECONOMICS, POLITICS, CRYPTO, CULTURE, TECH, FINANCE,
OVERALL), ranked by ALL-TIME PnL (timePeriod=ALL — since each account's
creation), THEN filters to only those with a RECENT trade — a wallet with
a great historical PnL but that stopped trading months ago is useless for
a real-time consensus signal.

For each candidate, this checks their most recent trade timestamp via the
public Data API, keeps only wallets active within --max-inactive-days and
under the --max-buys activity ceiling, and reports their win rate on
resolved positions (any category — no sport filter here) alongside PnL.

Usage:
    python discover_top50_alltime.py
    python discover_top50_alltime.py --category CRYPTO --top 50
    python discover_top50_alltime.py --category POLITICS --top 50 --output found_wallets_politics.txt
"""
import argparse
import time
from datetime import datetime, timezone, timedelta

import requests

import config
from wallet_screening import fetch_recent_buys, compute_win_rate, MAX_BUYS, LOOKBACK_WEEKS

LEADERBOARD_URL = f"{config.POLYMARKET_DATA_API}/v1/leaderboard"
TRADES_URL = f"{config.POLYMARKET_DATA_API}/trades"

VALID_CATEGORIES = ["OVERALL", "POLITICS", "SPORTS", "CRYPTO", "CULTURE", "ECONOMICS", "TECH", "FINANCE"]


def fetch_leaderboard(category: str, order_by: str, limit: int, offset: int = 0, max_retries: int = 3) -> list:
    params = {
        "category": category,
        "timePeriod": "ALL",   # all-time, since account creation — not WEEK/MONTH
        "orderBy": order_by,
        "limit": limit,
        "offset": offset,
    }
    delay = 1.5
    for attempt in range(max_retries):
        resp = requests.get(LEADERBOARD_URL, params=params, timeout=15)
        if resp.status_code == 429:
            time.sleep(delay)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    return []


def fetch_leaderboard_paginated(category: str, order_by: str, max_candidates: int) -> list:
    """The leaderboard API caps each response at 50 entries regardless of
    the requested limit — paginate with offset to gather more candidates
    beyond just the top 50."""
    all_candidates = []
    offset = 0
    page_size = 50
    while len(all_candidates) < max_candidates:
        page = fetch_leaderboard(category, order_by, page_size, offset=offset)
        if not page:
            break
        all_candidates.extend(page)
        if len(page) < page_size:
            break  # last page
        offset += page_size
    return all_candidates


def get_most_recent_trade_days_ago(address: str, max_retries: int = 3) -> float:
    """Returns how many days ago this wallet's most recent trade was, or
    None if it couldn't be determined (treated as inactive/unverifiable)."""
    delay = 1.5
    for attempt in range(max_retries):
        try:
            resp = requests.get(TRADES_URL, params={"user": address, "limit": 1}, timeout=15)
            if resp.status_code == 429:
                time.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
            trades = resp.json()
            if not trades:
                return None
            ts = trades[0].get("timestamp")
            if not ts:
                return None
            trade_time = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            return (datetime.now(timezone.utc) - trade_time).total_seconds() / 86400
        except requests.RequestException:
            return None
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", choices=VALID_CATEGORIES, default=config.LEADERBOARD_CATEGORY,
                         help=f"Leaderboard category to source candidates from (default: "
                              f"config.LEADERBOARD_CATEGORY = {config.LEADERBOARD_CATEGORY}). "
                              f"Overriding this does NOT touch config.py — it only changes which "
                              f"leaderboard THIS run pulls from, so you can compare categories "
                              f"(e.g. --category CRYPTO, then --category POLITICS) without editing "
                              f"config.py between runs.")
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--order", choices=["PNL", "VOL"], default="PNL")
    parser.add_argument("--output", type=str, default=None,
                         help="Defaults to found_wallets_<category>.txt (lowercase) so results "
                              "from different --category runs don't overwrite each other.")
    parser.add_argument("--exclude-negative", action="store_true", default=True,
                         help="Skip wallets with negative all-time PnL (default: on)")
    parser.add_argument("--max-inactive-days", type=float, default=14,
                         help="Only keep wallets whose most recent trade was within "
                              "this many days (default: 14 — i.e. active in the last 2 weeks)")
    parser.add_argument("--max-buys", type=int, default=MAX_BUYS,
                         help=f"Maximum buys in the last {LOOKBACK_WEEKS} weeks — above this a "
                              f"wallet is presumed to be a market-maker/arb bot rather than a "
                              f"conviction whale, regardless of how good its PnL looks "
                              f"(default {MAX_BUYS})")
    parser.add_argument("--min-winrate", type=float, default=None,
                         help="Optional: also require this win rate (0-1) on resolved positions "
                              "to keep a wallet. Win rate is always computed and reported "
                              "regardless; by default it doesn't gate inclusion (many good "
                              "wallets have few resolved-yet positions), only PnL/activity do.")
    parser.add_argument("--delay", type=float, default=1.0,
                         help="Seconds between activity-check calls, to avoid rate limits")
    args = parser.parse_args()
    output_path = args.output or f"found_wallets_{args.category.lower()}.txt"

    print(f"Fetching top {args.category} wallets by ALL-TIME {args.order}...")
    # Fetch a larger candidate pool since some will get filtered out for
    # being negative-PnL or inactive. Paginated beyond the API's 50-per-call cap.
    candidates = fetch_leaderboard_paginated(args.category, args.order, args.top * 5)
    print(f"{len(candidates)} candidates fetched. Checking recent activity "
          f"(must have traded within the last {args.max_inactive_days:.0f} days)...\n")

    lines = []
    kept = 0
    checked = 0
    win_rates = []
    for e in candidates:
        if kept >= args.top:
            break
        addr = (e.get("proxyWallet") or "").lower()
        if not addr:
            continue
        pnl = e.get("pnl")
        vol = e.get("vol")

        if args.exclude_negative and pnl is not None and pnl < 0:
            continue

        checked += 1
        days_ago = get_most_recent_trade_days_ago(addr)
        time.sleep(args.delay)

        name = e.get("userName") or f"whale-{addr[2:8]}"
        pnl_str = f"${pnl:,.0f}" if pnl is not None else "n/a"
        vol_str = f"${vol:,.0f}" if vol is not None else "n/a"

        if days_ago is None:
            print(f"[{checked}] {name} — skip (no trade history found)")
            continue
        if days_ago > args.max_inactive_days:
            print(f"[{checked}] {name} — skip (last trade {days_ago:.1f} days ago, too inactive)")
            continue

        # fetch_recent_buys already paginates properly and stops early once
        # over max_buys — reuse the same buys list for the win-rate
        # computation below instead of fetching the wallet's history twice.
        recent_buys, exceeded = fetch_recent_buys(addr, weeks=LOOKBACK_WEEKS, max_count=args.max_buys)
        time.sleep(args.delay)
        if exceeded:
            print(
                f"[{checked}] {name} — skip (>{args.max_buys} buys/{LOOKBACK_WEEKS}w — "
                f"market-maker/bot pattern, not a conviction whale)"
            )
            continue

        wins, losses, total_resolved, win_rate = compute_win_rate(recent_buys)
        time.sleep(args.delay)
        wr_str = f"{win_rate:.1%}" if win_rate is not None else "n/a"

        if args.min_winrate is not None and (win_rate is None or win_rate < args.min_winrate):
            print(
                f"[{checked}] {name} — skip (win rate {wr_str} on {total_resolved} resolved "
                f"positions, below {args.min_winrate:.0%})"
            )
            continue

        print(f"[{checked}] {name} — KEEP (last trade {days_ago:.1f} days ago, "
              f"{len(recent_buys)} buys/{LOOKBACK_WEEKS}w, win rate {wr_str} "
              f"on {total_resolved} resolved), PnL {pnl_str}")
        if win_rate is not None:
            win_rates.append(win_rate)
        line = (
            f'    "{name}": "{addr}",  # all-time PnL {pnl_str}, vol {vol_str}, '
            f'last active {days_ago:.1f}d ago, {len(recent_buys)} buys/{LOOKBACK_WEEKS}w, '
            f'win rate {wr_str} ({wins}W/{losses}L)'
        )
        lines.append(line)
        kept += 1

    print(f"\n{kept} wallets qualify: strong all-time {args.category} PnL AND recently active "
          f"(traded within {args.max_inactive_days:.0f} days)"
          f"{' AND >= ' + f'{args.min_winrate:.0%} win rate' if args.min_winrate is not None else ''}.")
    if win_rates:
        avg_wr = sum(win_rates) / len(win_rates)
        print(f"Average win rate across kept wallets (where resolvable): {avg_wr:.1%} "
              f"({len(win_rates)}/{kept} had resolved positions to measure)")

    if kept < args.top:
        print(
            f"Got {kept}/{args.top} — try a longer --max-inactive-days window "
            f"or a smaller --top if you need more results."
        )

    with open(output_path, "w") as f:
        f.write("WATCHED_WALLETS = {\n")
        f.write("\n".join(lines))
        f.write("\n}\n")
    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()
