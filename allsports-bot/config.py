"""
Configuration for the Polymarket whale-consensus bot. Sport-agnostic —
controlled by SPORT_TAG_SLUG below.
"""
import os
from dataclasses import dataclass
from typing import Dict, List

# --------------------------------------------------------------------------
# MODE
# --------------------------------------------------------------------------
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

# --------------------------------------------------------------------------
# CATEGORY / DOMAIN
# --------------------------------------------------------------------------
# Which Polymarket tag to trade. Filtering is done via the official Gamma
# API tag system (see sport_filter.py) rather than a slug prefix, since
# market slugs are named per-event, not consistently.
SPORT_TAG_SLUG = "sports"

# Which category to pull the wallet leaderboard from (data-api.polymarket.com
# /v1/leaderboard?category=X). Valid values include: OVERALL, POLITICS,
# SPORTS, CRYPTO, CULTURE, ECONOMICS, TECH, FINANCE. Keep this aligned with
# SPORT_TAG_SLUG above — e.g. both set to the economics/macro domain.
LEADERBOARD_CATEGORY = "SPORTS"

# Some domains (sports, esports) name every market slug with a shared prefix
# ("ufc-...", "nba-..."), which sport_filter.py uses as a sanity check
# against mislabeled tag/series data. Political market slugs are one-off
# phrases with no shared prefix ("will-trump-win-2024", "russia-ukraine-
# ceasefire"...), so that check doesn't apply there. Sports slugs DO follow
# this convention, so keep the sanity check enabled here.
DISABLE_SANITY_CHECK = False

# --------------------------------------------------------------------------
# WATCHED WALLETS
# --------------------------------------------------------------------------
# Auto-loaded from found_wallets_top50.txt if it exists next to this file
# (that's what discover_top50_alltime.py writes) — so re-running the
# discovery script and re-running the bot always uses the latest list,
# with no manual copy-pasting of addresses required.
#
# If that file doesn't exist yet, falls back to the 19 wallets found in the
# earlier UFC-specific screening (still valid, just a smaller starting set).
_FALLBACK_WATCHED_WALLETS: Dict[str, str] = {
    "Talvez10": "0xa71093cafc0c099b4ccab24c3cb8018d817923c4",             # 91 buys/10w, PnL +110,109$
    "surfandturf": "0x9f2fe025f84839ca81dd8e0338892605702d2ca8",          # 77 buys/10w, PnL +916,360$
    "matanovik": "0x39d3c773be30fcc73161fc6768f46d563a779ef0",           # 50 buys/10w, PnL +316,962$
    "jtwyslljy": "0x9cb990f1862568a63d8601efeebe0304225c32f2",           # 15 buys/10w, PnL +2,483,103$
    "Nooserac": "0xf68a281980f8c13828e84e147e3822381d6e5b1b",            # 14 buys/10w, PnL +77,809$
    "no1dodgersfan": "0xb8ef617fd5d960e61e56c50d2971697300b32864",       # 12 buys/10w, PnL +3,353$
    "whale-2c3350": "0x2c335066fe58fe9237c3d3dc7b275c2a034a0563",        # 11 buys/10w, PnL +4,515,806$
    "Jsram": "0x83720820a8aa6c3f20ad71850e7a1a17d16c5223",               # 6 buys/10w, PnL +62,037$
    "Netrol": "0x23c8a4c266d10ba5846837eac391fea89ed6f293",              # 6 buys/10w, PnL +132,666$
    "AV23IUa": "0xdb859a551fcf56e49416160911476bea7307152f",             # 6 buys/10w, PnL +123,355$
    "hansama231": "0x381b9294c1b95b61d018ff56312fbcc4897c4d74",          # 4 buys/10w, PnL +116,860$
    "BreakTheBank": "0xf0318c32136c2db7fec88b84869aee6a1106c80c",        # 2 buys/10w, PnL +223,383$
    "jarosbill": "0x927cf2bb94d15707993f954552e56c74eb6d6633",           # 2 buys/10w, PnL +23,073$
    "monkeymashingkeyboard": "0x684baa57c338c2549aec0aa3f034f695d72a8409",  # 2 buys/10w, PnL +90,360$
    "rabbitfoot1": "0x10a6fadcbacd66330862206f6199b197e3ad4d8b",         # 1 buy/10w, PnL +86,185$
    "sulumos": "0x9db82de5a71ae539bc82f4d9ac3a007c7d742eff",             # 1 buy/10w, PnL +48,609$
    "CoffeeDespiser": "0x629c2844d5c0e36774a67fe10dcd43ca31a76c01",      # 1 buy/10w, PnL +27,447$
    "whale-424779": "0x42477970683d4d0a52ec7082fee5d760cc5591c4",        # 1 buy/10w, PnL +111,792$
    "Allezpapa": "0xe549581668a5751c1972d3ad2d1991d900bd2d54",           # 1 buy/10w, PnL +4,280,723$
}

WATCHED_WALLETS: Dict[str, str] = _FALLBACK_WATCHED_WALLETS
_wallets_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "found_wallets_top50.txt")
if os.path.exists(_wallets_file):
    try:
        _ns = {}
        with open(_wallets_file) as _f:
            exec(_f.read(), _ns)
        _loaded = _ns.get("WATCHED_WALLETS")
        if _loaded:
            WATCHED_WALLETS = _loaded
    except Exception as _e:
        print(f"[config.py] Failed to load {_wallets_file}, using fallback wallets: {_e}")

# --------------------------------------------------------------------------
# CONSENSUS RULE
# --------------------------------------------------------------------------
# Trigger a trade the moment this many DISTINCT watched wallets have bought
# the same outcome of the same market within TIME_WINDOW_MINUTES.
CONSENSUS_WALLET_THRESHOLD = 3   # trade the instant 3 wallets agree
DOUBLE_UP_THRESHOLD = 6          # if 6+ agree, place a second same-size trade to double total stake

# Window during which wallets buying the same outcome are considered part of
# the same signal. Kept short since the goal is near-simultaneous agreement,
# not a slow accumulation over hours.
TIME_WINDOW_MINUTES = 15

# --------------------------------------------------------------------------
# CORE FILTERS (same protective role as before)
# --------------------------------------------------------------------------
COOLDOWN_MINUTES = 60           # lock-out per market+outcome after a bet
MIN_WHALE_TRADE_USD = 200       # minimum whale trade size to count toward consensus
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
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "2"))
