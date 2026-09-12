"""
Consensus rule: the moment CONSENSUS_WALLET_THRESHOLD distinct watched
wallets have bought the same outcome of the same market within
TIME_WINDOW_MINUTES, fire a signal. Each signal is only fired ONCE per
market+outcome (tracked via `_fired`) so it doesn't re-trigger on every poll
once the threshold is already crossed.

Note on "instant": this engine reacts as soon as it's called, and main.py
calls it every POLL_INTERVAL_SECONDS (default 5s). That's as close to
instant as a polling architecture gets — true sub-second reaction needs a
WebSocket trade feed instead of polling the Data API, see README "Going
faster than polling".
"""
import time
import logging
from dataclasses import dataclass
from typing import Dict, List, Set

import config
from wallet_tracker import WhaleTrade

logger = logging.getLogger("consensus_engine")


@dataclass
class ConsensusSignal:
    market_slug: str
    outcome: str
    wallet_count: int
    contributing_wallets: List[str]
    avg_price: float
    first_seen: float
    multiplier: float = 1.0


class ConsensusEngine:
    def __init__(self):
        # key: (market_slug, outcome) -> {wallet_nickname: WhaleTrade}
        self._pending: Dict[tuple, Dict[str, WhaleTrade]] = {}
        # markets+outcomes already fired on, to avoid re-firing every poll
        self._fired: Set[tuple] = set()

    def _prune_expired(self):
        cutoff = time.time() - config.TIME_WINDOW_MINUTES * 60
        for key in list(self._pending.keys()):
            self._pending[key] = {
                wallet: t for wallet, t in self._pending[key].items()
                if t.timestamp >= cutoff
            }
            if not self._pending[key]:
                del self._pending[key]
                self._fired.discard(key)

    def ingest(self, trades: List[WhaleTrade]) -> List[ConsensusSignal]:
        self._prune_expired()

        for t in trades:
            key = (t.market_slug, t.outcome)
            self._pending.setdefault(key, {})[t.wallet_nickname] = t  # last trade per wallet

        signals: List[ConsensusSignal] = []
        for key, wallets in self._pending.items():
            if key in self._fired:
                continue  # already acted on this market+outcome this window

            if len(wallets) >= config.CONSENSUS_WALLET_THRESHOLD:
                trade_list = list(wallets.values())
                avg_price = sum(t.price for t in trade_list) / len(trade_list)
                signal = ConsensusSignal(
                    market_slug=key[0],
                    outcome=key[1],
                    wallet_count=len(wallets),
                    contributing_wallets=list(wallets.keys()),
                    avg_price=avg_price,
                    first_seen=min(t.timestamp for t in trade_list),
                    multiplier=config.compute_multiplier(len(wallets)),
                )
                signals.append(signal)
                self._fired.add(key)
                logger.info(
                    f"[CONSENSUS REACHED] {key[0]} / {key[1]} — "
                    f"{len(wallets)} wallets agreed: {list(wallets.keys())}"
                )

        return signals

    def clear_market(self, market_slug: str):
        """Call after acting on a signal so cooldowns/state don't get stale."""
        for key in list(self._pending.keys()):
            if key[0] == market_slug:
                del self._pending[key]
                self._fired.discard(key)
