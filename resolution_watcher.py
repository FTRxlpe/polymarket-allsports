"""
Periodically checks whether open positions' markets have resolved, and if so
computes P&L and reports it to the RiskManager (updates bankroll, win-streak
tracking, and the loss-streak pause).

Run this as a second process alongside main.py:
    python resolution_watcher.py
"""
import logging
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

import config
from risk_manager import RiskManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("resolution_watcher")

CHECK_INTERVAL_SECONDS = 60


def fetch_market_status(slug: str) -> dict:
    """Look up a market's resolution status via the public Gamma API."""
    url = "https://gamma-api.polymarket.com/markets"
    resp = requests.get(url, params={"slug": slug}, timeout=10)
    resp.raise_for_status()
    results = resp.json()
    return results[0] if results else {}


def compute_pnl(position: dict, winning_outcome: str) -> tuple:
    """Returns (won, pnl) for a resolved binary market. Winning shares pay
    out $1 each; losing shares pay out $0. `position` holds the entry price
    and USD size actually staked (see risk_manager.OpenPosition)."""
    won = str(position["outcome"]).lower() == str(winning_outcome).lower()
    bet_size = position["bet_size_usd"]
    price = position["price"]

    if won:
        shares = bet_size / price if price else 0.0
        pnl = shares - bet_size  # payout ($1/share) minus the stake
    else:
        pnl = -bet_size

    return won, pnl


def run():
    risk = RiskManager()
    logger.info("Resolution watcher started")

    while True:
        for position in list(risk.state.open_positions):
            slug = position["market_slug"]
            try:
                market = fetch_market_status(slug)
                if not market.get("closed"):
                    continue

                winning_outcome = market.get("winningOutcome") or market.get("outcome")
                if not winning_outcome:
                    logger.warning(
                        f"Market {slug} is closed but has no winning outcome "
                        f"yet — will re-check next cycle."
                    )
                    continue

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
