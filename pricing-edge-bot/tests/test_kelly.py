import pytest

from kelly import kelly_fraction, sized_kelly_fraction


def test_kelly_zero_at_fair_price():
    # p == price is a fair bet -> full Kelly says 0% of bankroll.
    assert kelly_fraction(0.6, 0.6) == pytest.approx(0.0, abs=1e-9)


def test_kelly_positive_with_edge():
    # p_win 0.9 at price 0.8 is a real edge -> positive fraction.
    f = kelly_fraction(0.90, 0.80)
    assert f > 0


def test_kelly_negative_without_edge():
    # p_win below the market-implied probability -> negative (don't bet).
    f = kelly_fraction(0.10, 0.30)
    assert f < 0


def test_kelly_matches_textbook_formula():
    # Classic Kelly example: p=0.6 coin, even-money bet (price=0.5 -> b=1).
    # f* = p - q = 0.6 - 0.4 = 0.2
    f = kelly_fraction(0.6, 0.5)
    assert f == pytest.approx(0.2)


def test_sized_kelly_floors_negative_at_zero():
    result = sized_kelly_fraction(0.10, 0.30, kelly_multiplier=1.0, max_fraction=1.0)
    assert result.raw_fraction < 0
    assert result.applied_fraction == 0.0


def test_sized_kelly_applies_fractional_multiplier():
    result = sized_kelly_fraction(0.6, 0.5, kelly_multiplier=0.25, max_fraction=1.0)
    assert result.raw_fraction == pytest.approx(0.2)
    assert result.applied_fraction == pytest.approx(0.2 * 0.25)


def test_sized_kelly_respects_hard_cap():
    # A huge edge would want a huge Kelly fraction; the hard cap must win.
    result = sized_kelly_fraction(0.99, 0.10, kelly_multiplier=1.0, max_fraction=0.05)
    assert result.applied_fraction == pytest.approx(0.05)


@pytest.mark.parametrize("kelly_multiplier", [0.0, 1.5, -0.1])
def test_rejects_invalid_kelly_multiplier(kelly_multiplier):
    with pytest.raises(ValueError):
        sized_kelly_fraction(0.6, 0.5, kelly_multiplier=kelly_multiplier)
