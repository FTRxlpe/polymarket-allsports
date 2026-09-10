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
# SPORT_TAG_SLUG is a human-readable label only (used in log/README text) —
# it is NOT looked up directly against the Gamma API, because Polymarket has
# no generic umbrella tag for "all sports combined". Confirmed by running
# list_sport_tags.py against the live API: the tag_slug="sports" this used
# to be set to resolves (via tag_id) to unrelated non-sports markets, and
# the closest real tag match is "fox-sports" (a broadcaster tag, not
# content). So "all sports" is built as a UNION of the real per-sport tags
# below (see sport_filter.MultiSportFilter) instead of one tag lookup.
SPORT_TAG_SLUG = "sports"

# Real per-sport tags/leagues to union. Each entry is either a plain tag
# slug (sanity check expects that slug itself in results) or a
# (tag_slug, [expected_keywords]) tuple for tags whose real market-slug
# prefix differs from the tag name — verified with sample_sport_slugs.py
# against the live Gamma API, not guessed:
#
#   - nba/nfl/mlb/nhl/tennis: proven slug-prefix pattern (their own name IS
#     the prefix — nba-lal-bos-..., nfl-week-7-..., atp-... for tennis).
#     nfl/nhl/mlb aren't generic /tags entries but are "automated leagues"
#     sport_filter.py's series_id path (GET /sports) resolves.
#   - "ufc" alone does NOT resolve — there is no generic /tags entry for
#     it, and it isn't in /sports either. Real UFC (and boxing) match
#     markets live under tag_id=1355, slug "boxingmma" (sample checked:
#     "ufc-303-who-will-win-...", "ufc-fight-night-who-will-win-...",
#     "haney-vs-garcia-ruled-no-contest"), which doesn't contain "ufc" or
#     "boxingmma" itself in most slugs, hence the custom keywords.
#   - "formula-one" tag_id=100280 returns real race-outcome markets
#     ("will-max-verstappen-win-the-british-grand-prix") but slugged
#     "grand-prix", not "formula-one" — custom keyword needed too.
#
# Checked and deliberately EXCLUDED:
#   - "champions-league" (tag_id=1234): only long-range futures props
#     ("will-the-2027-uefa-champions-league-winner-come-from-england"),
#     no actual match-level markets seen — low value for a whale-consensus
#     strategy built around match outcomes.
#   - "college-football" (tag_id=636): polluted with unrelated novelty
#     markets (EA Sports cover-athlete votes, NFL draft speculation using
#     college players' names) rather than actual game outcomes — including
#     it would count irrelevant activity toward wallet screening.
#
# Still unverified: soccer (dozens of per-competition tags, no single
# generic one — see list_sport_tags.py's "soccer-*" entries), golf,
# motorsports beyond F1, cricket, rugby. Sample a tag_id with
# sample_sport_slugs.py before adding it here.
SPORT_TAG_SLUGS: List[str] = [
    "nba", "nfl", "mlb", "nhl",
    # "tennis" (tag_id=864, confirmed via list_sport_tags.py) used to
    # resolve to 0 markets here: /tags?slug=tennis silently returned an
    # unrelated tag_id (a Gamma bug, see _resolve_tag_id's comment), which
    # sport_filter.py trusted without validating — fixed there, but real
    # tennis match slugs are likely "atp-.../wta-..." rather than literally
    # containing "tennis", so give the sanity check both keywords.
    ("tennis", ["atp", "wta", "tennis"]),
    ("boxingmma", ["ufc", "vs-", "fight-night"]),
    ("formula-one", ["grand-prix"]),
]

# Which category to pull the wallet leaderboard from (data-api.polymarket.com
# /v1/leaderboard?category=X). Valid values include: OVERALL, POLITICS,
# SPORTS, CRYPTO, CULTURE, ECONOMICS, TECH, FINANCE. Keep this aligned with
# SPORT_TAG_SLUG above — e.g. both set to the economics/macro domain.
LEADERBOARD_CATEGORY = "SPORTS"

# Some domains (sports, esports) name every market slug with a shared prefix
# ("ufc-...", "nba-..."), which sport_filter.py uses as a sanity check
# against mislabeled tag/series data. Political market slugs are one-off
# phrases with no shared prefix ("will-trump-win-2024", "russia-ukraine-
# ceasefire"...), so that check doesn't apply there. Each individual sport
# tag in SPORT_TAG_SLUGS DOES follow this convention (its own slug appears
# in its own markets' slugs), so keep the sanity check enabled here — it's
# what caught the broken "sports" umbrella tag in the first place.
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
#
# The "buys/10w" comments below are stale — they were counted against a
# UFC-only filter, not the current all-sports one, so they badly
# undercount real activity. Confirmed via backtest.py: 3 of these wallets
# (whale-2c3350, rabbitfoot1, no1dodgersfan) actually trade ~60-135
# times/day across all sports combined — market-maker/arb bot territory,
# not conviction whales — and whale-2c3350 alone showed up in 14/14
# triggered consensus signals in a 30-day backtest (30.8% win rate, -43%
# ROI). Removed here; wallet_screening.py's new MAX_BUYS now filters this
# class of wallet out automatically for anyone re-run through discovery.
_FALLBACK_WATCHED_WALLETS: Dict[str, str] = {
    "Talvez10": "0xa71093cafc0c099b4ccab24c3cb8018d817923c4",             # PnL +110,109$
    "surfandturf": "0x9f2fe025f84839ca81dd8e0338892605702d2ca8",          # PnL +916,360$
    "matanovik": "0x39d3c773be30fcc73161fc6768f46d563a779ef0",           # PnL +316,962$
    "jtwyslljy": "0x9cb990f1862568a63d8601efeebe0304225c32f2",           # PnL +2,483,103$
    "Nooserac": "0xf68a281980f8c13828e84e147e3822381d6e5b1b",            # PnL +77,809$
    "Jsram": "0x83720820a8aa6c3f20ad71850e7a1a17d16c5223",               # PnL +62,037$
    "Netrol": "0x23c8a4c266d10ba5846837eac391fea89ed6f293",              # PnL +132,666$
    "AV23IUa": "0xdb859a551fcf56e49416160911476bea7307152f",             # PnL +123,355$
    "hansama231": "0x381b9294c1b95b61d018ff56312fbcc4897c4d74",          # PnL +116,860$
    "BreakTheBank": "0xf0318c32136c2db7fec88b84869aee6a1106c80c",        # PnL +223,383$
    "jarosbill": "0x927cf2bb94d15707993f954552e56c74eb6d6633",           # PnL +23,073$
    "monkeymashingkeyboard": "0x684baa57c338c2549aec0aa3f034f695d72a8409",  # PnL +90,360$
    "sulumos": "0x9db82de5a71ae539bc82f4d9ac3a007c7d742eff",             # PnL +48,609$
    "CoffeeDespiser": "0x629c2844d5c0e36774a67fe10dcd43ca31a76c01",      # PnL +27,447$
    "whale-424779": "0x42477970683d4d0a52ec7082fee5d760cc5591c4",        # PnL +111,792$
    "Allezpapa": "0xe549581668a5751c1972d3ad2d1991d900bd2d54",           # PnL +4,280,723$
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
CONSENSUS_WALLET_THRESHOLD = 2   # trade the instant 2 wallets agree
DOUBLE_UP_THRESHOLD = 4          # if 4+ agree, place a second same-size trade to double total stake

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
