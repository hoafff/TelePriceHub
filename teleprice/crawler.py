"""Telegram MTProto crawler for supplier bots.

Automates multi-level inline menu traversal, cycle detection,
editMessage tracking, FloodWait throttling, and checkpoint persistence.
"""

import asyncio
import hashlib
import logging
import random
import re
from typing import Any, Callable, Dict, List, Optional, Set

try:
    from telethon import TelegramClient, events
    from telethon.errors import FloodWaitError
    from telethon.tl.custom.message import Message
except ImportError:
    # Allows module to be loaded/tested in environments without telethon installed
    TelegramClient = Any  # type: ignore
    FloodWaitError = Exception  # type: ignore
    Message = Any  # type: ignore

from teleprice.config import config
from teleprice.db import Database
from teleprice.matcher import ProductMatcher
from teleprice.parser import MessageParser

logger = logging.getLogger(__name__)


class TelegramCrawler:
    # Pattern to identify navigation / backtrack buttons
    RE_BACK_BUTTON = re.compile(
        r"(quay lại|trở về|back|trang chủ|menu chính|home|⬅️|🔙)", re.IGNORECASE
    )
    RE_PAGINATION_BUTTON = re.compile(
        r"(trang sau|next|tiếp|tiếp theo|>>|➡️|\[\d+/\d+\])", re.IGNORECASE
    )
    RE_IGNORE_BUTTON = re.compile(
        r"(mua ngay|đặt hàng|thanh toán|buy|order|checkout|hỗ trợ|support|trợ giúp|liên hệ)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        client: Optional[TelegramClient] = None,
        db: Optional[Database] = None,
        matcher: Optional[ProductMatcher] = None,
    ) -> None:
        self.client = client
        self.db = db or Database(config.db_path)
        self.matcher = matcher or ProductMatcher(config.gemini_api_key)
        self.visited_hashes: Set[str] = set()
        self.enable_throttle: bool = True

    async def crawl_supplier(self, bot_username: str, max_depth: int = 5) -> int:
        """Crawls a single supplier bot starting with /start command."""
        logger.info("Starting crawl for supplier: %s", bot_username)
        supplier_id = self.db.upsert_supplier(username=bot_username)
        self.visited_hashes.clear()

        # Send /start
        await self._send_command(bot_username, "/start")
        await self._throttle()

        # Get the latest message from the bot
        latest_msg = await self._get_latest_message(bot_username)
        if not latest_msg:
            logger.warning("No response received from %s", bot_username)
            return 0

        # Begin recursive/stack-based menu traversal
        products_collected = await self._traverse_menu(
            bot_username=bot_username,
            supplier_id=supplier_id,
            current_message=latest_msg,
            depth=0,
            max_depth=max_depth,
        )

        logger.info("Crawl finished for %s. Found %d products.", bot_username, products_collected)
        return products_collected

    async def _traverse_menu(
        self,
        bot_username: str,
        supplier_id: int,
        current_message: Any,
        depth: int,
        max_depth: int,
    ) -> int:
        """Traverses inline keyboard buttons using DFS with cycle prevention."""
        if depth > max_depth or not current_message:
            return 0

        text = getattr(current_message, "text", "") or ""
        buttons = getattr(current_message, "buttons", None) or []

        # Check if current message is already a product detail page
        parsed = MessageParser.parse(text)
        products_saved = 0
        if parsed.is_product and parsed.price:
            catalog = self.db.get_all_canonical_products()
            canonical_name, brand, model = self.matcher.match(
                raw_name=parsed.name,
                specs=parsed.specs,
                spec_key=parsed.spec_key,
                existing_products=catalog,
            )
            prod_id = self.db.upsert_product(
                raw_name=parsed.name,
                canonical_name=canonical_name,
                brand=brand,
                model=model,
                spec_key=parsed.spec_key,
                specs=parsed.specs,
            )
            self.db.save_offer(
                supplier_id=supplier_id,
                product_id=prod_id,
                price=parsed.price,
                currency=parsed.currency,
                in_stock=parsed.in_stock,
                duration=parsed.duration,
                raw_message=text,
            )
            products_saved += 1
            logger.info("Saved product [%s - %s]: %s", canonical_name, parsed.spec_key, parsed.price)
            # Product details page is a leaf node; stop recursing further into checkout actions
            return products_saved

        if not buttons:
            return products_saved

        # Flatten button rows
        for row_idx, row in enumerate(buttons):
            for col_idx, btn in enumerate(row):
                btn_text = getattr(btn, "text", "").strip()
                btn_data = getattr(btn, "data", b"")

                # Skip back/home buttons and order/help buttons
                if self.RE_BACK_BUTTON.search(btn_text) or self.RE_IGNORE_BUTTON.search(btn_text):
                    continue

                # Compute unique node hash
                node_hash = self._compute_node_hash(btn_text, btn_data, text)
                if node_hash in self.visited_hashes or self.db.is_node_visited(
                    supplier_id, node_hash
                ):
                    continue

                self.visited_hashes.add(node_hash)
                self.db.mark_node_visited(supplier_id, node_hash, depth)

                # Click button and wait for response/editMessage
                response_msg = await self._click_button_safe(current_message, row_idx, col_idx)
                await self._throttle()

                if response_msg:
                    # If this was pagination, don't increase depth
                    is_pagination = bool(self.RE_PAGINATION_BUTTON.search(btn_text))
                    next_depth = depth if is_pagination else depth + 1

                    sub_count = await self._traverse_menu(
                        bot_username=bot_username,
                        supplier_id=supplier_id,
                        current_message=response_msg,
                        depth=next_depth,
                        max_depth=max_depth,
                    )
                    products_saved += sub_count

                    # If bot edited message in place, attempt to backtrack
                    if getattr(response_msg, "id", None) == getattr(current_message, "id", None):
                        await self._backtrack(response_msg)

        return products_saved

    async def _click_button_safe(
        self, message: Any, row_idx: int, col_idx: int
    ) -> Optional[Any]:
        # ponytail: direct click with timeout; handles both editMessage and new message responses
        try:
            if hasattr(message, "click"):
                # Telethon Message.click or MockMessage.click
                res = await message.click(row_idx, col_idx)
                if res is not None and (hasattr(res, "text") or hasattr(res, "buttons")):
                    return res
            # Otherwise fetch latest message in peer
            peer = getattr(message, "peer_id", None)
            if peer and self.client:
                msgs = await self.client.get_messages(peer, limit=1)
                return msgs[0] if msgs else None
        except FloodWaitError as e:
            logger.warning("Telegram FloodWait hit: waiting %s seconds", e.seconds)
            await asyncio.sleep(e.seconds + 2)
        except Exception as e:
            logger.warning("Error clicking button (%d, %d): %s", row_idx, col_idx, e)
        return None

    async def _backtrack(self, message: Any) -> None:
        """Finds and clicks a Back/Home button if available."""
        buttons = getattr(message, "buttons", None) or []
        for r_idx, row in enumerate(buttons):
            for c_idx, btn in enumerate(row):
                btn_text = getattr(btn, "text", "")
                if self.RE_BACK_BUTTON.search(btn_text):
                    try:
                        await message.click(r_idx, c_idx)
                        await self._throttle()
                        return
                    except Exception:
                        pass

    @staticmethod
    def _compute_node_hash(btn_text: str, btn_data: bytes, context_text: str) -> str:
        s = f"{btn_text}|{btn_data.hex()}|{context_text[:60]}"
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    async def _throttle(self) -> None:
        if not self.enable_throttle:
            return
        delay = random.uniform(config.crawl_delay_min, config.crawl_delay_max)
        await asyncio.sleep(delay)

    async def _send_command(self, bot_username: str, command: str) -> None:
        if self.client:
            await self.client.send_message(bot_username, command)

    async def _get_latest_message(self, bot_username: str) -> Optional[Any]:
        if self.client:
            msgs = await self.client.get_messages(bot_username, limit=1)
            return msgs[0] if msgs else None
        return None
