"""Mock Telegram environment and Supplier Bot simulator for zero-risk testing.

Simulates nested inline keyboard menus, editMessage updates, back/home navigation,
and product detail pages.
"""

from dataclasses import dataclass, field
import hashlib
from typing import Any, Callable, Dict, List, Optional


@dataclass
class MockButton:
    text: str
    data: bytes = b""

    def __post_init__(self) -> None:
        if not self.data:
            self.data = self.text.encode("utf-8")


class MockMessage:
    def __init__(
        self,
        msg_id: int,
        peer_id: str,
        text: str,
        buttons: Optional[List[List[MockButton]]] = None,
        simulator: Optional["MockBotSimulator"] = None,
    ) -> None:
        self.id = msg_id
        self.peer_id = peer_id
        self.text = text
        self.buttons = buttons or []
        self.simulator = simulator

    async def click(self, row: int, col: int) -> Optional["MockMessage"]:
        if not self.simulator:
            return None
        btn = self.buttons[row][col]
        return await self.simulator.handle_callback(self, btn)


class MockBotSimulator:
    """Simulates realistic supplier bot behavior with nested menus and product detail screens."""

    def __init__(self, bot_username: str = "@supplier_mock_bot") -> None:
        self.bot_username = bot_username
        self.msg_counter = 100
        self.current_screen = "root"
        # Map of button text to simulated target screen
        self._tree = self._build_menu_tree()
        self._parent = {
            "root": None,
            "🎬 Dịch vụ Streaming": "root",
            "Netflix Premium": "🎬 Dịch vụ Streaming",
            "Spotify Premium": "🎬 Dịch vụ Streaming",
            "Netflix 1 Tháng (4K)": "Netflix Premium",
            "Netflix 3 Tháng (4K)": "Netflix Premium",
            "☁️ Dịch vụ Cloud / VPS": "root",
            "VPS 2 Core 4GB": "☁️ Dịch vụ Cloud / VPS",
            "VPS 4 Core 8GB": "☁️ Dịch vụ Cloud / VPS",
        }

    def _build_menu_tree(self) -> Dict[str, Dict[str, Any]]:
        return {
            "root": {
                "text": "🤖 Chào mừng đến với Digital Store!\nVui lòng chọn danh mục sản phẩm bên dưới:",
                "buttons": [
                    [MockButton("🎬 Dịch vụ Streaming"), MockButton("☁️ Dịch vụ Cloud / VPS")],
                    [MockButton("❓ Trợ giúp")],
                ],
            },
            "🎬 Dịch vụ Streaming": {
                "text": "📺 Danh mục Streaming chất lượng cao:\nChọn dịch vụ bạn muốn xem bảng giá:",
                "buttons": [
                    [MockButton("Netflix Premium"), MockButton("Spotify Premium")],
                    [MockButton("⬅️ Quay lại")],
                ],
            },
            "Netflix Premium": {
                "text": "🍿 Bảng giá Netflix Premium Ultra HD:\nChọn gói sử dụng:",
                "buttons": [
                    [MockButton("Netflix 1 Tháng (4K)"), MockButton("Netflix 3 Tháng (4K)")],
                    [MockButton("⬅️ Quay lại")],
                ],
            },
            "Netflix 1 Tháng (4K)": {
                "text": (
                    "⭐ THÔNG TIN SẢN PHẨM ⭐\n"
                    "Tên: Netflix Premium Ultra HD\n"
                    "Thời hạn: 1 tháng\n"
                    "Chất lượng: 4K UHD\n"
                    "Tình trạng: Còn hàng\n"
                    "Giá: 65.000đ"
                ),
                "buttons": [[MockButton("💳 Mua ngay")], [MockButton("⬅️ Quay lại")]],
            },
            "Netflix 3 Tháng (4K)": {
                "text": (
                    "⭐ THÔNG TIN SẢN PHẨM ⭐\n"
                    "Tên: Netflix Premium Ultra HD\n"
                    "Thời hạn: 3 tháng\n"
                    "Chất lượng: 4K UHD\n"
                    "Tình trạng: Còn hàng\n"
                    "Giá: 180.000đ"
                ),
                "buttons": [[MockButton("💳 Mua ngay")], [MockButton("⬅️ Quay lại")]],
            },
            "Spotify Premium": {
                "text": (
                    "🎵 Gói Spotify Premium Family Nâng chính chủ:\n"
                    "Thời hạn: 1 năm\n"
                    "Tình trạng: Còn hàng\n"
                    "Giá: 240.000 VNĐ"
                ),
                "buttons": [[MockButton("💳 Mua ngay")], [MockButton("⬅️ Quay lại")]],
            },
            "☁️ Dịch vụ Cloud / VPS": {
                "text": "⚡ Bảng giá VPS Cloud Singapore:\nChọn cấu hình:",
                "buttons": [
                    [MockButton("VPS 2 Core 4GB"), MockButton("VPS 4 Core 8GB")],
                    [MockButton("⬅️ Quay lại")],
                ],
            },
            "VPS 2 Core 4GB": {
                "text": (
                    "💻 VPS Singapore NVMe\n"
                    "CPU: 2 Core\n"
                    "RAM: 4GB RAM\n"
                    "Ổ cứng: 64GB SSD\n"
                    "Thời hạn: 1 tháng\n"
                    "Tình trạng: Còn hàng\n"
                    "Giá: 120.000đ"
                ),
                "buttons": [[MockButton("💳 Đặt hàng")], [MockButton("⬅️ Quay lại")]],
            },
            "VPS 4 Core 8GB": {
                "text": (
                    "💻 VPS Singapore NVMe\n"
                    "CPU: 4 Core\n"
                    "RAM: 8GB RAM\n"
                    "Ổ cứng: 128GB SSD\n"
                    "Thời hạn: 1 tháng\n"
                    "Tình trạng: Tạm hết hàng\n"
                    "Giá: 230.000đ"
                ),
                "buttons": [[MockButton("💳 Đặt hàng")], [MockButton("⬅️ Quay lại")]],
            },
        }

    async def get_initial_message(self) -> MockMessage:
        self.msg_counter += 1
        screen = self._tree["root"]
        return MockMessage(
            msg_id=self.msg_counter,
            peer_id=self.bot_username,
            text=screen["text"],
            buttons=screen["buttons"],
            simulator=self,
        )

    async def handle_callback(self, current_msg: MockMessage, button: MockButton) -> MockMessage:
        btn_text = button.text.strip()
        # Handle Back button: returns parent screen
        if "quay lại" in btn_text.lower():
            target = self._parent.get(self.current_screen) or "root"
        else:
            target = btn_text

        self.current_screen = target
        screen = self._tree.get(target, self._tree["root"])
        # Simulate editMessageText: update message in-place
        current_msg.text = screen["text"]
        current_msg.buttons = screen["buttons"]
        return current_msg


class MockTelegramClient:
    """Mock Telethon client for local testing."""

    def __init__(self, simulator: MockBotSimulator) -> None:
        self.simulator = simulator
        self.sent_commands: List[Tuple[str, str]] = []

    async def send_message(self, peer: str, message: str) -> None:
        self.sent_commands.append((peer, message))

    async def get_messages(self, peer: str, limit: int = 1) -> List[MockMessage]:
        msg = await self.simulator.get_initial_message()
        return [msg]
