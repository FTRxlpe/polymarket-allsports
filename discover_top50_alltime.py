"""
Fetches top wallets from Polymarket's official leaderboard for whichever
category is configured (config.LEADERBOARD_CATEGORY — SPORTS, ECONOMICS,
POLITICS, CRYPTO, etc.), ranked by ALL-TIME PnL (timePeriod=ALL — since
each account's creation), THEN filters to only those with a RECENT trade —
a wallet with a great historical PnL but that stopped trading months ago is
useless for a real-time consensus signal.

For each candidate, this checks their most recent trade timestamp via the
public Data API and only keeps wallets active within --max-inactive-days.

Usage:
    python discover_top50_alltime.py
    python discover_top50_alltime.py --top 50 --order PNL --max-inactive-days 14
"""
import argparse
import time
from datetime import datetime, timezone, timedelta

import requests

import config
from wallet_screening import fetch_recent_buys, MAX_BUYS, LOOKBACK_WEEKS

LEADERBOARD_URL = f"{config.POLYMARKET_DATA_API}/v1/leaderboard"
TRADES_URL = f"{config.POLYMARKET_DATA_API}/trades"


def count_recent_buys(address: str, max_count: int) -> tuple:
    """How many BUY trades this wallet made in the last LOOKBACK_WEEKS weeks,
    across ALL markets (no sport filter here — this script ranks by
    all-time PnL across any category, so the check is generic trading
    frequency, same threshold wallet_screening.py uses). Catches
    market-maker/arb bots that rank highly on PnL purely from volume —
    confirmed via backtest.py that including one such wallet (~135
    buys/day) was enough to fake 14/14 consensus signals and produce a
    -43% ROI. discover_top50_alltime.py never went through
    wallet_screening.screen_wallet()'s MIN_BUYS/MAX_BUYS checks at all
    (it only filters by PnL + recent activity), so re-running discovery
    without this would have silently re-introduced the same wallet.

    Delegates to wallet_screening.fetch_recent_buys, which paginates
    properly with early exit once max_count is passed — a single capped
    fetch (limit=500, no pagination) undercounts a hyperactive wallet
    badly: its 500 most recent trades might cover only a few days, so its
    true volume never surfaces and this check could never trigger. That
    exact gap is how whale-2c3350 slipped back into a discovery run even
    after this ceiling was first added — see wallet_screening.py.

    Returns (count_or_None, exceeded) — count is None when exceeded is
    True (collection stopped early, so the exact number is unknown, only
    that it's over max_count)."""
    buys, exceeded = fetch_recent_buys(address, weeks=LOOKBACK_WEEKS, max_count=max_count)
    return (None if exceeded else len(buys)), exceeded


def fetch_leaderboard(order_by: str, limit: int, offset: int = 0, max_retries: int = 3) -> list:
    params = {
        "category": config.LEADERBOARD_CATEGORY,
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


def fetch_leaderboard_paginated(order_by: str, max_candidates: int) -> list:
    """The leaderboard API caps each response at 50 entries regardless of
    the requested limit — paginate with offset to gather more candidates
    beyond just the top 50."""
    all_candidates = []
    offset = 0
    page_size = 50
    while len(all_candidates) < max_candidates:
        page = fetch_leaderboard(order_by, page_size, offset=offset)
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
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--order", choices=["PNL", "VOL"], default="PNL")
    parser.add_argument("--output", type=str, default="found_wallets_top50.txt")
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
    parser.add_argument("--delay", type=float, default=1.0,
                         help="Seconds between activity-check calls, to avoid rate limits")
    args = parser.parse_args()

    print(f"Fetching top {config.LEADERBOARD_CATEGORY} wallets by ALL-TIME {args.order}...")
    # Fetch a larger candidate pool since some will get filtered out for
    # being negative-PnL or inactive. Paginated beyond the API's 50-per-call cap.
    candidates = fetch_leaderboard_paginated(args.order, args.top * 5)
    print(f"{len(candidates)} candidates fetched. Checking recent activity "
          f"(must have traded within the last {args.max_inactive_days:.0f} days)...\n")

    lines = []
    kept = 0
    checked = 0
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

        recent_buys, exceeded = count_recent_buys(addr, args.max_buys)
        time.sleep(args.delay)
        if exceeded:
            print(
                f"[{checked}] {name} — skip (>{args.max_buys} buys/{LOOKBACK_WEEKS}w — "
                f"market-maker/bot pattern, not a conviction whale)"
            )
            continue

        print(f"[{checked}] {name} — KEEP (last trade {days_ago:.1f} days ago, "
              f"{recent_buys} buys/{LOOKBACK_WEEKS}w), PnL {pnl_str}")
        line = (
            f'    "{name}": "{addr}",  # all-time PnL {pnl_str}, vol {vol_str}, '
            f'last active {days_ago:.1f}d ago, {recent_buys} buys/{LOOKBACK_WEEKS}w'
        )
        lines.append(line)
        kept += 1

    print(f"\n{kept} wallets qualify: strong all-time PnL AND recently active "
          f"(traded within {args.max_inactive_days:.0f} days).")

    if kept < args.top:
        print(
            f"Got {kept}/{args.top} — try a longer --max-inactive-days window "
            f"or a smaller --top if you need more results."
        )

    with open(args.output, "w") as f:
        f.write("WATCHED_WALLETS = {\n")
        f.write("\n".join(lines))
        f.write("\n}\n")
    print(f"Written to {args.output} — paste this into config.py")


if __name__ == "__main__":
    main()
