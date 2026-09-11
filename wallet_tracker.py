"""
Polls Polymarket's public Data API for recent trades made by watched
wallets, keeping only BUY trades on active tennis markets above the minimum
whale trade size.
"""
import time
import logging
from dataclasses import dataclass
from typing import List, Optional

import requests

import config
import wallet_reputation
from sport_filter import MultiSportFilter

logger = logging.getLogger("wallet_tracker")


@dataclass
class WhaleTrade:
    wallet_nickname: str
    wallet_address: str
    market_slug: str
    outcome: str
    side: str
    price: float
    size_usd: float
    timestamp: float
    tx_hash: Optional[str] = None
    event_slug: Optional[str] = None  # parent event's own slug — see market_resolver.py's docstring


class WalletTracker:
    def __init__(self):
        self._seen_tx_hashes = set()
        self._logged_bans: set = set()  # avoid re-logging the same ban every poll cycle
        self.session = requests.Session()
        self.sport_filter = MultiSportFilter(config.SPORT_TAG_SLUGS)

    def fetch_recent_trades(self, address: str, limit: int = 20) -> List[dict]:
        url = f"{config.POLYMARKET_DATA_API}/trades"
        params = {"user": address, "limit": limit}
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch trades for {address}: {e}")
            return []

    def poll_once(self) -> List[WhaleTrade]:
        new_trades: List[WhaleTrade] = []

        # Wallets the reputation agent has auto-banned (see
        # wallet_reputation.py) for a proven poor track record on trades
        # this bot actually copied are skipped before even fetching their
        # trades — cheaper than filtering downstream, and means a banned
        # wallet's signals can never re-enter the pipeline through any path.
        banned = wallet_reputation.get_banned(config.WATCHED_WALLETS.keys())
        if banned and banned - self._logged_bans:
            logger.warning(f"[REPUTATION] No longer tracking banned wallets: {sorted(banned - self._logged_bans)}")
            self._logged_bans |= banned

        for nickname, address in config.WATCHED_WALLETS.items():
            if nickname in banned:
                continue
            address = address.lower()

            raw_trades = self.fetch_recent_trades(address)
            for t in raw_trades:
                tx_hash = t.get("transactionHash") or t.get("id")
                if not tx_hash or tx_hash in self._seen_tx_hashes:
                    continue

                side = (t.get("side") or "").upper()
                if side != "BUY":
                    continue

                slug = t.get("slug") or t.get("market_slug") or ""
                # See config.APPLY_SPORT_FILTER's docstring: backtest.py
                # never applied this filter, so leaving it on while trading
                # a non-sports category (e.g. TECH) would silently discard
                # almost every real signal.
                if config.APPLY_SPORT_FILTER and not self.sport_filter.is_match(slug):
                    continue  # not a currently-active market in a watched sport

                size_usd = float(t.get("size", 0)) * float(t.get("price", 0))
                if size_usd < config.MIN_WHALE_TRADE_USD:
                    continue

                trade = WhaleTrade(
                    wallet_nickname=nickname,
                    wallet_address=address,
                    market_slug=slug,
                    outcome=t.get("outcome", ""),
                    side=side,
                    price=float(t.get("price", 0)),
                    size_usd=size_usd,
                    timestamp=float(t.get("timestamp", time.time())),
                    tx_hash=tx_hash,
                    event_slug=t.get("eventSlug"),
                )
                self._seen_tx_hashes.add(tx_hash)
                new_trades.append(trade)
                logger.info(
                    f"[SIGNAL] {nickname} bought '{trade.outcome}' "
                    f"on {slug} @ {trade.price:.2f} for ${size_usd:.0f}"
                )

        return new_trades

    def run_forever(self, on_trades_callback):
        scope = f"'{config.SPORT_TAG_SLUG}'-tagged markets only" if config.APPLY_SPORT_FILTER \
            else f"all categories (sport filter off, sourced from {config.LEADERBOARD_CATEGORY} leaderboard)"
        logger.info(
            f"Tracking {len(config.WATCHED_WALLETS)} wallets, {scope}, "
            f"polling every {config.POLL_INTERVAL_SECONDS}s"
        )
        if len(config.WATCHED_WALLETS) == 0:
            logger.warning(
                "WATCHED_WALLETS is empty — paste your 50 addresses into "
                "config.py before running for real."
            )
        while True:
            try:
                new_trades = self.poll_once()
                if new_trades:
                    on_trades_callback(new_trades)
            except Exception:
                logger.exception("Error during poll cycle")
            time.sleep(config.POLL_INTERVAL_SECONDS)
