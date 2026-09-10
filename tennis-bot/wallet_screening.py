"""
Shared wallet-screening logic: checks a candidate address against simple
whale criteria for the configured sport.
  - >= MIN_BUYS buys in the last LOOKBACK_WEEKS weeks
  - >= MIN_WIN_RATE win rate on resolved positions

Used by:
  - manual_wallet_check.py  (you supply candidate addresses yourself)
  - auto_discover_wallets.py (candidates come from Polymarket's own
    leaderboard API, then get screened for real tennis activity here)

This module never invents wallet addresses — it only evaluates real ones,
whichever script feeds them in.
"""
import time
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests

import config
from sport_filter import SportFilter

logger = logging.getLogger("wallet_screening")

LOOKBACK_WEEKS = 10
MIN_BUYS = 8
MIN_WIN_RATE = 0.50

_sport_filter = SportFilter(tag_slug=config.SPORT_TAG_SLUG)


def fetch_trades(address: str, limit: int = 500, max_retries: int = 4) -> list:
    url = f"{config.POLYMARKET_DATA_API}/trades"
    delay = 1.5
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params={"user": address, "limit": limit}, timeout=15)
            if resp.status_code == 429:
                logger.warning(
                    f"Rate limited (429) for {address}, retrying in {delay:.1f}s "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(delay)
                delay *= 2  # exponential backoff
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch trades for {address}: {e}")
            return []
    logger.warning(f"Giving up on {address} after {max_retries} retries (still rate limited)")
    return []


def screen_wallet(address: str, min_buys: int = None, min_win_rate: float = None) -> dict:
    """min_buys / min_win_rate override the module defaults (MIN_BUYS /
    MIN_WIN_RATE) when provided — lets callers loosen or tighten the bar
    without editing this file."""
    if min_buys is None:
        min_buys = MIN_BUYS
    if min_win_rate is None:
        min_win_rate = MIN_WIN_RATE

    address = address.lower()
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=LOOKBACK_WEEKS)).timestamp()

    trades = fetch_trades(address)
    sport_buys = [
        t for t in trades
        if _sport_filter.is_match(t.get("slug") or "")
        and (t.get("side") or "").upper() == "BUY"
        and float(t.get("timestamp", 0)) >= cutoff
    ]

    from market_resolver import MarketResolver, get_winning_outcome
    resolver = MarketResolver()

    wins, losses = 0, 0
    by_market = defaultdict(list)
    for t in sport_buys:
        by_market[t.get("slug")].append(t)

    for slug, market_trades in by_market.items():
        market = resolver._get_market(slug)
        if not market or not market.get("closed"):
            continue
        winning_outcome = get_winning_outcome(market)
        if not winning_outcome:
            continue
        for t in market_trades:
            if str(t.get("outcome", "")).lower() == str(winning_outcome).lower():
                wins += 1
            else:
                losses += 1

    total_resolved = wins + losses
    win_rate = (wins / total_resolved) if total_resolved else None

    meets_activity_bar = len(sport_buys) >= min_buys
    meets_winrate_bar = (win_rate is not None and win_rate >= min_win_rate)

    return {
        "address": address,
        "buys_last_10w": len(sport_buys),
        "resolved_markets": total_resolved,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "meets_activity_bar": meets_activity_bar,
        "meets_winrate_bar": meets_winrate_bar,
        # A wallet with no resolvable win-rate data cannot be verified to
        # meet the win-rate bar, so it no longer qualifies by default — only
        # a genuinely computed win_rate >= min_win_rate passes.
        "qualifies": meets_activity_bar and meets_winrate_bar,
    }
