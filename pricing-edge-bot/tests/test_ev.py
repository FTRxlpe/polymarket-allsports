import pytest

from ev import expected_value, has_edge


def test_ev_zero_at_fair_price():
    # If p_hat exactly equals price, EV per share is 0 (fair bet).
    result = expected_value(p_win=0.6, price=0.6)
    assert result.ev == pytest.approx(0.0, abs=1e-9)
    assert result.ev_roi == pytest.approx(0.0, abs=1e-9)


def test_ev_positive_when_underpriced():
    # True prob 0.90 but market prices it at 0.80 -> should be positive EV.
    result = expected_value(p_win=0.90, price=0.80)
    expected_ev = 0.90 * (1 - 0.80) - 0.10 * 0.80
    assert result.ev == pytest.approx(expected_ev)
    assert result.ev > 0


def test_ev_negative_when_overpriced():
    # True prob 0.10 but market prices it at 0.30 (classic overpriced longshot).
    result = expected_value(p_win=0.10, price=0.30)
    assert result.ev < 0


def test_ev_roi_matches_ev_over_price():
    result = expected_value(p_win=0.7, price=0.5)
    assert result.ev_roi == pytest.approx(result.ev / 0.5)


def test_has_edge_respects_margin():
    # Tiny edge should fail a nontrivial min_ev_roi requirement.
    assert has_edge(p_win=0.501, price=0.50, min_ev_roi=0.0) is True
    assert has_edge(p_win=0.501, price=0.50, min_ev_roi=0.05) is False


@pytest.mark.parametrize("p_win", [-0.1, 1.1])
def test_rejects_invalid_probability(p_win):
    with pytest.raises(ValueError):
        expected_value(p_win, 0.5)


@pytest.mark.parametrize("price", [0.0, 1.0, -0.2, 1.5])
def test_rejects_invalid_price(price):
    with pytest.raises(ValueError):
        expected_value(0.5, price)
