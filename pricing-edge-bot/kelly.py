"""
Kelly criterion sizing for a binary Polymarket contract.

f* = (p*b - q) / b

where:
  p = estimated probability of winning
  q = 1 - p
  b = net odds per $1 staked = (1 - price) / price
      (stake `price` to win `1 - price` profit if correct)

Full Kelly is only correct if `p` is known exactly. In practice `p` is a
statistical *estimate* (see pricing_edge.py), so betting full Kelly on a
noisy estimate is a well-known way to over-bet and blow up a bankroll.
This module defaults to fractional Kelly (see `KELLY_FRACTION` in
config.py) as a margin of safety against estimation error.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class KellyResult:
    p_win: float
    price: float
    b: float
    raw_fraction: float      # full-Kelly fraction, can be negative (no edge)
    applied_fraction: float  # after fractional-Kelly scaling + hard cap


def kelly_fraction(p_win: float, price: float) -> float:
    """Full-Kelly fraction of bankroll to stake. Can be negative (meaning:
    don't bet — there is no edge, or the edge is on the other outcome)."""
    if not 0.0 <= p_win <= 1.0:
        raise ValueError(f"p_win must be in [0, 1], got {p_win}")
    if not 0.0 < price < 1.0:
        raise ValueError(f"price must be in (0, 1), got {price}")

    q = 1.0 - p_win
    b = (1.0 - price) / price
    return (p_win * b - q) / b


def sized_kelly_fraction(
    p_win: float,
    price: float,
    kelly_multiplier: float = 0.25,
    max_fraction: float = 0.05,
) -> KellyResult:
    """Applies fractional-Kelly scaling (default: quarter-Kelly) and a hard
    cap on top, then floors negative fractions at 0 (never bet against your
    own edge estimate)."""
    if not 0.0 < kelly_multiplier <= 1.0:
        raise ValueError(f"kelly_multiplier must be in (0, 1], got {kelly_multiplier}")
    if not 0.0 < max_fraction <= 1.0:
        raise ValueError(f"max_fraction must be in (0, 1], got {max_fraction}")

    q = 1.0 - p_win
    b = (1.0 - price) / price
    raw = (p_win * b - q) / b

    applied = max(0.0, raw) * kelly_multiplier
    applied = min(applied, max_fraction)

    return KellyResult(p_win=p_win, price=price, b=b, raw_fraction=raw, applied_fraction=applied)
