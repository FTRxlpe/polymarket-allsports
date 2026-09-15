"""
Executes trades. In paper mode (default), nothing ever touches the real
Polymarket order book — trades are simulated and logged to
logs/paper_trades.jsonl for later review.

In live mode, this uses py-clob-client (Polymarket's official SDK) to submit
a real limit order signed with your wallet's private key. Live mode is only
active if PAPER_TRADING=false in your .env AND WALLET_PRIVATE_KEY is set.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

import config
from consensus_engine import ConsensusSignal

logger = logging.getLogger("trade_executor")

PAPER_LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "paper_trades.jsonl")
LIVE_LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "live_trades.jsonl")


class TradeExecutor:
    def __init__(self):
        self.paper_mode = config.PAPER_TRADING
        self._clob_client = None

        if not self.paper_mode:
            if not config.WALLET_PRIVATE_KEY:
                raise RuntimeError(
                    "PAPER_TRADING=false but WALLET_PRIVATE_KEY is not set in .env. "
                    "Refusing to start in live mode without credentials."
                )
            self._init_live_client()
            logger.warning(
                "!!! LIVE TRADING MODE ACTIVE — real orders will be submitted "
                "with real funds. !!!"
            )
        else:
            logger.info("Running in PAPER TRADING mode — no real orders will be sent.")

        os.makedirs(os.path.dirname(PAPER_LOG_PATH), exist_ok=True)

    def _init_live_client(self):
        # Imported lazily so paper-mode users don't need the dependency installed
        # until they actually flip to live trading.
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds

        self._clob_client = ClobClient(
            host=config.POLYMARKET_CLOB_API,
            chain_id=config.POLYGON_CHAIN_ID,
            key=config.WALLET_PRIVATE_KEY,
        )
        # Derive/attach API credentials (required for order posting).
        creds = self._clob_client.create_or_derive_api_creds()
        self._clob_client.set_api_creds(creds)

    def execute(self, signal: ConsensusSignal, bet_size_usd: float, token_id: str = None):
        if self.paper_mode:
            self._execute_paper(signal, bet_size_usd, token_id)
        else:
            self._execute_live(signal, bet_size_usd, token_id)

    def _execute_paper(self, signal: ConsensusSignal, bet_size_usd: float, token_id: str = None):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_slug": signal.market_slug,
            "outcome": signal.outcome,
            "token_id": token_id,
            "price": signal.avg_price,
            "bet_size_usd": bet_size_usd,
            "wallet_count": signal.wallet_count,
            "contributing_wallets": signal.contributing_wallets,
            "mode": "paper",
        }
        with open(PAPER_LOG_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")
        logger.info(f"[PAPER TRADE] {record}")

    def _execute_live(self, signal: ConsensusSignal, bet_size_usd: float, token_id: str):
        """
        Submits a real limit BUY order via py-clob-client.

        `token_id` is the ERC-1155 token id for the specific outcome you're
        buying — you must resolve this from the market's slug/outcome using
        the Polymarket Gamma API (get-markets) before calling this. See
        README.md "Resolving token IDs" for details; this is left as an
        explicit step so you always confirm you're buying the right outcome
        before real money moves.
        """
        if not token_id:
            raise ValueError(
                "token_id is required for live execution — resolve it from "
                "the Gamma API first. Refusing to guess which outcome to buy."
            )

        from py_clob_client.clob_types import OrderArgs
        from py_clob_client.order_builder.constants import BUY

        shares = bet_size_usd / signal.avg_price

        order_args = OrderArgs(
            price=signal.avg_price,
            size=round(shares, 2),
            side=BUY,
            token_id=token_id,
        )
        signed_order = self._clob_client.create_order(order_args)
        resp = self._clob_client.post_order(signed_order)
        logger.info(f"[LIVE ORDER SUBMITTED] {signal.market_slug} -> {resp}")

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_slug": signal.market_slug,
            "outcome": signal.outcome,
            "token_id": token_id,
            "price": signal.avg_price,
            "bet_size_usd": bet_size_usd,
            "wallet_count": signal.wallet_count,
            "contributing_wallets": signal.contributing_wallets,
            "order_response": resp,
            "mode": "live",
        }
        with open(LIVE_LOG_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")

        return resp
