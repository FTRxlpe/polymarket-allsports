"""
Two-tier consensus rule:
  - The instant CONSENSUS_WALLET_THRESHOLD (2) distinct watched wallets have
    bought the same outcome of the same market within TIME_WINDOW_MINUTES,
    fire a "base" signal — the bot places its normal bet size.
  - If the count for that same market+outcome later reaches
    DOUBLE_UP_THRESHOLD (4) within the same window, fire a second
    "double_up" signal — the bot places ANOTHER trade of the same base
    size, so the cumulative stake on that position is doubled.

Each tier only fires ONCE per market+outcome (tracked via `_fired_base` /
`_fired_double`), so it doesn't re-trigger on every poll once a threshold is
already crossed.

Note on "instant": this engine reacts as soon as it's called, and main.py
calls it every POLL_INTERVAL_SECONDS (default 2s). That's as close to
instant as a polling architecture gets — true sub-second reaction needs a
WebSocket trade feed instead of polling the Data API, see README "Going
faster than polling".

Note on reputation weighting: threshold-crossing is decided on
weighted_count, not the raw wallet_count, when config.REPUTATION_WEIGHTING_ENABLED
is True (see wallet_reputation.py) — a wallet with a proven track record on
past copied trades counts for more (or less) than one flat vote. Wallets
with no resolved history yet default to a neutral weight of 1.0, so this
only changes behavior once the bot has actually learned something.
Banned wallets (see wallet_reputation.is_banned) never make it this far —
wallet_tracker.py stops fetching their trades entirely.
"""
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set

import config
import wallet_reputation
from wallet_tracker import WhaleTrade

logger = logging.getLogger("consensus_engine")


@dataclass
class ConsensusSignal:
    market_slug: str
    outcome: str
    wallet_count: int
    weighted_count: float
    contributing_wallets: List[str]
    avg_price: float
    first_seen: float
    signal_type: str = "base"   # "base" or "double_up"
    multiplier: float = 1.0


class ConsensusEngine:
    def __init__(self):
        # key: (market_slug, outcome) -> {wallet_nickname: WhaleTrade}
        self._pending: Dict[tuple, Dict[str, WhaleTrade]] = {}
        self._fired_base: Set[tuple] = set()
        self._fired_double: Set[tuple] = set()

    def _prune_expired(self):
        cutoff = time.time() - config.TIME_WINDOW_MINUTES * 60
        for key in list(self._pending.keys()):
            self._pending[key] = {
                wallet: t for wallet, t in self._pending[key].items()
                if t.timestamp >= cutoff
            }
            if not self._pending[key]:
                del self._pending[key]
                self._fired_base.discard(key)
                self._fired_double.discard(key)

    def _make_signal(self, key: tuple, wallets: Dict[str, WhaleTrade], signal_type: str,
                      weighted_count: float) -> ConsensusSignal:
        trade_list = list(wallets.values())
        avg_price = sum(t.price for t in trade_list) / len(trade_list)
        return ConsensusSignal(
            market_slug=key[0],
            outcome=key[1],
            wallet_count=len(wallets),
            weighted_count=weighted_count,
            contributing_wallets=list(wallets.keys()),
            avg_price=avg_price,
            first_seen=min(t.timestamp for t in trade_list),
            signal_type=signal_type,
            multiplier=1.0,  # each fired signal (base or double_up) uses the
                              # normal bet size — firing twice is what doubles
                              # the cumulative stake, not a bigger multiplier
        )

    def ingest(self, trades: List[WhaleTrade]) -> List[ConsensusSignal]:
        self._prune_expired()

        for t in trades:
            key = (t.market_slug, t.outcome)
            self._pending.setdefault(key, {})[t.wallet_nickname] = t  # last trade per wallet

        signals: List[ConsensusSignal] = []
        for key, wallets in self._pending.items():
            count = len(wallets)

            if config.REPUTATION_WEIGHTING_ENABLED:
                weights, _ = wallet_reputation.get_weights_and_bans(wallets.keys())
                weighted_count = sum(weights.values())
            else:
                weighted_count = float(count)  # weighting off: behaves exactly like the old flat count
            effective_count = weighted_count

            if key not in self._fired_base and effective_count >= config.CONSENSUS_WALLET_THRESHOLD:
                signal = self._make_signal(key, wallets, "base", weighted_count)
                signals.append(signal)
                self._fired_base.add(key)
                logger.info(
                    f"[CONSENSUS REACHED] {key[0]} / {key[1]} — "
                    f"{count} wallets agreed (weighted {weighted_count:.2f}, base trade): "
                    f"{list(wallets.keys())}"
                )

            # Double-up can only fire AFTER the base signal has fired for
            # this market+outcome (it's an addition to an existing trade,
            # not a substitute for it).
            if (key in self._fired_base and key not in self._fired_double
                    and effective_count >= config.DOUBLE_UP_THRESHOLD):
                signal = self._make_signal(key, wallets, "double_up", weighted_count)
                signals.append(signal)
                self._fired_double.add(key)
                logger.info(
                    f"[DOUBLE-UP REACHED] {key[0]} / {key[1]} — "
                    f"{count} wallets agreed (weighted {weighted_count:.2f}, doubling stake): "
                    f"{list(wallets.keys())}"
                )

        return signals

    def clear_market(self, market_slug: str):
        """Call once a market's position is fully closed out (not after
        every trade — a double_up trade on the same market+outcome must
        still be recognized as the SAME position, not cleared prematurely)."""
        for key in list(self._pending.keys()):
            if key[0] == market_slug:
                del self._pending[key]
                self._fired_base.discard(key)
                self._fired_double.discard(key)
