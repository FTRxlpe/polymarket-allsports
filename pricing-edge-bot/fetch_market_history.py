"""
Pulls REAL resolved tennis markets from Polymarket's public APIs and writes
them to data/markets_history.jsonl in the format backtest.py expects.

This exists specifically so you don't have to trust the "72 million
transactions" claim from wherever you heard about this strategy — it lets
you build your own historical dataset from Polymarket's own public record
and measure the price bias yourself.

For each closed tennis market:
  1. Gamma API (`/markets`) gives us the final outcome (which side settled
     at price 1.0) and the CLOB token id for each outcome.
  2. CLOB API (`/prices-history`) gives us the price of that token at
     `--lookback-minutes` before the market closed — this is used as the
     hypothetical "entry price" (buying right before resolution is not a
     realistic strategy; the point is just to have a real, non-fabricated
     (price, outcome) pair. For a live bot you'd use the price at whatever
     lead time before match completion you actually intend to trade at).

No API key is required — both endpoints are public market data.

Usage:
    python fetch_market_history.py --limit 500 --lookback-minutes 60 \\
        --output data/markets_history.jsonl

Polymarket's API responses are not contractually stable; if field names
have changed since this was written, this script will log a warning and
skip markets it can't parse rather than fabricate data.
"""
import argparse
import json
import logging
import time
from typing import Optional

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("fetch_market_history")

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


def _parse_maybe_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def fetch_closed_markets(tag_slug: str, limit: int, session: requests.Session):
    markets = []
    offset = 0
    page_size = 100
    while len(markets) < limit:
        resp = session.get(
            f"{GAMMA_API}/markets",
            params={
                "tag": tag_slug,
                "closed": "true",
                "limit": min(page_size, limit - len(markets)),
                "offset": offset,
                "order": "endDate",
                "ascending": "false",
            },
            timeout=20,
        )
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break
        markets.extend(page)
        offset += len(page)
        if len(page) < page_size:
            break
    return markets[:limit]


def _resolution_timestamp(market: dict) -> Optional[float]:
    end_date = market.get("endDate") or market.get("closedTime")
    if not end_date:
        return None
    try:
        # Gamma returns ISO 8601 timestamps.
        import datetime
        return datetime.datetime.fromisoformat(end_date.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def _winning_token_id(market: dict) -> Optional[tuple]:
    """Returns (winning_token_id, other_token_id) or None if we can't tell."""
    outcomes = _parse_maybe_json(market.get("outcomes"))
    prices = _parse_maybe_json(market.get("outcomePrices"))
    token_ids = _parse_maybe_json(market.get("clobTokenIds"))

    if not (outcomes and prices and token_ids) or not (len(outcomes) == len(prices) == len(token_ids) == 2):
        return None

    try:
        prices = [float(p) for p in prices]
    except (TypeError, ValueError):
        return None

    # A settled binary market has one outcome at ~1.0 and the other at ~0.0.
    if prices[0] > prices[1]:
        return token_ids[0], token_ids[1]
    elif prices[1] > prices[0]:
        return token_ids[1], token_ids[0]
    return None


def fetch_price_at(token_id: str, before_ts: float, session: requests.Session) -> Optional[float]:
    """Price of `token_id` at the last available data point before
    `before_ts`, via the CLOB prices-history endpoint."""
    try:
        resp = session.get(
            f"{CLOB_API}/prices-history",
            params={"market": token_id, "startTs": int(before_ts - 6 * 3600), "endTs": int(before_ts)},
            timeout=15,
        )
        resp.raise_for_status()
        history = resp.json().get("history", [])
    except (requests.RequestException, ValueError) as e:
        logger.debug(f"prices-history failed for {token_id}: {e}")
        return None

    if not history:
        return None
    last_point = history[-1]
    price = last_point.get("p")
    return float(price) if price is not None else None


def build_dataset(tag_slug: str, limit: int, lookback_minutes: int) -> list:
    session = requests.Session()
    logger.info(f"Fetching up to {limit} closed '{tag_slug}' markets from Gamma API...")
    markets = fetch_closed_markets(tag_slug, limit, session)
    logger.info(f"Got {len(markets)} closed markets, resolving prices...")

    records = []
    for market in markets:
        resolved_at = _resolution_timestamp(market)
        winner = _winning_token_id(market)
        if resolved_at is None or winner is None:
            continue
        winning_token_id, losing_token_id = winner

        entry_ts = resolved_at - lookback_minutes * 60
        entry_price = fetch_price_at(winning_token_id, entry_ts, session)
        if entry_price is None:
            continue

        records.append({
            "entry_price": entry_price,
            "outcome": 1,
            "resolved_at": resolved_at,
            "slug": market.get("slug"),
        })
        # Also record the losing side as a separate (would-have-lost) data
        # point, since the strategy could equally have been offered that side.
        losing_entry_price = fetch_price_at(losing_token_id, entry_ts, session)
        if losing_entry_price is not None:
            records.append({
                "entry_price": losing_entry_price,
                "outcome": 0,
                "resolved_at": resolved_at,
                "slug": market.get("slug"),
            })

        time.sleep(0.1)  # be polite to the public API

    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="tennis")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--lookback-minutes", type=int, default=60)
    parser.add_argument("--output", default="data/markets_history.jsonl")
    args = parser.parse_args()

    records = build_dataset(args.tag, args.limit, args.lookback_minutes)
    if not records:
        logger.warning(
            "No records fetched. Either Polymarket's API shape has changed "
            "since this script was written, or there's no closed data for "
            "this tag/lookback combination. Check the endpoints manually "
            "before assuming the strategy has no signal."
        )
        return

    with open(args.output, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    logger.info(f"Wrote {len(records)} (price, outcome) records to {args.output}")


if __name__ == "__main__":
    main()
