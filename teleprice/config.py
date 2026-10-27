"""Configuration manager for TelePriceHub.

Uses stdlib os and pathlib to parse .env file with zero external dependencies.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import List


def load_dotenv(env_path: Path) -> None:
    # ponytail: naive key=value parser; handles comments and unquoted/quoted strings, upgrade to python-dotenv if multi-line values needed
    if not env_path.is_file():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            if key not in os.environ:
                os.environ[key] = val


# Load default .env from project root or current working dir
_root_env = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_root_env)


@dataclass
class Config:
    telegram_api_id: int = field(default_factory=lambda: int(os.getenv("TELEGRAM_API_ID", "0")))
    telegram_api_hash: str = field(default_factory=lambda: os.getenv("TELEGRAM_API_HASH", ""))
    telegram_session_name: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_SESSION_NAME", "teleprice_userbot")
    )
    telegram_string_session: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_STRING_SESSION", "")
    )
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    allowed_user_ids: List[int] = field(
        default_factory=lambda: [
            int(x.strip()) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()
        ]
    )
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    supplier_bots: List[str] = field(
        default_factory=lambda: [
            x.strip() for x in os.getenv("SUPPLIER_BOTS", "").split(",") if x.strip()
        ]
    )
    crawl_delay_min: float = field(
        default_factory=lambda: float(os.getenv("CRAWL_DELAY_MIN", "1.5"))
    )
    crawl_delay_max: float = field(
        default_factory=lambda: float(os.getenv("CRAWL_DELAY_MAX", "3.0"))
    )
    max_depth: int = field(default_factory=lambda: int(os.getenv("MAX_DEPTH", "5")))
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "teleprice.db"))


config = Config()
