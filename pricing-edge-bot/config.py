"""
Configuration for the pricing-edge bot (price-error correction + EV + Kelly).

This bot is standalone: it does not import from, depend on, or share state
with any other bot in this repository.
"""
import os

# --------------------------------------------------------------------------
# MODE — defaults to paper trading. Live trading requires explicitly
# setting both PAPER_TRADING=false AND WALLET_PRIVATE_KEY in .env.
# --------------------------------------------------------------------------
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

# --------------------------------------------------------------------------
# SPORT / MARKET SCOPE
# --------------------------------------------------------------------------
SPORT_TAG_SLUG = os.getenv("SPORT_TAG_SLUG", "tennis")

# --------------------------------------------------------------------------
# STRATEGY PARAMETERS
# --------------------------------------------------------------------------
# A bucket needs at least this many resolved historical markets before its
# price-error estimate (delta) is trusted at all.
MIN_BUCKET_SAMPLES = int(os.getenv("MIN_BUCKET_SAMPLES", "30"))

# Minimum expected-ROI edge (after the delta correction) required to trade.
# This is a margin of safety on top of breakeven, since p_hat is itself an
# estimate with error bars, not a certainty.
MIN_EV_ROI = float(os.getenv("MIN_EV_ROI", "0.02"))

# Fractional Kelly multiplier. 1.0 = full Kelly (NOT recommended — Kelly
# assumes p is known exactly; ours is a noisy estimate). 0.25 = quarter
# Kelly, a common industry default that trades some growth rate for much
# lower variance/drawdown risk under estimation error.
KELLY_MULTIPLIER = float(os.getenv("KELLY_MULTIPLIER", "0.25"))

# Hard cap on stake size regardless of what Kelly says, as a backstop
# against a bad delta estimate producing an oversized bet.
MAX_FRACTION_PER_BET = float(os.getenv("MAX_FRACTION_PER_BET", "0.05"))

# --------------------------------------------------------------------------
# RISK MANAGEMENT (same protective layers as the repo's other bots)
# --------------------------------------------------------------------------
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
MAX_BETS_PER_DAY = int(os.getenv("MAX_BETS_PER_DAY", "10"))
DAILY_LOSS_CAP_FRACTION = float(os.getenv("DAILY_LOSS_CAP_FRACTION", "0.10"))  # of bankroll
LOSS_STREAK_PAUSE = int(os.getenv("LOSS_STREAK_PAUSE", "5"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "60"))

# --------------------------------------------------------------------------
# POLYMARKET / CHAIN CONFIG
# --------------------------------------------------------------------------
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137

WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "")
STARTING_BANKROLL = float(os.getenv("STARTING_BANKROLL", "100"))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
