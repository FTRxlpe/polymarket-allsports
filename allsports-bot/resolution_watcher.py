"""
Periodically checks whether open positions' markets have resolved, and if so
computes P&L and reports it to the RiskManager (updates bankroll, win-streak
tracking, and the loss-streak pause).

Run this as a second process alongside main.py:
    python resolution_watcher.py
"""
import json
import logging
import os
import time

from dotenv import load_dotenv

load_dotenv()

import config
from risk_manager import RiskManager
from market_resolver import MarketResolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("resolution_watcher")

CHECK_INTERVAL_SECONDS = 60


def get_winning_outcome(market: dict):
    """There is no "winningOutcome" field in Polymarket's API — the winner
    is determined from outcomePrices, which settle to ~1.0 for the winning
    outcome once resolution completes. Returns None if not confidently
    resolved yet."""
    outcomes = market.get("outcomes")
    prices = market.get("outcomePrices")
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    if isinstance(prices, str):
        prices = json.loads(prices)
    if not outcomes or not prices or len(outcomes) != len(prices):
        return None
    try:
        prices_f = [float(p) for p in prices]
    except (TypeError, ValueError):
        return None
    winner_idx = prices_f.index(max(prices_f))
    if prices_f[winner_idx] < 0.9:
        return None
    return outcomes[winner_idx]


def compute_pnl(position: dict, winning_outcome: str) -> tuple:
    """Returns (won, pnl) for a resolved binary market. Winning shares pay
    out $1 each; losing shares pay out $0. `position` holds the total shares
    and USD actually staked across base + any double_up (see
    risk_manager.OpenPosition)."""
    won = str(position["outcome"]).lower() == str(winning_outcome).lower()
    bet_size = position["bet_size_usd"]
    shares = position["shares"]

    pnl = (shares - bet_size) if won else -bet_size
    return won, pnl


def run():
    risk = RiskManager()
    resolver = MarketResolver()
    logger.info("Resolution watcher started")

    while True:
        for position in list(risk.state.open_positions):
            slug = position["market_slug"]
            try:
                market = resolver._get_market(slug)  # uses the reliable /events lookup
                if not market or not market.get("closed"):
                    continue

                winning_outcome = get_winning_outcome(market)
                if winning_outcome is None:
                    continue  # closed but not confidently settled yet, check again next cycle

                won, pnl = compute_pnl(position, winning_outcome)
                logger.info(
                    f"Market resolved: {slug} -> winner: {winning_outcome} "
                    f"(held: {position['outcome']})"
                )
                risk.record_result(slug, won=won, pnl=pnl)

            except Exception:
                logger.exception(f"Error checking resolution for {slug}")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
