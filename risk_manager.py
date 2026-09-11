"""
Implements strategy layers 4-10:
  4. Bankroll Sizer        8. Price Range Guard
  5. Daily Budget Cap      9. Max Open Positions
  6. Cooldown Lock        10. Loss Streak Pause
  7. Category Filter (also enforced in wallet_tracker as an early filter)

State is persisted to state/risk_state.json so a restart doesn't reset caps,
cooldowns, or the loss-streak counter.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import config
from consensus_engine import ConsensusSignal

logger = logging.getLogger("risk_manager")

STATE_PATH = os.path.join(os.path.dirname(__file__), "state", "risk_state.json")


@dataclass
class OpenPosition:
    market_slug: str
    outcome: str
    shares: float           # total outcome shares held (accumulates on double_up)
    bet_size_usd: float     # total USD staked (base + any double_up)
    contributing_wallets: List[str] = field(default_factory=list)  # union across base + double_up
    event_slug: Optional[str] = None  # needed for resolution_watcher.py's lookup — see market_resolver.py
    opened_at: float = field(default_factory=time.time)


@dataclass
class RiskState:
    bankroll: float = config.STARTING_BANKROLL
    day_key: str = ""                       # UTC date string, resets daily counters
    spent_today: float = 0.0
    bets_today: int = 0
    consecutive_losses: int = 0
    paused: bool = False
    open_positions: List[dict] = field(default_factory=list)   # see OpenPosition
    cooldowns: Dict[str, float] = field(default_factory=dict)  # "slug|outcome" -> expiry ts


class RiskManager:
    def __init__(self):
        self.state = self._load()
        self._roll_day_if_needed()

    # ---------------- persistence ----------------
    def _load(self) -> RiskState:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH) as f:
                data = json.load(f)
            return RiskState(**data)
        return RiskState(day_key=self._today_key())

    def _save(self):
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(asdict(self.state), f, indent=2)

    @staticmethod
    def _today_key() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _roll_day_if_needed(self):
        today = self._today_key()
        if self.state.day_key != today:
            logger.info(f"New UTC day ({today}) — resetting daily counters")
            self.state.day_key = today
            self.state.spent_today = 0.0
            self.state.bets_today = 0
            self.state.paused = False  # daily cap / pause resets at UTC midnight
            self._save()

    # ---------------- sizing (layer 4) ----------------
    def compute_bet_size(self, multiplier: float) -> float:
        tier = config.get_bankroll_tier(self.state.bankroll)
        if tier.is_percentage:
            base = tier.base_bet * self.state.bankroll
            max_bet = tier.max_bet * self.state.bankroll
        else:
            base = tier.base_bet
            max_bet = tier.max_bet
        return min(base * multiplier, max_bet)

    # ---------------- gate check (layers 5,6,8,9,10) ----------------
    def check(self, signal: ConsensusSignal, is_addition: bool = False) -> Optional[str]:
        """Returns None if the signal passes all risk checks, else a string
        reason for why it was rejected. `is_addition=True` (used for
        double_up signals) skips the cooldown and already-open-position
        checks, since that trade is intentionally adding to a position the
        bot itself just opened moments earlier — not a fresh, separate bet."""
        self._roll_day_if_needed()

        if self.state.paused:
            return "bot is paused (loss streak or manual pause)"

        tier = config.get_bankroll_tier(self.state.bankroll)
        daily_cap = tier.daily_cap * self.state.bankroll if tier.is_percentage else tier.daily_cap
        if self.state.spent_today >= daily_cap:
            return f"daily cap reached (${self.state.spent_today:.2f} / ${daily_cap:.2f})"

        if self.state.bets_today >= tier.max_bets_per_day:
            return f"max bets/day reached ({self.state.bets_today}/{tier.max_bets_per_day})"

        if not is_addition and len(self.state.open_positions) >= config.MAX_OPEN_POSITIONS:
            return f"max open positions reached ({config.MAX_OPEN_POSITIONS})"

        if not is_addition:
            cooldown_key = f"{signal.market_slug}|{signal.outcome}"
            expiry = self.state.cooldowns.get(cooldown_key)
            if expiry and time.time() < expiry:
                remaining = int((expiry - time.time()) / 60)
                return f"cooldown active on {cooldown_key} ({remaining} min left)"

        if not (config.PRICE_MIN <= signal.avg_price <= config.PRICE_MAX):
            return f"price {signal.avg_price:.2f} outside range [{config.PRICE_MIN}, {config.PRICE_MAX}]"

        if not is_addition and self._has_open_position(signal.market_slug):
            return "position already open on this market"

        return None  # all checks passed

    def _has_open_position(self, market_slug: str) -> bool:
        return any(p["market_slug"] == market_slug for p in self.state.open_positions)

    # ---------------- state mutation after acting on a signal ----------------
    def record_bet_placed(self, signal: ConsensusSignal, bet_size: float, is_addition: bool = False):
        self.state.spent_today += bet_size
        self.state.bets_today += 1
        shares = bet_size / signal.avg_price if signal.avg_price else 0.0

        if is_addition:
            # Double-up: fold into the existing position on this market
            # instead of opening a second one, so PnL reconciles against the
            # full cumulative stake (base + double_up) once it resolves.
            # contributing_wallets accumulates the union of both signals'
            # wallets, so resolution_watcher.py credits/blames everyone who
            # actually contributed to the final result, not just whichever
            # tier fired last.
            for pos in self.state.open_positions:
                if pos["market_slug"] == signal.market_slug:
                    pos["shares"] += shares
                    pos["bet_size_usd"] += bet_size
                    pos["contributing_wallets"] = sorted(
                        set(pos.get("contributing_wallets", [])) | set(signal.contributing_wallets)
                    )
                    break
            else:
                self.state.open_positions.append(asdict(OpenPosition(
                    market_slug=signal.market_slug, outcome=signal.outcome,
                    shares=shares, bet_size_usd=bet_size,
                    contributing_wallets=list(signal.contributing_wallets),
                    event_slug=signal.event_slug,
                )))
        else:
            self.state.open_positions.append(asdict(OpenPosition(
                market_slug=signal.market_slug, outcome=signal.outcome,
                shares=shares, bet_size_usd=bet_size,
                contributing_wallets=list(signal.contributing_wallets),
                event_slug=signal.event_slug,
            )))
            cooldown_key = f"{signal.market_slug}|{signal.outcome}"
            self.state.cooldowns[cooldown_key] = time.time() + config.COOLDOWN_MINUTES * 60

        self._save()
        logger.info(
            f"[BET PLACED{' - DOUBLE-UP' if is_addition else ''}] "
            f"{signal.market_slug} / {signal.outcome} ${bet_size:.2f} "
            f"(wallet_count={signal.wallet_count}, type={signal.signal_type})"
        )

    def record_result(self, market_slug: str, won: bool, pnl: float):
        """Call this once a market resolves (see resolution_watcher.py)."""
        self.state.open_positions = [
            p for p in self.state.open_positions if p["market_slug"] != market_slug
        ]

        self.state.bankroll += pnl

        if won:
            self.state.consecutive_losses = 0
        else:
            self.state.consecutive_losses += 1
            if self.state.consecutive_losses >= config.LOSS_STREAK_PAUSE:
                self.state.paused = True
                logger.warning(
                    f"[PAUSE] {self.state.consecutive_losses} consecutive losses — "
                    f"bot paused. Resume manually by editing state/risk_state.json "
                    f"(set paused=false) once you've reviewed what happened."
                )

        self._save()
        logger.info(
            f"[RESULT] {market_slug}: {'WIN' if won else 'LOSS'} "
            f"pnl=${pnl:.2f} bankroll=${self.state.bankroll:.2f}"
        )
