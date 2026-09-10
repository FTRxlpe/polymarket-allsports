"""
Entry point. Wires together:
  WalletTracker -> ConsensusEngine -> RiskManager -> TradeExecutor

Run with:  python main.py
Stop with: Ctrl+C
"""
import logging
import os
from dotenv import load_dotenv

load_dotenv()  # reads .env before config.py evaluates os.getenv() calls

import config
from wallet_tracker import WalletTracker
from consensus_engine import ConsensusEngine
from risk_manager import RiskManager
from trade_executor import TradeExecutor
from market_resolver import MarketResolver

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/bot.log"),
    ],
)
logger = logging.getLogger("main")


def main():
    mode = "PAPER" if config.PAPER_TRADING else "LIVE"
    logger.info(f"=== Polymarket {config.SPORT_TAG_SLUG.upper()} Whale-Consensus Bot starting in {mode} mode ===")

    tracker = WalletTracker()
    consensus = ConsensusEngine()
    risk = RiskManager()
    executor = TradeExecutor()
    resolver = MarketResolver()

    def handle_new_trades(trades):
        signals = consensus.ingest(trades)
        for signal in signals:
            is_addition = (signal.signal_type == "double_up")

            rejection_reason = risk.check(signal, is_addition=is_addition)
            if rejection_reason:
                logger.info(f"[SKIP] {signal.market_slug}/{signal.outcome} ({signal.signal_type}): {rejection_reason}")
                continue

            # Live-mode safety checks: confirm the market is still open and
            # resolve the exact token_id before any real order is built.
            # These also run harmlessly in paper mode for consistent testing.
            if not resolver.is_market_active(signal.market_slug):
                logger.info(f"[SKIP] {signal.market_slug}: market no longer active")
                continue

            token_id = resolver.resolve_token_id(signal.market_slug, signal.outcome)
            if not config.PAPER_TRADING and not token_id:
                logger.warning(
                    f"[SKIP] {signal.market_slug}/{signal.outcome}: could not "
                    f"resolve token_id — refusing to trade blind in live mode."
                )
                continue

            bet_size = risk.compute_bet_size(signal.multiplier)

            logger.info(
                f"[ACTING - {signal.signal_type.upper()}] {signal.market_slug} / "
                f"{signal.outcome} — ${bet_size:.2f} — {signal.wallet_count} "
                f"wallets agreed: {signal.contributing_wallets}"
            )

            executor.execute(signal, bet_size, token_id=token_id)
            risk.record_bet_placed(signal, bet_size, is_addition=is_addition)
            # Note: consensus.clear_market() is intentionally NOT called here.
            # The pending signal state must persist so a later double_up
            # signal on the same market+outcome can still be detected. It
            # naturally expires after TIME_WINDOW_MINUTES via _prune_expired().

    tracker.run_forever(on_trades_callback=handle_new_trades)


if __name__ == "__main__":
    main()
