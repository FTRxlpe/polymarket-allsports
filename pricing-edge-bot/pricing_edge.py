"""
Empirical price-error correction (delta).

The claim behind this strategy is that the market's price is a slightly
biased estimate of the true probability, and that the bias depends on the
price bucket (e.g. cheap longshots are overpriced, expensive favorites are
underpriced). This module does NOT assume that bias exists or trust any
externally-claimed win rate — it *measures* it from historical resolved
markets you supply, per price bucket:

    delta_bucket = mean(resolved_outcome) - mean(entry_price)

for every market whose entry price fell in that bucket.

Two safeguards against fooling yourself:
  1. `min_samples` — a bucket with too few resolved markets doesn't get a
     delta estimate at all (returns None), rather than an overconfident
     estimate from noise.
  2. Walk-forward / out-of-sample bias estimation is enforced by
     `WalkForwardEdgeEstimator`: delta for a given point in time is
     computed ONLY from markets that resolved strictly before it. A
     backtest that instead computed one delta over the whole dataset and
     applied it to every trade in that same dataset would be leaking
     future information into its own signal — a classic way backtests lie.
"""
from bisect import bisect_right
from dataclasses import dataclass
from typing import List, Optional, Sequence


@dataclass(frozen=True)
class ResolvedMarket:
    entry_price: float     # price at the moment we would have entered
    outcome: int            # 1 if the bought outcome won, 0 otherwise
    resolved_at: float      # unix timestamp of resolution, for walk-forward ordering


DEFAULT_BUCKETS = [
    (0.00, 0.20),
    (0.20, 0.50),
    (0.50, 0.80),
    (0.80, 0.95),
    (0.95, 1.00),
]


def _bucket_of(price: float, buckets: Sequence[tuple]) -> Optional[tuple]:
    for lo, hi in buckets:
        if lo <= price < hi or (hi == 1.0 and price == 1.0):
            return (lo, hi)
    return None


def compute_bucket_deltas(
    markets: Sequence[ResolvedMarket],
    buckets: Sequence[tuple] = DEFAULT_BUCKETS,
    min_samples: int = 30,
) -> dict:
    """Returns {(lo, hi): delta_or_None} for every bucket that has at least
    `min_samples` resolved markets in it."""
    sums = {b: [0.0, 0.0, 0] for b in buckets}  # price_sum, outcome_sum, count
    for m in markets:
        b = _bucket_of(m.entry_price, buckets)
        if b is None:
            continue
        sums[b][0] += m.entry_price
        sums[b][1] += m.outcome
        sums[b][2] += 1

    result = {}
    for b, (price_sum, outcome_sum, count) in sums.items():
        if count < min_samples:
            result[b] = None
        else:
            result[b] = (outcome_sum / count) - (price_sum / count)
    return result


def estimated_true_probability(price: float, delta: Optional[float]) -> float:
    """p_hat = price + delta, clamped to a valid probability. If delta is
    None (not enough data for that bucket), returns `price` unchanged —
    i.e. assume the market is efficient absent evidence otherwise."""
    if delta is None:
        return price
    return min(0.999, max(0.001, price + delta))


class WalkForwardEdgeEstimator:
    """Prevents lookahead bias in the backtest: delta for a trade taken at
    time T is computed only from markets that had already resolved before T.
    """

    def __init__(
        self,
        markets: Sequence[ResolvedMarket],
        buckets: Sequence[tuple] = DEFAULT_BUCKETS,
        min_samples: int = 30,
    ):
        self.buckets = buckets
        self.min_samples = min_samples
        self._sorted = sorted(markets, key=lambda m: m.resolved_at)
        self._times = [m.resolved_at for m in self._sorted]

    def delta_as_of(self, timestamp: float) -> dict:
        """Bucket deltas computed only from markets resolved strictly
        before `timestamp`."""
        cutoff = bisect_right(self._times, timestamp)
        available = self._sorted[:cutoff]
        return compute_bucket_deltas(available, self.buckets, self.min_samples)

    def estimate(self, price: float, timestamp: float) -> float:
        deltas = self.delta_as_of(timestamp)
        b = _bucket_of(price, self.buckets)
        delta = deltas.get(b) if b else None
        return estimated_true_probability(price, delta)
