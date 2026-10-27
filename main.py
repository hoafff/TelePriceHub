"""CLI Entrypoint for TelePriceHub.

Commands:
    python main.py crawl [--mock]
    python main.py report [--search <kw>]
    python main.py bot
    python main.py test
"""

import argparse
import asyncio
import logging
import sys

from teleprice.comparator import PriceComparator
from teleprice.config import config
from teleprice.crawler import TelegramCrawler
from teleprice.db import Database
from teleprice.matcher import ProductMatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("teleprice.main")


def cmd_report(args: argparse.Namespace) -> None:
    db = Database(config.db_path)
    offers = db.get_comparison(keyword=args.search)
    if not offers:
        print("Không có dữ liệu báo giá nào phù hợp.")
        return

    comparisons = PriceComparator.compare(offers)
    for comp in comparisons:
        print("\n" + PriceComparator.format_markdown_table(comp))


def cmd_crawl(args: argparse.Namespace) -> None:
    db = Database(config.db_path)
    matcher = ProductMatcher(config.gemini_api_key)

    if args.mock:
        from teleprice.mock import MockBotSimulator, MockTelegramClient

        sim = MockBotSimulator("@mock_supplier_bot")
        client = MockTelegramClient(sim)
        crawler = TelegramCrawler(client=client, db=db, matcher=matcher)
        crawler.enable_throttle = False  # fast execution in mock mode
        print("Đang chạy crawler ở chế độ MOCK BOT...")
        total = asyncio.run(crawler.crawl_supplier("@mock_supplier_bot", max_depth=config.max_depth))
        print(f"Hoàn thành crawl mock bot. Thu thập được: {total} sản phẩm.")
        return

    # Live crawl via Telethon
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    if not config.telegram_api_id or not config.telegram_api_hash:
        print("Lỗi: Thiếu TELEGRAM_API_ID hoặc TELEGRAM_API_HASH trong file .env")
        sys.exit(1)

    if not config.supplier_bots:
        print("Lỗi: Chưa cấu hình SUPPLIER_BOTS trong file .env")
        sys.exit(1)

    session = StringSession(config.telegram_string_session) if config.telegram_string_session else config.telegram_session_name
    client = TelegramClient(session, config.telegram_api_id, config.telegram_api_hash)

    async def _run() -> None:
        await client.start()
        crawler = TelegramCrawler(client=client, db=db, matcher=matcher)
        for bot in config.supplier_bots:
            try:
                print(f"--> Bắt đầu crawl bot: {bot}")
                count = await crawler.crawl_supplier(bot, max_depth=config.max_depth)
                print(f"--> Đã lưu {count} sản phẩm từ {bot}")
            except Exception as e:
                logger.error("Lỗi khi crawl bot %s: %s", bot, e)

    with client:
        client.loop.run_until_complete(_run())


def cmd_sync(args: argparse.Namespace) -> None:
    from teleprice.cloud_sync import publish
    count = publish(Database(config.db_path))
    print(f"Đã đồng bộ {count} báo giá lên Cloudflare D1.")

def cmd_bot(args: argparse.Namespace) -> None:
    from teleprice.bot import QueryBot

    if not config.bot_token:
        print("Lỗi: Thiếu BOT_TOKEN trong file .env")
        sys.exit(1)

    bot = QueryBot(bot_token=config.bot_token)
    print("Bot tra cứu đang chạy qua long-polling... Nhấn Ctrl+C để dừng.")
    bot.poll_forever()


def cmd_test(args: argparse.Namespace) -> None:
    import unittest
    loader = unittest.TestLoader()
    suite = loader.discover("tests")
    runner = unittest.TextTestRunner(verbosity=2)
    res = runner.run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="TelePriceHub - Telegram Price Aggregator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # crawl
    crawl_p = subparsers.add_parser("crawl", help="Chạy crawler quét giá từ bot Telegram")
    crawl_p.add_argument("--mock", action="store_true", help="Chạy crawler giả lập với MockBot (không cần Telegram)")

    # report
    report_p = subparsers.add_parser("report", help="Xem bảng so sánh giá trong terminal")
    report_p.add_argument("--search", type=str, default="", help="Từ khóa tìm kiếm sản phẩm")

    # cloud synchronization
    subparsers.add_parser("sync", help="Đẩy báo giá lên Cloudflare Worker + D1")

    # bot
    subparsers.add_parser("bot", help="Chạy Telegram Bot tra cứu giá cho người dùng")

    # test
    subparsers.add_parser("test", help="Chạy toàn bộ unit & integration tests")

    args = parser.parse_args()

    if args.command == "crawl":
        cmd_crawl(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "bot":
        cmd_bot(args)
    elif args.command == "test":
        cmd_test(args)


if __name__ == "__main__":
    main()
