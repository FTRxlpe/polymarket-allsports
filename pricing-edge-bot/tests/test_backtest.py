"""
Proves two things about the backtest engine itself (not about whether the
real Polymarket market has this bias — that requires real data, see
fetch_market_history.py):

1. When a price bucket genuinely has a repeatable historical bias, the
   strategy detects it (after enough samples) and turns a profit.
2. When a price bucket has NO bias (price always matches the true win
   rate), the strategy does not hallucinate an edge and stays flat —
   it must not trade on noise.

Both datasets are built deterministically (no RNG) so results are exact
and cannot be flaky.
"""
from pricing_edge import ResolvedMarket
from backtest import BacktestConfig, run_backtest


def _cycle_markets(price: float, pattern: list, count: int) -> list:
    """Builds `count` ResolvedMarkets at `price`, with outcomes cycling
    through `pattern` (e.g. [1, 1, 1, 0] = 75% win rate), timestamped 1
    second apart so ordering is deterministic."""
    markets = []
    for i in range(count):
        outcome = pattern[i % len(pattern)]
        markets.append(ResolvedMarket(entry_price=price, outcome=outcome, resolved_at=float(i)))
    return markets


def test_backtest_profits_from_a_real_repeatable_bias():
    # Price says 60% (bucket 0.50-0.80), true win rate is 75% (3 wins per
    # loss) — a genuine, consistent 15-point edge.
    markets = _cycle_markets(price=0.60, pattern=[1, 1, 1, 0], count=400)

    cfg = BacktestConfig(starting_bankroll=1000.0, min_ev_roi=0.02, min_bucket_samples=30)
    result = run_backtest(markets, cfg)

    assert result.n_trades > 300  # skips only the ~30-sample warmup
    assert result.total_pnl > 0
    assert 0.65 < result.win_rate < 0.85  # should track the true 75% rate


def test_backtest_stays_flat_with_no_bias():
    # Price says 70%, true win rate IS 70% (efficient market, no edge).
    # Wins/losses are interleaved evenly (not front-loaded) so the running
    # win rate never drifts far enough above 0.70 to look like a transient
    # bias before the pattern's exact 7/10 ratio reasserts itself.
    markets = _cycle_markets(price=0.70, pattern=[0, 1, 1, 0, 1, 1, 0, 1, 1, 1], count=400)

    cfg = BacktestConfig(starting_bankroll=1000.0, min_ev_roi=0.02, min_bucket_samples=30)
    result = run_backtest(markets, cfg)

    # No genuine edge exists anywhere in this data, so the min_ev_roi filter
    # should reject every single trade opportunity.
    assert result.n_trades == 0
    assert result.total_pnl == 0
    assert result.ending_bankroll == cfg.starting_bankroll


def test_backtest_ignores_thin_buckets_regardless_of_apparent_bias():
    # Only 10 samples in the bucket -- even though they show a "bias",
    # min_bucket_samples=30 should refuse to trust it.
    markets = _cycle_markets(price=0.60, pattern=[1, 1, 1, 0], count=10)

    cfg = BacktestConfig(starting_bankroll=1000.0, min_bucket_samples=30)
    result = run_backtest(markets, cfg)

    assert result.n_trades == 0


def test_backtest_summary_is_human_readable():
    markets = _cycle_markets(price=0.60, pattern=[1, 1, 1, 0], count=100)
    result = run_backtest(markets)
    s = result.summary()
    assert "trades=" in s and "win_rate=" in s and "pnl=" in s
