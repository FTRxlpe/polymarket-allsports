"""
Reputation agent — the piece that makes the bot "learn from its mistakes".

Every other module treats a wallet's vote as worth exactly 1 count, forever,
regardless of how its past copied trades actually turned out. This module
closes that loop:

  - resolution_watcher.py calls record_outcome() for every wallet that
    contributed to a signal once that signal's market resolves — this is
    the only place real win/loss data enters the system.
  - wallet_tracker.py calls get_banned() once per poll cycle to stop even
    fetching trades from a wallet that's proven itself unreliable (saves
    API calls too, not just signal quality).
  - consensus_engine.py calls get_weight() for each wallet still in a
    pending signal, so a wallet with a proven edge counts for more than
    one vote and a mediocre one counts for less — instead of every wallet
    being treated as equally trustworthy just because it's on the list.

State lives in state/wallet_reputation.json so main.py (reads every poll
cycle) and resolution_watcher.py (writes as positions resolve) stay in
sync across process boundaries — the same file-based pattern risk_manager.py
already uses for risk_state.json.

Wallets are keyed by NICKNAME (not address) throughout, matching how
ConsensusSignal.contributing_wallets and config.WATCHED_WALLETS already
identify them everywhere else in the pipeline.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, asdict, field
from typing import Dict, Iterable, Set, Tuple

logger = logging.getLogger("wallet_reputation")

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "wallet_reputation.json")

# Bayesian shrinkage: every wallet starts from a neutral 50% prior worth
# PRIOR_STRENGTH "phantom" resolved trades. A wallet with only 1-2 real
# resolved trades barely moves off neutral (protects against one early
# lucky/unlucky result swinging its weight wildly); a wallet with hundreds
# of resolved trades converges to its true observed win rate. This is
# separate from — and deliberately more conservative than — the ban
# decision below, which uses the raw observed rate once there's enough
# sample size to trust it.
PRIOR_STRENGTH = 8
PRIOR_MEAN = 0.5

# A wallet is only auto-banned once there's enough resolved sample size to
# be confident it's genuinely bad, not just unlucky on a short run — below
# MIN_RESOLVED_FOR_BAN resolved trades, a wallet can never be banned no
# matter how badly it's currently doing.
MIN_RESOLVED_FOR_BAN = 12
BAN_WIN_RATE_THRESHOLD = 0.35

# Consensus weight is 2x the Bayesian win rate, so a wallet sitting exactly
# at the 50% prior weighs like 1 flat vote (matches the old unweighted
# behavior for a wallet with no track record yet), a proven 75% wallet
# weighs like 1.5 votes, a proven 25% wallet weighs like 0.5. Clipped so no
# single wallet's weight can explode or vanish outside this range —
# permanently dropping a wallet is the ban mechanism's job, not weighting's.
MIN_WEIGHT = 0.3
MAX_WEIGHT = 2.0
NEUTRAL_WEIGHT = 1.0  # weight for a wallet with zero resolved history


@dataclass
class WalletRecord:
    wins: int = 0
    losses: int = 0
    last_updated: float = field(default_factory=time.time)

    @property
    def resolved(self) -> int:
        return self.wins + self.losses

    @property
    def observed_win_rate(self) -> float:
        return self.wins / self.resolved if self.resolved else 0.5

    @property
    def bayesian_win_rate(self) -> float:
        return (PRIOR_STRENGTH * PRIOR_MEAN + self.wins) / (PRIOR_STRENGTH + self.resolved)


def load_all() -> Dict[str, WalletRecord]:
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH) as f:
        raw = json.load(f)
    return {nickname: WalletRecord(**rec) for nickname, rec in raw.items()}


def _save(records: Dict[str, WalletRecord]):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump({nickname: asdict(rec) for nickname, rec in records.items()}, f, indent=2)


def record_outcome(wallet: str, won: bool):
    """Call once per contributing wallet after a copied signal's market
    resolves (see resolution_watcher.py) — the bot's actual learning step.
    Safe to call from a different process than the one reading weights/bans
    since state round-trips through STATE_PATH."""
    records = load_all()
    rec = records.get(wallet, WalletRecord())
    if won:
        rec.wins += 1
    else:
        rec.losses += 1
    rec.last_updated = time.time()
    records[wallet] = rec
    _save(records)
    logger.info(
        f"[REPUTATION] {wallet}: {'WIN' if won else 'LOSS'} recorded — "
        f"{rec.wins}W/{rec.losses}L (observed {rec.observed_win_rate:.1%}, "
        f"weight {_weight_from_record(rec):.2f})"
        + (" — now over the auto-ban bar" if _banned_from_record(rec) else "")
    )


def _weight_from_record(rec: WalletRecord) -> float:
    weight = 2 * rec.bayesian_win_rate
    return max(MIN_WEIGHT, min(MAX_WEIGHT, weight))


def _banned_from_record(rec: WalletRecord) -> bool:
    return rec.resolved >= MIN_RESOLVED_FOR_BAN and rec.observed_win_rate <= BAN_WIN_RATE_THRESHOLD


def get_weight(wallet: str, records: Dict[str, WalletRecord] = None) -> float:
    """Consensus weight for this wallet's vote. A wallet with no resolved
    history yet gets neutral weight 1.0 — reputation only kicks in once
    the bot has actually learned something about it."""
    if records is None:
        records = load_all()
    rec = records.get(wallet)
    return NEUTRAL_WEIGHT if rec is None else _weight_from_record(rec)


def is_banned(wallet: str, records: Dict[str, WalletRecord] = None) -> bool:
    if records is None:
        records = load_all()
    rec = records.get(wallet)
    return False if rec is None else _banned_from_record(rec)


def get_weights_and_bans(wallets: Iterable[str]) -> Tuple[Dict[str, float], Set[str]]:
    """Batch version of get_weight()/is_banned() — one file read instead of
    one per wallet. Returns (weights, banned_set)."""
    records = load_all()
    wallets = list(wallets)
    weights = {w: get_weight(w, records) for w in wallets}
    banned = {w for w in wallets if is_banned(w, records)}
    return weights, banned


def get_banned(wallets: Iterable[str]) -> Set[str]:
    records = load_all()
    return {w for w in wallets if is_banned(w, records)}
