import pytest

from pricing_edge import (
    ResolvedMarket,
    compute_bucket_deltas,
    estimated_true_probability,
    WalkForwardEdgeEstimator,
    DEFAULT_BUCKETS,
)


def _market(price, outcome, t):
    return ResolvedMarket(entry_price=price, outcome=outcome, resolved_at=t)


def test_delta_is_none_below_min_samples():
    markets = [_market(0.85, 1, i) for i in range(10)]  # only 10, need 30
    deltas = compute_bucket_deltas(markets, min_samples=30)
    assert deltas[(0.80, 0.95)] is None


def test_delta_detects_known_bias():
    # Bucket 0.80-0.95: price averages 0.85 but true win rate is 0.95.
    # delta should be close to +0.10.
    markets = [_market(0.85, 1, i) for i in range(95)] + [_market(0.85, 0, i) for i in range(5)]
    deltas = compute_bucket_deltas(markets, min_samples=30)
    assert deltas[(0.80, 0.95)] == pytest.approx(0.10, abs=1e-9)


def test_delta_zero_when_market_is_efficient():
    # price == actual win rate exactly -> delta ~ 0.
    markets = [_market(0.70, 1, i) for i in range(70)] + [_market(0.70, 0, i) for i in range(30)]
    deltas = compute_bucket_deltas(markets, min_samples=30)
    assert deltas[(0.50, 0.80)] == pytest.approx(0.0, abs=1e-9)


def test_estimated_probability_applies_delta():
    assert estimated_true_probability(0.80, 0.05) == pytest.approx(0.85)
    assert estimated_true_probability(0.80, None) == 0.80  # no data -> assume efficient


def test_estimated_probability_is_clamped():
    assert estimated_true_probability(0.98, 0.10) <= 0.999
    assert estimated_true_probability(0.02, -0.10) >= 0.001


def test_walk_forward_ignores_future_data():
    # 50 markets resolve "in the past" with a clear bias; one resolves
    # "in the future" with the opposite bias. Estimating at the midpoint
    # must NOT see the future market's outcome.
    past = [_market(0.85, 1, t=i) for i in range(50)]  # all wins, price 0.85 -> delta ~ +0.15
    future_only = [_market(0.85, 0, t=10_000)]          # a single future loss

    estimator = WalkForwardEdgeEstimator(past + future_only, min_samples=30)
    p_hat_before_future = estimator.estimate(price=0.85, timestamp=5000)

    # If the future data leaked in, this estimate would move toward more
    # losses; it must match the "past-only" delta of +0.15 (clamped to the
    # 0.999 ceiling), not something pulled down by the future loss.
    assert p_hat_before_future == pytest.approx(0.999, abs=1e-6)


def test_walk_forward_has_no_data_before_any_history():
    estimator = WalkForwardEdgeEstimator([_market(0.85, 1, t=100)], min_samples=1)
    # Querying at t=0, before any market resolved, must fall back to price.
    assert estimator.estimate(price=0.85, timestamp=0) == 0.85
