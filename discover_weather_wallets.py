"""
Discovers whale wallets active on weather markets. There's no WEATHER
leaderboard category on Polymarket's data API (see list_weather_tags.py),
so discover_top50_alltime.py's leaderboard-based approach can't be reused
here.

Instead: collect every market slug under the real weather tag_ids (found
via list_weather_tags.py + sample_sport_slugs.py — climate-weather,
climate-science, hurricanes, snow), then scan every wallet ALREADY vetted
as a legit whale in some other category (every found_wallets_*.txt already
on disk from prior discover_top50_alltime.py runs) to see which of them
ALSO trade weather markets, and how well they do there specifically.

Caveat: this can only surface weather activity among wallets already
discovered elsewhere — it will miss a wallet that trades ONLY weather
markets and nothing else. It's a cheap first empirical read (reuses every
already-screened whale you have, zero new leaderboard needed) on whether
weather is worth a dedicated from-scratch discovery effort at all.

Usage:
    python discover_weather_wallets.py
    python discover_weather_wallets.py --tag-ids 1474 103037 85 103545
"""
import argparse
import glob
import re
import time

import requests

import config
from wallet_screening import compute_win_rate

GAMMA_API = "https://gamma-api.polymarket.com"
DEFAULT_TAG_IDS = [1474, 103037, 85, 103545]  # climate-weather, climate-science, hurricanes, snow


def fetch_weather_slugs(tag_ids, max_retries: int = 3) -> set:
    """Collect every market slug under the given tag_ids, both active and
    closed, so wallet trade history can be matched against real weather
    markets regardless of whether they're still open."""
    slugs = set()
    for tag_id in tag_ids:
        for closed in (False, True):
            offset = 0
            page_size = 100
            for _ in range(20):
                params = {"tag_id": tag_id, "limit": page_size, "offset": offset,
                          "closed": str(closed).lower()}
                delay = 1.5
                page = None
                for attempt in range(max_retries):
                    resp = requests.get(f"{GAMMA_API}/events", params=params, timeout=15)
                    if resp.status_code == 429:
                        time.sleep(delay)
                        delay *= 2
                        continue
                    resp.raise_for_status()
                    page = resp.json()
                    break
                if not page:
                    break
                for event in page:
                    for market in event.get("markets", []):
                        slug = market.get("slug")
                        if slug:
                            slugs.add(slug)
                if len(page) < page_size:
                    break
                offset += page_size
    return slugs


def load_all_known_wallets() -> dict:
    """Pools every wallet from every found_wallets_*.txt already on disk —
    all previously vetted as legit whales in SOME category, just not
    specifically screened for weather activity yet."""
    wallets = {}
    pattern = re.compile(r'"([^"]+)":\s*"(0x[a-fA-F0-9]{40})"')
    for path in glob.glob("found_wallets_*.txt"):
        with open(path) as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    wallets[m.group(1)] = m.group(2).lower()
    return wallets


def fetch_all_trades(address: str, max_pages: int = 10, page_size: int = 500,
                      max_retries: int = 4) -> list:
    url = f"{config.POLYMARKET_DATA_API}/trades"
    all_trades = []
    offset = 0
    for _ in range(max_pages):
        delay = 1.5
        page = None
        for attempt in range(max_retries):
            resp = requests.get(
                url, params={"user": address, "limit": page_size, "offset": offset}, timeout=15
            )
            if resp.status_code == 429:
                time.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
            page = resp.json()
            break
        if not page:
            break
        all_trades.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return all_trades


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag-ids", type=int, nargs="+", default=DEFAULT_TAG_IDS)
    parser.add_argument("--delay", type=float, default=1.0,
                         help="Seconds between wallets, to avoid rate limits")
    parser.add_argument("--output", type=str, default="found_wallets_weather.txt")
    args = parser.parse_args()

    print(f"Collecting weather market slugs under tag_ids {args.tag_ids}...")
    weather_slugs = fetch_weather_slugs(args.tag_ids)
    print(f"{len(weather_slugs)} weather market slugs found.\n")

    wallets = load_all_known_wallets()
    if not wallets:
        print("No found_wallets_*.txt files found in this directory — run "
              "discover_top50_alltime.py for at least one category first.")
        return
    print(f"Scanning {len(wallets)} already-vetted whale wallets (pooled from every "
          f"found_wallets_*.txt on disk) for weather activity...\n")

    results = []
    for i, (nickname, addr) in enumerate(wallets.items(), 1):
        trades = fetch_all_trades(addr)
        time.sleep(args.delay)
        weather_buys = [
            t for t in trades
            if (t.get("side") or "").upper() == "BUY" and (t.get("slug") in weather_slugs)
        ]
        if not weather_buys:
            continue

        wins, losses, total_resolved, win_rate = compute_win_rate(weather_buys, throttle=0.15)
        wr_str = f"{win_rate:.1%}" if win_rate is not None else "n/a"
        print(f"[{i}/{len(wallets)}] {nickname} ({addr}): {len(weather_buys)} weather buys, "
              f"win rate {wr_str} ({wins}W/{losses}L on {total_resolved} resolved)")
        results.append((nickname, addr, len(weather_buys), wins, losses, total_resolved, win_rate))

    print(f"\n{len(results)}/{len(wallets)} already-known whale wallets have ANY weather activity.")
    if not results:
        print("\nNone of the wallets already vetted in other categories trade weather markets. "
              "Weather-specialist whales, if they exist, are a distinct population this scan "
              "can't see without a from-scratch discovery method (scanning trades ON the "
              "weather markets themselves rather than known wallets' histories) — a bigger "
              "build. Given also the correlated-recurring-question structure seen in the slug "
              "samples, probably not worth that investment right now.")
        return

    lines = []
    for nickname, addr, n_buys, wins, losses, total_resolved, win_rate in sorted(
        results, key=lambda r: -r[2]
    ):
        wr_str = f"{win_rate:.1%}" if win_rate is not None else "n/a"
        lines.append(
            f'    "{nickname}": "{addr}",  # {n_buys} weather buys, '
            f'win rate {wr_str} ({wins}W/{losses}L)'
        )
    with open(args.output, "w") as f:
        f.write("WATCHED_WALLETS = {\n")
        f.write("\n".join(lines))
        f.write("\n}\n")
    print(f"\nWritten to {args.output} — feed it to "
          f"backtest.py --wallets-file {args.output} to see if a real consensus edge shows "
          f"up, or if it reproduces ECONOMICS/POLITICS's correlated-recurring-question problem.")


if __name__ == "__main__":
    main()
