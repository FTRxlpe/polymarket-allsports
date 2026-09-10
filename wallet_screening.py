"""
Shared wallet-screening logic: checks a candidate address against simple
whale criteria for the configured sport.
  - >= MIN_BUYS and <= MAX_BUYS buys in the last LOOKBACK_WEEKS weeks
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
from sport_filter import MultiSportFilter

logger = logging.getLogger("wallet_screening")

LOOKBACK_WEEKS = 10
MIN_BUYS = 8
# Upper bound on activity: a real "whale" making conviction bets doesn't
# place thousands of trades a month — that volume is a market-maker/arb bot,
# not a signal worth copying. Confirmed empirically via backtest.py: a
# wallet averaging ~135 buys/day showed up in 14/14 triggered consensus
# signals (result: 30.8% win rate, -43% ROI) — it wasn't 3 whales agreeing,
# it was 2 whales plus one hyperactive wallet that touches nearly every
# market. MAX_BUYS filters that class of wallet out of the watch list.
MAX_BUYS = 2500
MIN_WIN_RATE = 0.50

_sport_filter = MultiSportFilter(config.SPORT_TAG_SLUGS)


def fetch_trades(address: str, limit: int = 500, offset: int = 0, max_retries: int = 4) -> list:
    url = f"{config.POLYMARKET_DATA_API}/trades"
    delay = 1.5
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url, params={"user": address, "limit": limit, "offset": offset}, timeout=15
            )
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


def fetch_recent_buys(address: str, weeks: int, max_count: int,
                       page_size: int = 500, max_pages: int = 20) -> tuple:
    """Paginates through `address`'s FULL trade history (every category,
    not just the sport(s) being screened) to collect every BUY trade within
    the last `weeks` weeks, stopping as soon as more than `max_count` have
    been found.

    A single capped fetch_trades(limit=500) call badly undercounts a
    hyperactive wallet: for one trading ~135 times/day (confirmed via
    backtest.py — see MAX_BUYS above), the 500 most recent trades cover
    under 4 days, nowhere near the 10-week lookback window, so its true
    volume never surfaces and MAX_BUYS can never trigger. This paginates
    properly instead, and checks TOTAL activity across every category
    (not just the sport being screened) since that's the actual signature
    of a market-maker/arb bot — its sport-specific volume alone can look
    perfectly modest even while its overall activity is enormous.

    Returns (buys, exceeded_max). When exceeded_max is True, `buys` is a
    partial/incomplete list (collection stopped early) — use it only as
    evidence the wallet is over max_count, never as its true trade history.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).timestamp()
    buys = []
    offset = 0
    for _ in range(max_pages):
        page = fetch_trades(address, limit=page_size, offset=offset)
        if not page:
            break
        reached_cutoff = False
        for t in page:
            ts = float(t.get("timestamp", 0))
            if ts < cutoff:
                reached_cutoff = True
                continue
            if (t.get("side") or "").upper() == "BUY":
                buys.append(t)
        if len(buys) > max_count:
            return buys, True
        if reached_cutoff or len(page) < page_size:
            break
        offset += page_size
    return buys, False


def screen_wallet(address: str, min_buys: int = None, min_win_rate: float = None,
                   max_buys: int = None) -> dict:
    """min_buys / min_win_rate / max_buys override the module defaults
    (MIN_BUYS / MIN_WIN_RATE / MAX_BUYS) when provided — lets callers
    loosen or tighten the bar without editing this file."""
    if min_buys is None:
        min_buys = MIN_BUYS
    if min_win_rate is None:
        min_win_rate = MIN_WIN_RATE
    if max_buys is None:
        max_buys = MAX_BUYS

    address = address.lower()

    # Check TOTAL activity (every category) first, properly paginated with
    # early exit — see fetch_recent_buys' docstring for why this has to
    # come before anything sport-specific. If the wallet is already over
    # max_buys, skip the sport filtering and win-rate computation entirely:
    # the result is discarded either way.
    all_recent_buys, exceeded_max = fetch_recent_buys(address, weeks=LOOKBACK_WEEKS, max_count=max_buys)

    if exceeded_max:
        return {
            "address": address,
            "buys_last_10w": None,  # true count unknown — collection stopped early once > max_buys
            "resolved_markets": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "meets_activity_bar": False,
            "meets_winrate_bar": False,
            "qualifies": False,
        }

    sport_buys = [t for t in all_recent_buys if _sport_filter.is_match_historical(t.get("slug") or "")]
    meets_activity_bar = len(sport_buys) >= min_buys

    # Win-rate computation resolves every unique market the wallet touched,
    # each with a deliberate throttling sleep — for a wallet with many
    # unique markets that's real work for a result that's discarded anyway
    # once meets_activity_bar is already False. Skip it entirely in that case.
    wins = losses = total_resolved = 0
    win_rate = None
    if meets_activity_bar:
        from market_resolver import MarketResolver, get_winning_outcome
        resolver = MarketResolver()

        by_market = defaultdict(list)
        for t in sport_buys:
            by_market[t.get("slug")].append(t)

        for slug, market_trades in by_market.items():
            market = resolver._get_market(slug)
            time.sleep(0.15)  # avoid hammering the Gamma API when a wallet touches many markets
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
        # a genuinely computed win_rate >= min_win_rate passes. Likewise a
        # wallet trading more than max_buys times is presumed to be a bot/
        # market-maker, not a conviction whale worth copying (see MAX_BUYS).
        "qualifies": meets_activity_bar and meets_winrate_bar,
    }
