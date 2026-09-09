# Polymarket Tennis Whale-Consensus Bot

Tracks 50 watched wallets. The moment **5 of them buy the same outcome of
the same tennis match** within a 15-minute window, the bot fires a trade
instantly (next poll cycle, every 5s by default) for the same position.

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
cd polymarket-tennis
pip install -r requirements.txt
cp .env.example .env
# edit .env: set WALLET_ADDRESS, STARTING_BANKROLL. Leave PAPER_TRADING=true.
```

## Add your 50 wallets — two ways

### Option A: Automatic discovery (recommended)

```bash
python auto_discover_wallets.py --top 50 --output found_wallets.txt
```

This pulls Polymarket's own official leaderboard
(`data-api.polymarket.com/v1/leaderboard`, `category=SPORTS`, PnL and
volume, across weekly/monthly windows — no scraping, no API key), then
screens every candidate's *actual* trade history for genuine tennis
activity and win rate. Polymarket doesn't expose a tennis-only leaderboard,
so this two-step approach (broad sports leaderboard → tennis-specific
screening) is how it narrows down to real tennis specialists rather than
just general sports bettors. Paste the output into `WATCHED_WALLETS` in
`config.py`.

### Option B: Manual candidates

If you already have addresses in mind (e.g. from PolyCopy, Polymarket
profiles, or your own research), screen them the same way:

```bash
python manual_wallet_check.py candidates.txt
```

Both options use the same underlying screening (`wallet_screening.py`):
≥8 tennis buys in the last 10 weeks, ≥50% win rate on resolved positions.
Neither one ever fabricates an address — they only evaluate real wallets,
either pulled from Polymarket's leaderboard or supplied by you.

All wallets count equally — there are no tiers/weights in this version. The
bot fires the instant 5 distinct wallets from this list buy the same
outcome of the same tennis match within the 15-minute window
(`config.TIME_WINDOW_MINUTES`, `config.CONSENSUS_WALLET_THRESHOLD`).

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
| `sport_filter.py` | Determines which slugs are active tennis markets via the Gamma tag system |
| `consensus_engine.py` | Fires instantly once 5 distinct wallets agree on the same outcome |
| `wallet_screening.py` | Shared screening logic (real tennis activity + win rate) |
| `auto_discover_wallets.py` | Finds candidates from Polymarket's own leaderboard, screens them automatically |
| `manual_wallet_check.py` | Screens addresses you supply yourself in a text file |
| `risk_manager.py` | Daily cap, cooldowns, max positions, loss-streak pause |
| `trade_executor.py` | Paper simulation or live order submission |
| `market_resolver.py` | Resolves market slug/outcome -> CLOB token_id, checks market is still active |
| `resolution_watcher.py` | Tracks market resolutions, feeds P&L back |
| `main.py` | Wires everything together |

## State & logs

- `state/risk_state.json` — bankroll, daily spend, cooldowns, loss streak.
  Persisted across restarts. Delete it to reset the bot to a fresh state.
- `logs/bot.log` — full run log.
- `logs/paper_trades.jsonl` — one JSON line per simulated trade.
