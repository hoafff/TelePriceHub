"""Personal Telegram Query & Alert Bot.

Provides command handling (/search, /compare, /top) and price drop alerts.
Built with stdlib urllib for zero-dependency Telegram Bot API polling.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional
import urllib.parse
import urllib.request

from teleprice.comparator import PriceComparator
from teleprice.config import config
from teleprice.db import Database

logger = logging.getLogger(__name__)


class QueryBot:
    def __init__(
        self,
        bot_token: Optional[str] = None,
        db: Optional[Database] = None,
        allowed_users: Optional[List[int]] = None,
    ) -> None:
        self.token = bot_token or config.bot_token
        self.db = db or Database(config.db_path)
        self.allowed_users = allowed_users or config.allowed_user_ids
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.last_update_id = 0

    def _call_api(self, method: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.api_url}/{method}"
        req_data = json.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(
            url, data=req_data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_message(
        self, chat_id: int, text: str, parse_mode: str = "Markdown", disable_preview: bool = True
    ) -> None:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_preview,
        }
        try:
            self._call_api("sendMessage", payload)
        except Exception as e:
            logger.warning("Failed to send message to %s: %s", chat_id, e)

    def handle_update(self, update: Dict[str, Any]) -> None:
        msg = update.get("message") or update.get("edited_message")
        if not msg or "text" not in msg:
            return

        chat_id = msg["chat"]["id"]
        from_id = msg.get("from", {}).get("id")

        # Security check: whitelist user ID
        if self.allowed_users and from_id not in self.allowed_users:
            self.send_message(chat_id, "⛔ Bạn không có quyền truy cập bot tra cứu này.")
            return

        text = msg["text"].strip()

        if text.startswith("/start") or text.startswith("/help"):
            welcome = (
                "👋 **TelePriceHub - Bot Tra Cứu Giá Nhà Cung Cấp**\n\n"
                "Các lệnh hỗ trợ:\n"
                "• `/search <tên>` : Tra cứu giá tốt nhất cho sản phẩm\n"
                "• `/compare <tên>`: Xem bảng so sánh giá chi tiết giữa các bên\n"
                "• `/top` : Top 5 gói giá rẻ nhất hiện tại\n"
                "• `/status` : Thống kê số lượng sản phẩm & nhà cung cấp"
            )
            self.send_message(chat_id, welcome)

        elif text.startswith("/search"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                self.send_message(chat_id, "⚠️ Cú pháp: `/search <tên sản phẩm>` (Ví dụ: `/search netflix`)")
                return
            kw = parts[1].strip()
            self._handle_search(chat_id, kw)

        elif text.startswith("/compare"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                self.send_message(chat_id, "⚠️ Cú pháp: `/compare <tên sản phẩm>` (Ví dụ: `/compare spotify`)")
                return
            kw = parts[1].strip()
            self._handle_compare(chat_id, kw)

        elif text.startswith("/status"):
            self._handle_status(chat_id)

    def _handle_search(self, chat_id: int, keyword: str) -> None:
        offers = self.db.get_comparison(keyword=keyword)
        if not offers:
            self.send_message(chat_id, f"🔍 Không tìm thấy sản phẩm nào khớp với: `{keyword}`")
            return

        comparisons = PriceComparator.compare(offers)
        lines = [f"🎯 **Kết quả tra cứu cho:** `{keyword}`\n"]
        for comp in comparisons[:5]:
            best = comp.rankings[0]
            supp_link = f"[{best.supplier_name}](https://t.me/{best.supplier_username.lstrip('@')})"
            lines.append(
                f"🏷 **{comp.canonical_name}** (`{comp.spec_key}`)\n"
                f"• Giá rẻ nhất: **{comp.min_price:,.0f} {comp.currency}**\n"
                f"• Nhà cung cấp: {supp_link} ({'✅ Sẵn' if best.in_stock else '❌ Hết'})\n"
                f"• Dùng `/compare {comp.canonical_name}` để xem bảng chi tiết\n"
            )

        self.send_message(chat_id, "\n".join(lines))

    def _handle_compare(self, chat_id: int, keyword: str) -> None:
        offers = self.db.get_comparison(keyword=keyword)
        if not offers:
            self.send_message(chat_id, f"🔍 Không tìm thấy dữ liệu để so sánh: `{keyword}`")
            return

        comparisons = PriceComparator.compare(offers)
        for comp in comparisons[:3]:
            table_md = PriceComparator.format_markdown_table(comp)
            self.send_message(chat_id, table_md)

    def _handle_status(self, chat_id: int) -> None:
        products = self.db.get_all_canonical_products()
        with self.db.get_conn() as conn:
            supp_count = conn.execute("SELECT count(*) as cnt FROM suppliers").fetchone()["cnt"]
            offer_count = conn.execute("SELECT count(*) as cnt FROM offers").fetchone()["cnt"]

        text = (
            "📈 **Hệ thống TelePriceHub**\n"
            f"• Nhà cung cấp theo dõi: {supp_count}\n"
            f"• Sản phẩm chuẩn hóa: {len(products)}\n"
            f"• Báo giá đang lưu: {offer_count}\n"
        )
        self.send_message(chat_id, text)

    def poll_forever(self, poll_interval: float = 2.0) -> None:
        # ponytail: long polling loop; switch to webhook if deployed on serverless/public domain
        logger.info("Starting Telegram Query Bot polling...")
        while True:
            try:
                res = self._call_api("getUpdates", {"offset": self.last_update_id + 1, "timeout": 20})
                updates = res.get("result", [])
                for upd in updates:
                    self.last_update_id = max(self.last_update_id, upd["update_id"])
                    self.handle_update(upd)
            except Exception as e:
                logger.error("Polling error: %s", e)
                time.sleep(poll_interval)
