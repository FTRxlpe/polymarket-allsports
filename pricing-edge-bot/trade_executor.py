"""
Executes trades. In paper mode (default), nothing ever touches the real
Polymarket order book — trades are simulated and logged to
logs/paper_trades.jsonl.

In live mode, this uses py-clob-client (Polymarket's official SDK) to submit
a real limit order signed with your wallet's private key. Live mode only
activates if PAPER_TRADING=false AND WALLET_PRIVATE_KEY is set — refusing to
start live without both is intentional, not a default anyone should rely on.
"""
import json
import logging
import os
from datetime import datetime, timezone

import config

logger = logging.getLogger("trade_executor")

PAPER_LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "paper_trades.jsonl")


class TradeExecutor:
    def __init__(self):
        self.paper_mode = config.PAPER_TRADING
        self._clob_client = None

        if not self.paper_mode:
            if not config.WALLET_PRIVATE_KEY:
                raise RuntimeError(
                    "PAPER_TRADING=false but WALLET_PRIVATE_KEY is not set. "
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
        from py_clob_client.client import ClobClient

        self._clob_client = ClobClient(
            host=config.CLOB_API,
            chain_id=config.POLYGON_CHAIN_ID,
            key=config.WALLET_PRIVATE_KEY,
        )
        creds = self._clob_client.create_or_derive_api_creds()
        self._clob_client.set_api_creds(creds)

    def execute(self, market_slug: str, token_id: str, price: float, stake_usd: float):
        if self.paper_mode:
            return self._execute_paper(market_slug, token_id, price, stake_usd)
        return self._execute_live(market_slug, token_id, price, stake_usd)

    def _execute_paper(self, market_slug, token_id, price, stake_usd):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_slug": market_slug,
            "token_id": token_id,
            "price": price,
            "stake_usd": stake_usd,
            "mode": "paper",
        }
        with open(PAPER_LOG_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")
        logger.info(f"[PAPER TRADE] {record}")
        return record

    def _execute_live(self, market_slug, token_id, price, stake_usd):
        if not token_id:
            raise ValueError(
                "token_id is required for live execution — resolve it from "
                "the Gamma API first. Refusing to guess which outcome to buy."
            )

        from py_clob_client.clob_types import OrderArgs
        from py_clob_client.order_builder.constants import BUY

        shares = stake_usd / price
        order_args = OrderArgs(price=price, size=round(shares, 2), side=BUY, token_id=token_id)
        signed_order = self._clob_client.create_order(order_args)
        resp = self._clob_client.post_order(signed_order)
        logger.info(f"[LIVE ORDER SUBMITTED] {market_slug} -> {resp}")
        return resp
