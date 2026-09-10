"""
Backtest engine: replays historical resolved markets in chronological order,
applying (in order) the price-error correction, the EV filter, and Kelly
sizing — exactly the pipeline the live bot uses — and reports whether the
strategy would have made or lost money.

This is the tool that answers "does this actually work?" instead of trusting
an advertised win rate. Feed it real historical data (see
fetch_market_history.py) or your own dataset in the same format.

IMPORTANT CAVEATS (read before trusting any backtest output):
  - Past resolved markets are not a random sample of the future. A positive
    backtest result is evidence the *pattern existed historically* in your
    sample, not a guarantee it persists or that it isn't overfit.
  - This backtest ignores execution frictions that matter in practice:
    slippage, the fact that large orders move the price, gas fees, and that
    a signal computed from a stale price may no longer be available by the
    time an order lands.
  - `min_samples` per bucket and walk-forward estimation reduce curve-fitting
    but do not eliminate it. Treat results as a lower bound on how wrong
    reality could be, not an upper bound on how well it will do.
"""
from dataclasses import dataclass, field
from typing import List, Sequence

from ev import expected_value
from kelly import sized_kelly_fraction
from pricing_edge import ResolvedMarket, WalkForwardEdgeEstimator


@dataclass
class BacktestConfig:
    starting_bankroll: float = 1000.0
    min_ev_roi: float = 0.02          # require at least 2% edge above breakeven
    kelly_multiplier: float = 0.25    # quarter-Kelly
    max_fraction_per_bet: float = 0.05  # never stake more than 5% of bankroll on one bet
    min_bucket_samples: int = 30


@dataclass
class TradeRecord:
    timestamp: float
    entry_price: float
    p_hat: float
    ev_roi: float
    stake_fraction: float
    stake_usd: float
    outcome: int
    pnl: float
    bankroll_after: float


@dataclass
class BacktestResult:
    trades: List[TradeRecord] = field(default_factory=list)
    starting_bankroll: float = 0.0
    ending_bankroll: float = 0.0

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.outcome for t in self.trades) / len(self.trades)

    @property
    def total_pnl(self) -> float:
        return self.ending_bankroll - self.starting_bankroll

    @property
    def roi(self) -> float:
        if self.starting_bankroll == 0:
            return 0.0
        return self.total_pnl / self.starting_bankroll

    @property
    def max_drawdown(self) -> float:
        peak = self.starting_bankroll
        max_dd = 0.0
        bankroll = self.starting_bankroll
        for t in self.trades:
            bankroll = t.bankroll_after
            peak = max(peak, bankroll)
            if peak > 0:
                max_dd = max(max_dd, (peak - bankroll) / peak)
        return max_dd

    def summary(self) -> str:
        return (
            f"trades={self.n_trades} win_rate={self.win_rate:.1%} "
            f"pnl=${self.total_pnl:,.2f} roi={self.roi:.1%} "
            f"max_drawdown={self.max_drawdown:.1%} "
            f"ending_bankroll=${self.ending_bankroll:,.2f}"
        )


def run_backtest(
    markets: Sequence[ResolvedMarket],
    cfg: BacktestConfig = BacktestConfig(),
) -> BacktestResult:
    """`markets` must be in the format the strategy would have seen it live:
    entry_price is the price at the moment of hypothetical entry, outcome is
    1/0 for whether that side won, resolved_at orders trades in time.

    Delta is estimated walk-forward (see pricing_edge.py) so no trade uses
    information from markets that hadn't resolved yet at entry time — the
    backtest cannot see its own future.
    """
    ordered = sorted(markets, key=lambda m: m.resolved_at)
    estimator = WalkForwardEdgeEstimator(ordered, min_samples=cfg.min_bucket_samples)

    bankroll = cfg.starting_bankroll
    result = BacktestResult(starting_bankroll=bankroll, ending_bankroll=bankroll)

    for m in ordered:
        p_hat = estimator.estimate(m.entry_price, m.resolved_at)
        ev = expected_value(p_hat, m.entry_price)
        if ev.ev_roi <= cfg.min_ev_roi:
            continue

        kelly = sized_kelly_fraction(
            p_hat, m.entry_price,
            kelly_multiplier=cfg.kelly_multiplier,
            max_fraction=cfg.max_fraction_per_bet,
        )
        if kelly.applied_fraction <= 0:
            continue

        stake = bankroll * kelly.applied_fraction
        shares = stake / m.entry_price
        pnl = shares * (1.0 - m.entry_price) if m.outcome == 1 else -stake
        bankroll += pnl

        result.trades.append(TradeRecord(
            timestamp=m.resolved_at,
            entry_price=m.entry_price,
            p_hat=p_hat,
            ev_roi=ev.ev_roi,
            stake_fraction=kelly.applied_fraction,
            stake_usd=stake,
            outcome=m.outcome,
            pnl=pnl,
            bankroll_after=bankroll,
        ))

    result.ending_bankroll = bankroll
    return result
