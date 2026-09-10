"""
Live scanner for the pricing-edge bot.

Pipeline per active tennis market:
  1. Pull the current price for each outcome (Gamma API).
  2. Estimate p_hat = price + delta, using bucket deltas computed from your
     local historical dataset (data/markets_history.jsonl — see
     fetch_market_history.py to build one; the bot refuses to trade a
     bucket with fewer than config.MIN_BUCKET_SAMPLES resolved markets).
  3. Compute EV; skip if it doesn't clear config.MIN_EV_ROI.
  4. Size the stake with fractional Kelly (config.KELLY_MULTIPLIER),
     capped at config.MAX_FRACTION_PER_BET of bankroll.
  5. Risk-manager gate (daily cap, position count, cooldowns, loss-streak
     pause).
  6. Execute — paper by default; live only with PAPER_TRADING=false and a
     private key.

Run `python backtest.py` (via the tests, or your own script) BEFORE ever
touching PAPER_TRADING=false — this scanner will happily paper-trade a
strategy that has never been shown to have any edge if you skip that step.
"""
import argparse
import json
import logging
import os
import time
from typing import Optional

import requests

import config
from ev import expected_value
from kelly import sized_kelly_fraction
from pricing_edge import ResolvedMarket, compute_bucket_deltas, estimated_true_probability, _bucket_of, DEFAULT_BUCKETS
from risk_manager import RiskManager
from trade_executor import TradeExecutor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("main")

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "markets_history.jsonl")


def load_bucket_deltas(path: str = HISTORY_PATH) -> dict:
    if not os.path.exists(path):
        logger.warning(
            f"{path} not found — no historical data to estimate price bias from. "
            f"Run fetch_market_history.py first. Every signal will fall back to "
            f"p_hat = price (no assumed edge) until you do."
        )
        return {}

    markets = []
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            markets.append(ResolvedMarket(
                entry_price=r["entry_price"], outcome=r["outcome"], resolved_at=r["resolved_at"]
            ))
    deltas = compute_bucket_deltas(markets, min_samples=config.MIN_BUCKET_SAMPLES)
    logger.info(f"Loaded {len(markets)} historical markets. Bucket deltas: {deltas}")
    return deltas


def fetch_active_markets(session: requests.Session, tag_slug: str) -> list:
    resp = session.get(
        f"{config.GAMMA_API}/markets",
        params={"tag": tag_slug, "active": "true", "closed": "false", "limit": 200},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_maybe_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def scan_once(deltas: dict, risk: RiskManager, executor: TradeExecutor, session: requests.Session):
    markets = fetch_active_markets(session, config.SPORT_TAG_SLUG)
    for market in markets:
        slug = market.get("slug")
        outcomes = _parse_maybe_json(market.get("outcomes"))
        prices = _parse_maybe_json(market.get("outcomePrices"))
        token_ids = _parse_maybe_json(market.get("clobTokenIds"))
        if not (slug and outcomes and prices and token_ids) or len(outcomes) != len(prices):
            continue

        for outcome, price_str, token_id in zip(outcomes, prices, token_ids):
            try:
                price = float(price_str)
            except (TypeError, ValueError):
                continue
            if not 0.01 < price < 0.99:
                continue

            bucket = _bucket_of(price, DEFAULT_BUCKETS)
            delta = deltas.get(bucket) if bucket else None
            p_hat = estimated_true_probability(price, delta)

            ev = expected_value(p_hat, price)
            if ev.ev_roi <= config.MIN_EV_ROI:
                continue

            kelly = sized_kelly_fraction(
                p_hat, price,
                kelly_multiplier=config.KELLY_MULTIPLIER,
                max_fraction=config.MAX_FRACTION_PER_BET,
            )
            if kelly.applied_fraction <= 0:
                continue

            stake = risk.state.bankroll * kelly.applied_fraction
            market_key = f"{slug}|{outcome}"

            reason = risk.check(market_key, stake)
            if reason:
                logger.info(f"[SKIP] {market_key} price={price:.2f} p_hat={p_hat:.2f}: {reason}")
                continue

            logger.info(
                f"[SIGNAL] {market_key} price={price:.2f} p_hat={p_hat:.2f} "
                f"ev_roi={ev.ev_roi:.1%} stake=${stake:.2f}"
            )
            executor.execute(slug, token_id, price, stake)
            risk.record_bet_placed(market_key, stake)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single scan and exit")
    args = parser.parse_args()

    deltas = load_bucket_deltas()
    risk = RiskManager()
    executor = TradeExecutor()
    session = requests.Session()

    logger.info(
        f"Starting pricing-edge bot. paper_trading={config.PAPER_TRADING} "
        f"bankroll=${risk.state.bankroll:.2f}"
    )

    while True:
        try:
            scan_once(deltas, risk, executor, session)
        except requests.RequestException as e:
            logger.warning(f"Scan failed: {e}")

        if args.once:
            break
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
