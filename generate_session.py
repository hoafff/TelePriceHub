"""Helper script to generate a Telethon StringSession for headless environments (e.g. GitHub Actions)."""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from teleprice.config import config


async def main() -> None:
    api_id = config.telegram_api_id or int(input("Nhập TELEGRAM_API_ID: ").strip())
    api_hash = config.telegram_api_hash or input("Nhập TELEGRAM_API_HASH: ").strip()

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start()
    session_str = client.session.save()
    print("\n" + "=" * 60)
    print("TELEGRAM_STRING_SESSION của bạn:")
    print("=" * 60)
    print(session_str)
    print("=" * 60)
    print("Lưu chuỗi trên vào GitHub Secret hoặc file .env")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
