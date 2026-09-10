"""
Expected-value math for a binary Polymarket contract.

A contract bought at `price` (in [0, 1]) costs `price` dollars per share and
pays $1 per share if the outcome resolves YES, $0 otherwise. So per $1 of
face value:
    Gain (if win)  = 1 - price   (profit, stake excluded)
    Cost (if lose) = price       (the full stake is lost)
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class EVResult:
    p_win: float
    price: float
    gain: float
    cost: float
    ev: float          # expected profit per $1 of face value (per share)
    ev_roi: float       # ev expressed as a return on the amount staked (ev / price)


def expected_value(p_win: float, price: float) -> EVResult:
    """EV = P_win * Gain - P_loss * Cost, per share."""
    if not 0.0 <= p_win <= 1.0:
        raise ValueError(f"p_win must be in [0, 1], got {p_win}")
    if not 0.0 < price < 1.0:
        raise ValueError(f"price must be in (0, 1), got {price}")

    p_loss = 1.0 - p_win
    gain = 1.0 - price
    cost = price
    ev = p_win * gain - p_loss * cost
    ev_roi = ev / price
    return EVResult(p_win=p_win, price=price, gain=gain, cost=cost, ev=ev, ev_roi=ev_roi)


def has_edge(p_win: float, price: float, min_ev_roi: float = 0.0) -> bool:
    """True if the contract's expected ROI clears `min_ev_roi` (a margin of
    safety above breakeven, since p_win is itself an estimate)."""
    return expected_value(p_win, price).ev_roi > min_ev_roi
