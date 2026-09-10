"""
Backtest: for each wallet in config.WATCHED_WALLETS, pulls their real trade
history over the last N days, then replays it chronologically through the
SAME two-tier consensus logic the live bot uses (config.CONSENSUS_WALLET_THRESHOLD
/ config.DOUBLE_UP_THRESHOLD, config.TIME_WINDOW_MINUTES) to see how many
times a signal would actually have fired — and, where the market has since
resolved, whether it would have won or lost.

This answers "how often would my bot have traded, and how would it have
done?" using real historical data instead of guessing.

Usage:
    python backtest.py --days 30
"""
import argparse
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests

import config
from market_resolver import MarketResolver

TRADES_URL = f"{config.POLYMARKET_DATA_API}/trades"


def fetch_wallet_trades(address: str, since_ts: float, max_retries: int = 3) -> list:
    """Fetch as many recent trades as needed to cover `since_ts`, paginating
    with the API's offset param since a single call is capped."""
    all_trades = []
    offset = 0
    page_size = 500
    for _ in range(10):  # up to 5000 trades per wallet, generous ceiling
        delay = 1.5
        page = None
        for attempt in range(max_retries):
            try:
                resp = requests.get(
                    TRADES_URL,
                    params={"user": address, "limit": page_size, "offset": offset},
                    timeout=15,
                )
                if resp.status_code == 429:
                    time.sleep(delay)
                    delay *= 2
                    continue
                resp.raise_for_status()
                page = resp.json()
                break
            except requests.RequestException:
                return all_trades
        if not page:
            break

        stop = False
        for t in page:
            ts = float(t.get("timestamp", 0))
            if ts < since_ts:
                stop = True
                continue
            all_trades.append(t)
        if stop or len(page) < page_size:
            break
        offset += page_size

    return all_trades


def simulate_consensus(all_events: list, threshold: int, double_threshold: int, window_minutes: int):
    """all_events: list of dicts with wallet, slug, outcome, price, timestamp,
    sorted ascending by timestamp. Returns (base_signals, double_signals)."""
    pending = defaultdict(list)   # key -> list of event dicts
    fired_base = set()
    fired_double = set()
    base_signals = []
    double_signals = []

    for ev in all_events:
        key = (ev["slug"], ev["outcome"])
        cutoff = ev["timestamp"] - window_minutes * 60

        # prune expired entries for this key
        pending[key] = [e for e in pending[key] if e["timestamp"] >= cutoff]
        if not pending[key]:
            fired_base.discard(key)
            fired_double.discard(key)

        # keep only the latest entry per wallet within the window
        pending[key] = [e for e in pending[key] if e["wallet"] != ev["wallet"]]
        pending[key].append(ev)

        distinct_wallets = {e["wallet"] for e in pending[key]}
        count = len(distinct_wallets)

        if key not in fired_base and count >= threshold:
            fired_base.add(key)
            base_signals.append({
                "slug": key[0], "outcome": key[1], "wallet_count": count,
                "wallets": sorted(distinct_wallets), "timestamp": ev["timestamp"],
                "avg_price": sum(e["price"] for e in pending[key]) / len(pending[key]),
            })

        if key in fired_base and key not in fired_double and count >= double_threshold:
            fired_double.add(key)
            double_signals.append({
                "slug": key[0], "outcome": key[1], "wallet_count": count,
                "wallets": sorted(distinct_wallets), "timestamp": ev["timestamp"],
                "avg_price": sum(e["price"] for e in pending[key]) / len(pending[key]),
            })

    return base_signals, double_signals


def check_outcome(resolver: MarketResolver, slug: str, outcome: str):
    """Returns 'WON', 'LOST', or None (unresolved/unknown).

    There is no "winningOutcome" field in Polymarket's API — a resolved
    market's winner is determined from outcomePrices, which settle to ~1.0
    for the winning outcome and ~0.0 for the rest once resolution completes."""
    market = resolver._get_market(slug)
    if not market or not market.get("closed"):
        return None

    import json as _json
    outcomes = market.get("outcomes")
    prices = market.get("outcomePrices")
    if isinstance(outcomes, str):
        outcomes = _json.loads(outcomes)
    if isinstance(prices, str):
        prices = _json.loads(prices)
    if not outcomes or not prices or len(outcomes) != len(prices):
        return None

    try:
        prices_f = [float(p) for p in prices]
    except (TypeError, ValueError):
        return None

    winner_idx = prices_f.index(max(prices_f))
    if prices_f[winner_idx] < 0.9:
        return None  # not confidently settled yet, don't guess

    winning_outcome = outcomes[winner_idx]
    return "WON" if str(outcome).lower() == str(winning_outcome).lower() else "LOST"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--check-outcomes", action="store_true", default=True,
                         help="Look up win/loss for each base signal (slower)")
    args = parser.parse_args()

    since_ts = (datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp()

    print(f"Backtesting {len(config.WATCHED_WALLETS)} wallets over the last {args.days} days...")
    print(f"Thresholds: base={config.CONSENSUS_WALLET_THRESHOLD}, "
          f"double_up={config.DOUBLE_UP_THRESHOLD}, window={config.TIME_WINDOW_MINUTES}min\n")

    all_events = []
    for i, (nickname, address) in enumerate(config.WATCHED_WALLETS.items(), 1):
        trades = fetch_wallet_trades(address.lower(), since_ts)
        buys = [t for t in trades if (t.get("side") or "").upper() == "BUY"]
        print(f"[{i}/{len(config.WATCHED_WALLETS)}] {nickname}: {len(buys)} buys in window")
        for t in buys:
            all_events.append({
                "wallet": nickname,
                "slug": t.get("slug") or t.get("market_slug") or "",
                "outcome": t.get("outcome", ""),
                "price": float(t.get("price", 0)),
                "timestamp": float(t.get("timestamp", 0)),
            })
        time.sleep(args.delay)

    all_events.sort(key=lambda e: e["timestamp"])
    print(f"\n{len(all_events)} total buy events gathered. Replaying consensus logic...\n")

    base_signals, double_signals = simulate_consensus(
        all_events,
        config.CONSENSUS_WALLET_THRESHOLD,
        config.DOUBLE_UP_THRESHOLD,
        config.TIME_WINDOW_MINUTES,
    )

    print(f"=== RESULTS: last {args.days} days ===")
    print(f"Base trades (>= {config.CONSENSUS_WALLET_THRESHOLD} wallets agreed): {len(base_signals)}")
    print(f"Double-up trades (>= {config.DOUBLE_UP_THRESHOLD} wallets agreed): {len(double_signals)}\n")

    if base_signals:
        days_span = max(args.days, 1)
        print(f"Average: {len(base_signals) / days_span:.2f} base trades/day, "
              f"{len(double_signals) / days_span:.2f} double-ups/day\n")

    resolver = MarketResolver()

    # Use a static bet size based on config.STARTING_BANKROLL for the whole
    # backtest (not compounding trade-to-trade) — simpler and more
    # transparent than trying to replay the risk manager's running bankroll
    # state, and good enough to judge whether the strategy has real edge.
    bankroll = config.STARTING_BANKROLL
    tier = config.get_bankroll_tier(bankroll)
    bet_size = tier.base_bet * bankroll if tier.is_percentage else tier.base_bet
    bet_size = min(bet_size, tier.max_bet * bankroll if tier.is_percentage else tier.max_bet)
    print(f"Using a flat ${bet_size:.2f} bet size per signal (bankroll tier for ${bankroll:.0f})\n")

    def resolve_and_pnl(s, label):
        """Returns (outcome_str, pnl) for one signal. pnl is None if unresolved."""
        outcome = check_outcome(resolver, s["slug"], s["outcome"])
        time.sleep(0.2)
        if outcome == "WON":
            # Bought at avg_price, resolves to $1 per share.
            payout = bet_size / s["avg_price"] if s["avg_price"] > 0 else 0
            pnl = payout - bet_size
        elif outcome == "LOST":
            pnl = -bet_size
        else:
            pnl = None
        return outcome, pnl

    wins, losses, unresolved = 0, 0, 0
    total_pnl = 0.0
    total_staked = 0.0

    print("=== Individual base signals ===")
    for s in base_signals:
        when = datetime.fromtimestamp(s["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        result = ""
        if args.check_outcomes:
            outcome, pnl = resolve_and_pnl(s, "base")
            if outcome == "WON":
                wins += 1
                total_pnl += pnl
                total_staked += bet_size
                result = f" -> WON (+${pnl:.2f})"
            elif outcome == "LOST":
                losses += 1
                total_pnl += pnl
                total_staked += bet_size
                result = f" -> LOST (-${bet_size:.2f})"
            else:
                unresolved += 1
                result = " -> unresolved/unknown"
        print(f"  [{when}] {s['slug']} / {s['outcome']} "
              f"({s['wallet_count']} wallets: {s['wallets']}){result}")

    print(f"\n=== Double-up signals ===")
    for s in double_signals:
        when = datetime.fromtimestamp(s["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        result = ""
        if args.check_outcomes:
            outcome, pnl = resolve_and_pnl(s, "double_up")
            if outcome == "WON":
                wins += 1
                total_pnl += pnl
                total_staked += bet_size
                result = f" -> WON (+${pnl:.2f})"
            elif outcome == "LOST":
                losses += 1
                total_pnl += pnl
                total_staked += bet_size
                result = f" -> LOST (-${bet_size:.2f})"
            else:
                unresolved += 1
                result = " -> unresolved/unknown"
        print(f"  [{when}] {s['slug']} / {s['outcome']} ({s['wallet_count']} wallets){result}")

    if args.check_outcomes and (wins + losses) > 0:
        win_rate = wins / (wins + losses)
        roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0
        print(f"\n=== Hypothetical performance ===")
        print(f"Resolved signals: {wins}W / {losses}L  ({win_rate:.1%} win rate)")
        print(f"Unresolved/unknown: {unresolved}")
        print(f"Total staked: ${total_staked:.2f}")
        print(f"Total PnL: {'+' if total_pnl >= 0 else ''}${total_pnl:.2f}")
        print(f"ROI on staked capital: {'+' if roi >= 0 else ''}{roi:.1f}%")


if __name__ == "__main__":
    main()
