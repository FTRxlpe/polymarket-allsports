# Polymarket All-Sports Whale-Consensus Bot

Tracks up to 50 watched wallets across **all sports combined** (not one
specific sport). Two-tier trading rule:
- The instant **2 wallets** buy the same outcome of the same market, the
  bot places a trade.
- If it later reaches **4 wallets** agreeing (same market+outcome, same
  15-minute window), the bot places a **second trade of the same size**,
  doubling the cumulative stake on that position.

Polls every 2 seconds by default for near-instant reaction to reduce the
risk of the odds moving before the bot's copy trade lands.

## ⚠️ Read this before doing anything else

- **This code was written for you, from scratch, using Polymarket's official
  `py-clob-client` SDK.** Do not additionally install or run any other
  "Polymarket copy trading bot" repo you find on GitHub — several of the ones
  in search results asking for your private key show classic signs of wallet
  drainers (generic names, keyword-stuffed descriptions, anonymous authors).
- **Never share your private key with anyone, ever, including in a chat, a
  Discord, or a "support" DM.** Anyone who has it can move all your funds.
- **Use a dedicated wallet** funded only with the amount you're willing to
  risk on this bot — not your main wallet.
- Start in **paper trading mode** (the default) and let it run for at least
  a few days before considering live mode. Read every file in this project
  before you ever set `PAPER_TRADING=false`.
- This is trading software, not financial advice. Past backtest performance
  (from a 7-day, 56-signal sample) is not a reliable predictor of future
  results — that sample size is too small to draw strong conclusions from.
- Depending on your jurisdiction, trading on prediction markets like
  Polymarket may be restricted or require specific compliance. Check your
  local regulations before running this live.

## Setup

```bash
cd allsports-bot
pip install -r requirements.txt
cp .env.example .env
# edit .env: set WALLET_ADDRESS, STARTING_BANKROLL. Leave PAPER_TRADING=true.
```

## Add your 50 wallets — two ways

### Option A: Automatic discovery (recommended)

```bash
python discover_top50_alltime.py --top 50 --order PNL
```

This pulls the top wallets from Polymarket's official SPORTS leaderboard
using `timePeriod=ALL` (performance since each account's creation, not
weekly/monthly), skips negative-PnL wallets by default, and writes a
ready-to-paste `WATCHED_WALLETS` block to `found_wallets_top50.txt`, which
`config.py` picks up automatically on the next run (falling back to a
smaller built-in wallet list otherwise — see `config.py` for details).

Since the bot tracks all sports combined, no per-sport activity screening
is needed — strong all-time PnL in the SPORTS category is the qualifying
bar directly. (`auto_discover_wallets.py` also exists for a stricter,
single-sport screening workflow — e.g. a UFC-only watchlist filtered on
tennis-style activity/win-rate thresholds — if you want to narrow down to
one sport instead of all of them.)

### Option B: Manual candidates

If you already have addresses in mind (e.g. from PolyCopy, Polymarket
profiles, or your own research), screen them with the same underlying
logic (`wallet_screening.py`: ≥8 buys in the last 10 weeks, ≥50% win rate
on resolved positions):

```bash
python manual_wallet_check.py candidates.txt
```

Neither script ever fabricates an address — they only evaluate real
wallets, either pulled from Polymarket's leaderboard or supplied by you.

All wallets count equally — there are no tiers/weights in this version. The
bot fires the instant `CONSENSUS_WALLET_THRESHOLD` distinct wallets from
this list buy the same outcome of the same market within the 15-minute
window, then places a second same-size trade if `DOUBLE_UP_THRESHOLD` is
also reached in that window (see "Two-tier trading rule" above).

## Going faster than polling

By default the bot polls each wallet's trade history every 5 seconds
(`POLL_INTERVAL_SECONDS`). With 50 wallets that's 50 HTTP calls every 5s —
fine for the public Data API, but if you want true sub-second reaction time,
the next step is swapping `wallet_tracker.py`'s polling loop for a
WebSocket subscription to Polymarket's live trade feed instead. That's a
bigger change (persistent connection, reconnect handling) and wasn't
requested, so it's left as a documented upgrade path rather than built in.

## Running (paper mode — default, safe)

```bash
python main.py
```

This tracks all wallets in `config.py`, applies the full strategy, and logs
every simulated trade to `logs/paper_trades.jsonl`. No funds are ever moved.

Optionally, in a second terminal, run the resolution watcher to track
paper P&L over time:

```bash
python resolution_watcher.py
```

## Growing/vetting your wallet list further

`wallet_screening.py` is the shared screening logic used by both discovery
scripts above (≥8 tennis buys/10 weeks, ≥50% win rate) — adjust its
`MIN_BUYS` / `MIN_WIN_RATE` constants if you want a stricter or looser bar.

## Going live (only after you've reviewed everything above)

1. Set `PAPER_TRADING=false` and `WALLET_PRIVATE_KEY=...` in `.env`
   (dedicated wallet, limited funds).
2. Token-id resolution is now automatic: `market_resolver.py` looks up the
   exact CLOB `token_id` for each signal's outcome via the public Gamma API
   before any order is built, and the bot **skips the trade** if it can't
   confidently resolve it or if the market is no longer active — it never
   guesses.
3. Run `python main.py` and watch `logs/bot.log` closely for the first
   several signals before walking away from the terminal.

## Project structure

| File | Role |
|---|---|
| `config.py` | Wallets, tiers, all strategy parameters |
| `wallet_tracker.py` | Polls Polymarket's public Data API for whale trades |
| `sport_filter.py` | Determines which slugs are active sports markets via the Gamma tag system |
| `consensus_engine.py` | Two-tier consensus: fires a base trade at `CONSENSUS_WALLET_THRESHOLD` agreeing wallets, a double-up at `DOUBLE_UP_THRESHOLD` |
| `wallet_screening.py` | Shared screening logic (real activity + win rate), used by the single-sport discovery workflow |
| `discover_top50_alltime.py` | Primary discovery: top all-time PnL wallets from Polymarket's SPORTS leaderboard |
| `auto_discover_wallets.py` | Alternate discovery: leaderboard candidates screened for a specific sport's activity/win-rate |
| `manual_wallet_check.py` | Screens addresses you supply yourself in a text file |
| `check_wallet_activity.py` | Quick manual lookup of one wallet's recent activity |
| `backtest.py` | Replays the consensus logic over real historical trades to estimate win rate/ROI |
| `sweep_thresholds.py` | Backtests a range of consensus/double-up thresholds to compare |
| `debug_slug_match.py` | Debug helper for tag/slug resolution issues in `sport_filter.py` |
| `risk_manager.py` | Daily cap, cooldowns, max positions, loss-streak pause |
| `trade_executor.py` | Paper simulation or live order submission |
| `market_resolver.py` | Resolves market slug/outcome -> CLOB token_id, checks market is still active |
| `resolution_watcher.py` | Tracks market resolutions, feeds real P&L back to the risk manager |
| `main.py` | Wires everything together |

## State & logs

- `state/risk_state.json` — bankroll, daily spend, cooldowns, loss streak.
  Persisted across restarts. Delete it to reset the bot to a fresh state.
- `logs/bot.log` — full run log.
- `logs/paper_trades.jsonl` — one JSON line per simulated trade.
- `logs/live_trades.jsonl` — one JSON line per live order actually submitted.
