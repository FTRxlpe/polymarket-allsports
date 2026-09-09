"""
Risk guard-rails, independent of the strategy math. Even a mathematically
correct edge estimate can blow up a bankroll without limits on daily
exposure, position count, and loss streaks — Kelly sizing bounds a single
bet's fraction, not the bot's aggregate behavior over a day or a losing run.

State is persisted to state/risk_state.json so a restart doesn't reset caps.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import config

logger = logging.getLogger("risk_manager")

STATE_PATH = os.path.join(os.path.dirname(__file__), "state", "risk_state.json")


@dataclass
class RiskState:
    bankroll: float = config.STARTING_BANKROLL
    day_key: str = ""
    spent_today: float = 0.0
    pnl_today: float = 0.0
    bets_today: int = 0
    consecutive_losses: int = 0
    paused: bool = False
    open_positions: List[str] = field(default_factory=list)
    cooldowns: Dict[str, float] = field(default_factory=dict)


class RiskManager:
    def __init__(self):
        self.state = self._load()
        self._roll_day_if_needed()

    def _load(self) -> RiskState:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH) as f:
                return RiskState(**json.load(f))
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
            self.state.pnl_today = 0.0
            self.state.bets_today = 0
            self.state.paused = False
            self._save()

    def check(self, market_key: str, stake_usd: float) -> Optional[str]:
        """Returns None if the trade passes all risk checks, else a reason
        string for rejection."""
        self._roll_day_if_needed()

        if self.state.paused:
            return "bot is paused (loss streak or manual pause)"

        daily_loss_cap = config.DAILY_LOSS_CAP_FRACTION * self.state.bankroll
        if self.state.pnl_today <= -daily_loss_cap:
            return f"daily loss cap reached (${self.state.pnl_today:.2f})"

        if self.state.bets_today >= config.MAX_BETS_PER_DAY:
            return f"max bets/day reached ({self.state.bets_today}/{config.MAX_BETS_PER_DAY})"

        if len(self.state.open_positions) >= config.MAX_OPEN_POSITIONS:
            return f"max open positions reached ({config.MAX_OPEN_POSITIONS})"

        expiry = self.state.cooldowns.get(market_key)
        if expiry and time.time() < expiry:
            remaining = int((expiry - time.time()) / 60)
            return f"cooldown active on {market_key} ({remaining} min left)"

        if market_key in self.state.open_positions:
            return "position already open on this market"

        if stake_usd > self.state.bankroll:
            return "stake exceeds current bankroll"

        return None

    def record_bet_placed(self, market_key: str, stake_usd: float):
        self.state.spent_today += stake_usd
        self.state.bets_today += 1
        self.state.open_positions.append(market_key)
        self.state.cooldowns[market_key] = time.time() + config.COOLDOWN_MINUTES * 60
        self._save()
        logger.info(f"[BET PLACED] {market_key} ${stake_usd:.2f}")

    def record_result(self, market_key: str, won: bool, pnl: float):
        if market_key in self.state.open_positions:
            self.state.open_positions.remove(market_key)

        self.state.bankroll += pnl
        self.state.pnl_today += pnl

        if won:
            self.state.consecutive_losses = 0
        else:
            self.state.consecutive_losses += 1
            if self.state.consecutive_losses >= config.LOSS_STREAK_PAUSE:
                self.state.paused = True
                logger.warning(
                    f"[PAUSE] {self.state.consecutive_losses} consecutive losses — "
                    f"bot paused. Review before resuming (edit state/risk_state.json, "
                    f"set paused=false)."
                )

        self._save()
        logger.info(
            f"[RESULT] {market_key}: {'WIN' if won else 'LOSS'} "
            f"pnl=${pnl:.2f} bankroll=${self.state.bankroll:.2f}"
        )
