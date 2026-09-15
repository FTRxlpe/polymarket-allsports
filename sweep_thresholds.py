"""
Sweeps multiple CONSENSUS_WALLET_THRESHOLD values against the SAME fetched
trade history — much faster than re-running backtest.py once per threshold,
since fetching each wallet's trades (the slow part) only happens once.

Usage:
    python sweep_thresholds.py --thresholds 3,4,5,6 --days 30
"""
import argparse
import time
from datetime import datetime, timezone, timedelta

import config
from backtest import fetch_wallet_trades, simulate_consensus, check_outcome
from market_resolver import MarketResolver


def evaluate_threshold(all_events, threshold: int, double_up_offset: int,
                        window_minutes: int, bet_size: float, resolver: MarketResolver,
                        outcome_cache: dict):
    """Runs consensus simulation + PnL calc for one threshold value.
    outcome_cache avoids re-querying the same market twice across different
    threshold runs (a signal on the same slug/outcome can recur)."""
    double_up_threshold = threshold + double_up_offset
    base_signals, double_signals = simulate_consensus(
        all_events, threshold, double_up_threshold, window_minutes
    )

    wins, losses, unresolved = 0, 0, 0
    total_pnl = 0.0
    total_staked = 0.0

    for s in base_signals + double_signals:
        cache_key = (s["slug"], s["outcome"])
        if cache_key not in outcome_cache:
            outcome_cache[cache_key] = check_outcome(resolver, s["slug"], s["outcome"])
            time.sleep(0.15)
        outcome = outcome_cache[cache_key]

        if outcome == "WON":
            payout = bet_size / s["avg_price"] if s["avg_price"] > 0 else 0
            pnl = payout - bet_size
            wins += 1
            total_pnl += pnl
            total_staked += bet_size
        elif outcome == "LOST":
            losses += 1
            total_pnl -= bet_size
            total_staked += bet_size
        else:
            unresolved += 1

    win_rate = wins / (wins + losses) if (wins + losses) else None
    roi = (total_pnl / total_staked * 100) if total_staked > 0 else None

    return {
        "threshold": threshold,
        "double_up_threshold": double_up_threshold,
        "base_count": len(base_signals),
        "double_count": len(double_signals),
        "wins": wins,
        "losses": losses,
        "unresolved": unresolved,
        "win_rate": win_rate,
        "total_staked": total_staked,
        "total_pnl": total_pnl,
        "roi": roi,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--thresholds", type=str, default="3,4,5,6",
                         help="Comma-separated base thresholds to test")
    parser.add_argument("--double-up-offset", type=int, default=2,
                         help="double_up_threshold = threshold + this offset (default 2)")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.8)
    args = parser.parse_args()

    thresholds = [int(t.strip()) for t in args.thresholds.split(",")]
    since_ts = (datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp()

    print(f"Fetching {len(config.WATCHED_WALLETS)} wallets' trade history "
          f"over the last {args.days} days (fetched ONCE, reused for all thresholds)...\n")

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
    print(f"\n{len(all_events)} total buy events gathered.\n")

    tier = config.get_bankroll_tier(config.STARTING_BANKROLL)
    bet_size = tier.base_bet * config.STARTING_BANKROLL if tier.is_percentage else tier.base_bet
    bet_size = min(bet_size, tier.max_bet * config.STARTING_BANKROLL if tier.is_percentage else tier.max_bet)

    resolver = MarketResolver()
    outcome_cache = {}
    results = []

    for threshold in thresholds:
        print(f"\n=== Evaluating threshold={threshold} (double_up={threshold + args.double_up_offset}) ===")
        result = evaluate_threshold(
            all_events, threshold, args.double_up_offset,
            config.TIME_WINDOW_MINUTES, bet_size, resolver, outcome_cache
        )
        results.append(result)
        wr_str = f"{result['win_rate']:.1%}" if result['win_rate'] is not None else "n/a"
        roi_str = f"{result['roi']:+.1f}%" if result['roi'] is not None else "n/a"
        print(f"  base={result['base_count']} signals, double_up={result['double_count']} signals")
        print(f"  Resolved: {result['wins']}W/{result['losses']}L ({wr_str}), "
              f"{result['unresolved']} unresolved")
        print(f"  Staked: ${result['total_staked']:.2f}, PnL: {'+' if result['total_pnl']>=0 else ''}"
              f"${result['total_pnl']:.2f}, ROI: {roi_str}")

    print(f"\n\n{'='*80}")
    print(f"SUMMARY: threshold sweep over last {args.days} days (bet size ${bet_size:.2f})")
    print(f"{'='*80}")
    print(f"{'Base':>5} {'Double':>7} {'Signals':>8} {'Resolved':>9} {'WinRate':>8} {'Staked':>9} {'PnL':>10} {'ROI':>8}")
    for r in results:
        total_signals = r['base_count'] + r['double_count']
        resolved = r['wins'] + r['losses']
        wr_str = f"{r['win_rate']:.1%}" if r['win_rate'] is not None else "n/a"
        roi_str = f"{r['roi']:+.1f}%" if r['roi'] is not None else "n/a"
        pnl_str = f"{'+' if r['total_pnl']>=0 else ''}${r['total_pnl']:.2f}"
        print(f"{r['threshold']:>5} {r['double_up_threshold']:>7} {total_signals:>8} "
              f"{resolved:>9} {wr_str:>8} ${r['total_staked']:>7.2f} {pnl_str:>10} {roi_str:>8}")


if __name__ == "__main__":
    main()
