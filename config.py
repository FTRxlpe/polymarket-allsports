"""
Configuration for the Polymarket tennis whale-consensus bot.
"""
import os
from dataclasses import dataclass
from typing import Dict, List

# --------------------------------------------------------------------------
# MODE
# --------------------------------------------------------------------------
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

# --------------------------------------------------------------------------
# SPORT
# --------------------------------------------------------------------------
# Which Polymarket tag to trade. Filtering is done via the official Gamma
# API tag system (see sport_filter.py) rather than a slug prefix, since
# tennis market slugs are named per-tournament/matchup, not consistently.
SPORT_TAG_SLUG = "tennis"

# --------------------------------------------------------------------------
# WATCHED WALLETS
# --------------------------------------------------------------------------
# Paste your 50 addresses here — nickname is just a label for your own logs,
# it doesn't affect behavior. All wallets count equally toward the
# consensus threshold below (no tiers/weights in this version).
#
# Format: "nickname": "0xaddress"
WATCHED_WALLETS: Dict[str, str] = {
    # "whale-01": "0x0000000000000000000000000000000000000000",
    # "whale-02": "0x0000000000000000000000000000000000000000",
    # ... paste all 50 here ...
}

# --------------------------------------------------------------------------
# CONSENSUS RULE
# --------------------------------------------------------------------------
# Trigger a trade the moment this many DISTINCT watched wallets have bought
# the same outcome of the same market within TIME_WINDOW_MINUTES.
CONSENSUS_WALLET_THRESHOLD = 5

# Window during which wallets buying the same outcome are considered part of
# the same signal. Kept short since the goal is near-simultaneous agreement,
# not a slow accumulation over hours.
TIME_WINDOW_MINUTES = 15

# --------------------------------------------------------------------------
# CORE FILTERS (same protective role as before)
# --------------------------------------------------------------------------
COOLDOWN_MINUTES = 60           # lock-out per market+outcome after a bet
MIN_WHALE_TRADE_USD = 50        # minimum whale trade size to count toward consensus
                                  # (tennis markets trade smaller sizes than NBA typically)
PRICE_MIN = 0.20
PRICE_MAX = 0.80
MAX_OPEN_POSITIONS = 5
LOSS_STREAK_PAUSE = 4

# --------------------------------------------------------------------------
# BET SIZING
# --------------------------------------------------------------------------
# No weighting multiplier in this version — every triggered signal (5+
# wallets agreeing) gets the same base bet size for the current bankroll
# tier. Set to True if you later want size to keep scaling past 5 wallets.
SCALE_BET_WITH_EXTRA_WALLETS = False
EXTRA_WALLET_MULTIPLIER_STEP = 0.2   # +20% bet size per wallet beyond the threshold, if enabled
MAX_MULTIPLIER = 3.0


@dataclass
class BankrollTier:
    bankroll_min: float
    base_bet: float
    max_bet: float
    max_bets_per_day: int
    daily_cap: float
    is_percentage: bool = False


BANKROLL_TIERS: List[BankrollTier] = [
    BankrollTier(1000, 0.025, 0.04, 5, 0.15, is_percentage=True),
    BankrollTier(500, 25, 40, 5, 90),
    BankrollTier(200, 15, 25, 4, 45),
    BankrollTier(0, 8, 12, 4, 33),
]


def get_bankroll_tier(bankroll: float) -> BankrollTier:
    for tier in BANKROLL_TIERS:
        if bankroll >= tier.bankroll_min:
            return tier
    return BANKROLL_TIERS[-1]


def compute_multiplier(wallet_count: int) -> float:
    if not SCALE_BET_WITH_EXTRA_WALLETS:
        return 1.0
    extra = max(0, wallet_count - CONSENSUS_WALLET_THRESHOLD)
    return min(1.0 + extra * EXTRA_WALLET_MULTIPLIER_STEP, MAX_MULTIPLIER)


# --------------------------------------------------------------------------
# POLYMARKET / CHAIN CONFIG
# --------------------------------------------------------------------------
POLYMARKET_DATA_API = "https://data-api.polymarket.com"
POLYMARKET_CLOB_API = "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137

WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "")
STARTING_BANKROLL = float(os.getenv("STARTING_BANKROLL", "100"))

# Short poll interval for near-instant reaction. True sub-second reaction
# would require a WebSocket feed instead of polling — see README "Going
# faster than polling" for that upgrade path.
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
