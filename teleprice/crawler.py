"""Safe Telegram menu crawler. Each scheduled run visits menus afresh.

No persisted 'visited' marks: otherwise later cron executions cannot refresh prices.
Navigation is replayed from /start with button labels/positions, not callback_data.
"""
import asyncio
import hashlib
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Any

try:
    from telethon.errors import FloodWaitError
except ImportError:
    class FloodWaitError(Exception):
        seconds = 60

from teleprice.config import config
from teleprice.db import Database
from teleprice.matcher import ProductMatcher
from teleprice.parser import MessageParser

log = logging.getLogger(__name__)

# Match the whole label: "Cloud Backup" and "Cashback" must stay navigable.
BACK = re.compile(r"^\s*(?:[⬅↩🔙◀️ ]*)?(?:quay lại|trở về|trở lại|back|prev|previous|trang trước|menu chính|main menu|home|trang chủ)\s*[⬅↩🔙◀️ ]*$", re.I)
DANGEROUS = re.compile(r"(mua|đặt hàng|thanh toán|thanh toán ngay|checkout|buy|order|pay|payment|nạp tiền|deposit|confirm|xác nhận|gia hạn|renew|đổi mật khẩu|trợ giúp|support|liên hệ|contact|captcha|verify)", re.I)
CAPTCHA = re.compile(r"(captcha|verify you are human|xác minh bạn là người)", re.I)


@dataclass(frozen=True)
class Step:
    label: str
    row: int
    col: int


def screen_sig(msg: Any) -> str:
    buttons = [[getattr(b, "text", "") for b in row] for row in (getattr(msg, "buttons", None) or [])]
    return hashlib.sha256((str(getattr(msg, "text", "") or "") + repr(buttons)).encode()).hexdigest()


class TelegramCrawler:
    def __init__(self, client: Any = None, db: Database | None = None, matcher: ProductMatcher | None = None):
        self.client = client
        self.db = db or Database(config.db_path)
        self.matcher = matcher or ProductMatcher(config.gemini_api_key)
        self.enable_throttle = True
        self.max_nodes = 350
        self.max_clicks = 1800
        self.max_seconds = 1500
        self.response_timeout = 12
        self.clicks = 0
        self.errors: list[str] = []

    async def _sleep(self):
        if self.enable_throttle:
            await asyncio.sleep(random.uniform(config.crawl_delay_min, config.crawl_delay_max))

    async def _call(self, fn):
        for attempt in range(3):
            try:
                return await fn()
            except FloodWaitError as exc:
                delay = int(exc.seconds)
                if delay > 120:
                    raise
                log.warning("FloodWait %ss", delay)
                await asyncio.sleep(delay + 2)
        raise RuntimeError("Telegram rate limit")

    async def _latest_bot_message(self, peer):
        messages = await self.client.get_messages(peer, limit=5)
        return next((m for m in messages if not getattr(m, "out", False)), None)

    async def _wait_response(self, peer, old_msg, before, direct=None):
        if direct is not None and (hasattr(direct, "text") or hasattr(direct, "buttons")):
            return direct
        old_id = getattr(old_msg, "id", 0) if old_msg else 0
        deadline = time.monotonic() + self.response_timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            latest = await self._latest_bot_message(peer)
            if latest is not None and getattr(latest, "id", 0) > old_id:
                return latest
            if old_msg is not None and old_id:
                try:
                    edited = await self.client.get_messages(peer, ids=old_id)
                    if edited and screen_sig(edited) != before:
                        return edited
                except TypeError:  # simple mock clients may not support ids
                    pass
            if latest and screen_sig(latest) != before:
                return latest
        raise TimeoutError("Bot did not send or edit a message")

    async def _open(self, peer):
        before_msg = await self._latest_bot_message(peer)
        before = screen_sig(before_msg) if before_msg else ""
        await self._sleep()
        await self._call(lambda: self.client.send_message(peer, "/start"))
        return await self._wait_response(peer, before_msg, before)

    @staticmethod
    def _safe_button(button):
        name = getattr(button, "text", "").strip()
        if not name or BACK.search(name) or DANGEROUS.search(name):
            return False
        raw = getattr(button, "button", None)
        if raw is not None:
            kind = type(raw).__name__
            if kind not in ("KeyboardButtonCallback", "KeyboardButton"):
                return False  # never open URLs, pay buttons, web apps, or login links
        return True

    async def _click(self, peer, msg, step):
        btns = getattr(msg, "buttons", None) or []
        button = None
        if step.row < len(btns) and step.col < len(btns[step.row]):
            candidate = btns[step.row][step.col]
            if getattr(candidate, "text", "") == step.label:
                button = (step.row, step.col)
        if button is None:
            for r, row in enumerate(btns):
                for c, b in enumerate(row):
                    if getattr(b, "text", "") == step.label:
                        button = (r, c)
                        break
                if button is not None:
                    break
        if button is None:
            raise ValueError("Menu changed; missing button: " + step.label)
        if not self._safe_button(btns[button[0]][button[1]]):
            raise ValueError("Unsafe navigation button: " + step.label)
        before = screen_sig(msg)
        await self._sleep()
        self.clicks += 1
        try:
            # Telethon callback answers are not Message objects; wait for edit/new msg.
            direct = await asyncio.wait_for(
                self._call(lambda: msg.click(button[0], button[1])),
                timeout=self.response_timeout,
            )
        except asyncio.TimeoutError:
            direct = None   # callback can time out after bot already edited the message
        return await self._wait_response(peer, msg, before, direct=direct)

    async def _replay(self, peer, path):
        msg = await self._open(peer)
        ancestry = {screen_sig(msg)}
        for step in path:
            msg = await self._click(peer, msg, step)
            if CAPTCHA.search(getattr(msg, "text", "") or ""):
                raise RuntimeError("CAPTCHA; manual intervention required")
            signature = screen_sig(msg)
            if signature in ancestry:
                raise ValueError("Cyclic navigation")
            ancestry.add(signature)
        return msg, ancestry

    async def crawl_supplier(self, bot_username: str, max_depth: int = 5) -> int:
        if not self.client:
            raise RuntimeError("Telegram client required")
        supplier_id = self.db.upsert_supplier(bot_username)
        self.clicks = 0
        self.errors = []
        start = time.monotonic()
        # Full catalog rescan every run. The old DB crawl_state is intentionally unused.
        pending: list[tuple[Step, ...]] = [()]
        finished: set[tuple[Step, ...]] = set()
        found = 0
        nodes = 0
        try:
            while pending and nodes < self.max_nodes and self.clicks < self.max_clicks:
                if time.monotonic() - start > self.max_seconds:
                    log.warning("Crawl deadline reached: %s", bot_username)
                    break
                path = pending.pop()
                if path in finished or len(path) > max_depth:
                    continue
                msg = None
                for attempt in range(2):
                    try:
                        msg, ancestry = await self._replay(bot_username, path)
                        break
                    except (TimeoutError, ValueError) as exc:
                        self.errors.append(str(exc))
                        log.warning("Retry path %s (%s): %s", path, attempt + 1, exc)
                if msg is None:
                    continue
                finished.add(path)
                nodes += 1
                text = getattr(msg, "text", "") or ""
                parsed = MessageParser.parse(text, fallback_title=path[-1].label if path else "")
                if parsed.is_product and parsed.price is not None and parsed.price > 0:
                    catalog = self.db.get_all_canonical_products()
                    name, brand, model = self.matcher.match(parsed.name, parsed.specs, parsed.spec_key, catalog)
                    pid = self.db.upsert_product(parsed.name, name, brand, model, parsed.spec_key, parsed.specs)
                    self.db.save_offer(supplier_id, pid, parsed.price, parsed.currency, parsed.in_stock, parsed.duration, text)
                    found += 1
                    continue  # never press purchase buttons under product
                if len(path) >= max_depth:
                    continue
                children = []
                for r, row in enumerate(getattr(msg, "buttons", None) or []):
                    for c, button in enumerate(row):
                        if self._safe_button(button):
                            child = path + (Step(getattr(button, "text", ""), r, c),)
                            if child not in finished:
                                children.append(child)
                pending.extend(reversed(children))
        finally:
            log.info("Crawl %s: %s products, %s nodes, %s clicks, %s errors, pending=%s",
                     bot_username, found, nodes, self.clicks, len(self.errors), len(pending))
        return found
