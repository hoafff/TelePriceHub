"""Zero-cost rule and regex parser for Telegram bot product messages.

Extracts price, currency, stock status, duration, and hardware/plan specifications.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, Optional


@dataclass
class ParsedProduct:
    is_product: bool
    name: str
    price: Optional[float] = None
    currency: str = "VND"
    in_stock: int = 1
    duration: str = ""
    specs: Dict[str, Any] = field(default_factory=dict)
    spec_key: str = "default"


class MessageParser:
    """Deterministic extractor for Telegram supplier bot messages."""

    # Price patterns
    _RE_PRICE_VND = re.compile(
        r"(?:(?:giá|price|tổng)[:\s]*)?([\d\.,]+)\s*(?:vnđ|vnd|đ)\b", re.IGNORECASE
    )
    _RE_PRICE_K = re.compile(
        r"(?:giá|price|tổng)[:\s]+([\d\.,]+)\s*k\b|(?<![248\d])([1-9]\d{1,4})\s*k\b",
        re.IGNORECASE,
    )
    _RE_PRICE_USD = re.compile(
        r"(?:giá|price)?[:\s]*(?:\$|usdt|usd)?\s*([\d\.,]+)\s*(?:\$|usdt|usd)", re.IGNORECASE
    )
    _RE_PRICE_STANDALONE = re.compile(
        r"(?:giá|price|thanh toán)[:\s]*([\d\.,]+)", re.IGNORECASE
    )

    # Stock patterns
    _RE_OUT_OF_STOCK = re.compile(
        r"(hết hàng|out of stock|tạm hết|sold out|hết slot|stock:\s*0\b)", re.IGNORECASE
    )
    _RE_IN_STOCK = re.compile(
        r"(còn hàng|sẵn hàng|in stock|có sẵn|sẵn slot|stock:\s*\d+)", re.IGNORECASE
    )

    # Duration patterns
    _RE_DURATION = re.compile(
        r"(\d+\s*(?:tháng|năm|ngày|month|months|year|years|day|days)|vĩnh viễn|lifetime)",
        re.IGNORECASE,
    )

    # Hardware & Plan Specs
    _RE_RAM = re.compile(r"(\d+)\s*(?:gb|mb)\s*ram", re.IGNORECASE)
    _RE_STORAGE = re.compile(
        r"(\d+)\s*(?:gb|tb)\s*(?:ssd|hdd|nvme|rom|dung lượng|ổ cứng)\b", re.IGNORECASE
    )
    _RE_CPU = re.compile(r"(\d+)\s*(?:core|vcpu|cpu)", re.IGNORECASE)
    _RE_QUALITY = re.compile(r"\b(4k|uhd|fhd|1080p|720p)\b", re.IGNORECASE)
    _RE_PLAN_TYPE = re.compile(r"\b(family|solo|cá nhân|premium|extra|plus|vip)\b", re.IGNORECASE)

    @classmethod
    def parse(cls, text: str, fallback_title: str = "") -> ParsedProduct:
        text = text.strip()
        if not text and not fallback_title:
            return ParsedProduct(is_product=False, name="")

        # 1. Parse explicit prices per line and prefer discounted selling prices.
        price = None
        currency = "VND"
        candidates = []
        for line in text.splitlines():
            low = line.lower()
            if not re.search(r"giá|price|cost|\$|vnd|vnđ|usdt|usd|\d+đ\b", low):
                continue
            if re.search(r"giá\s*(?:gốc|niêm yết)|original\s*price|list\s*price|giá\s*cũ", low):
                priority = -10
            elif re.search(r"khuyến mãi|ưu đãi|giá\s*bán|sale|discount|now|giá\s*cuối|thực thu", low):
                priority = 10
            else:
                priority = 0
            money = re.search(
                r"(?:\$\s*(\d+(?:[.,]\d{1,3})?)\s*(?:USDT|USD)?|"
                r"(\d+(?:[.,]\d+)?)\s*(USDT|USD|\$)|"
                r"(?:USDT|USD)\s*(\d+(?:[.,]\d+)?)|"
                r"(\d[\d.,\s]*)\s*(vnđ|vnd|đ)\b|"
                r"(\d+(?:[.,]\d+)?)\s*k\b)",
                line, re.I)
            if not money and re.search(r"^\s*(?:giá|price|cost)\s*[:：]", line, re.I):
                money = re.search(r"(\d+(?:[.,]\d+)?)", line)
            if not money:
                continue
            raw = next((x for x in money.groups() if x and re.search(r"\d", x)), None)
            if not raw:
                continue
            raw = raw.strip().replace(" ", "")
            cur = "VND"
            if re.search(r"\$|USDT|USD", money.group(0), re.I):
                cur = "USDT" if "usdt" in money.group(0).lower() else "USD"
                value = float(raw.replace(",", ""))
            elif re.search(r"k\s*$", money.group(0), re.I):
                value = float(raw.replace(",", ".")) * 1000
            else:
                value = float(re.sub(r"[.,]", "", raw)) if re.search(r"[.,]\d{3}$", raw) else float(raw.replace(",", "."))
            if value > 0:
                candidates.append((priority, len(candidates), value, cur))
        if candidates:
            chosen = max(candidates, key=lambda x: (x[0], -x[1]))
            price, currency = chosen[2], chosen[3]

        # If no price found, check if it's likely a category menu, not a product page
        if price is None:
            return ParsedProduct(
                is_product=False,
                name=fallback_title or text.split("\n")[0][:60],
            )

        # 2. Stock status
        in_stock = 1
        if cls._RE_OUT_OF_STOCK.search(text):
            in_stock = 0
        elif cls._RE_IN_STOCK.search(text):
            in_stock = 1

        # 3. Specs extraction
        specs: Dict[str, Any] = {}

        # Duration
        dur_match = cls._RE_DURATION.search(text) or (
            cls._RE_DURATION.search(fallback_title) if fallback_title else None
        )
        duration_str = dur_match.group(1).lower().strip() if dur_match else ""
        if duration_str:
            # normalize duration
            norm_dur = cls._normalize_duration(duration_str)
            specs["duration"] = norm_dur
            duration_str = norm_dur

        # RAM
        ram_match = cls._RE_RAM.search(text)
        if ram_match:
            specs["ram"] = f"{ram_match.group(1)}gb".lower()

        # Storage
        storage_match = cls._RE_STORAGE.search(text)
        if storage_match:
            specs["storage"] = f"{storage_match.group(1)}gb".lower()

        # CPU
        cpu_match = cls._RE_CPU.search(text)
        if cpu_match:
            specs["cpu"] = f"{cpu_match.group(1)}core".lower()

        # Quality
        qual_match = cls._RE_QUALITY.search(text) or (
            cls._RE_QUALITY.search(fallback_title) if fallback_title else None
        )
        if qual_match:
            specs["quality"] = qual_match.group(1).lower()

        # Plan type
        plan_match = cls._RE_PLAN_TYPE.search(text) or (
            cls._RE_PLAN_TYPE.search(fallback_title) if fallback_title else None
        )
        if plan_match:
            specs["plan"] = plan_match.group(1).lower()

        if re.search(r"nâng (?:chính chủ|cấp)|upgrade|nâng cấp", text+" "+fallback_title, re.I):
            specs["delivery"] = "upgrade"
        elif re.search(r"shared|dùng chung|chia sẻ", text+" "+fallback_title, re.I):
            specs["delivery"] = "shared"
        elif re.search(r"tài khoản riêng|private account|account riêng", text+" "+fallback_title, re.I):
            specs["delivery"] = "private"

        # 4. Generate deterministic spec key
        # Crucial: specs must be sorted to ensure identical key representation
        spec_parts = [f"{k}:{specs[k]}" for k in sorted(specs.keys())]
        spec_key = "|".join(spec_parts) if spec_parts else "standard"

        # 5. Determine product name
        name = cls._extract_title(text, fallback_title)

        return ParsedProduct(
            is_product=True,
            name=name,
            price=price,
            currency=currency,
            in_stock=in_stock,
            duration=duration_str,
            specs=specs,
            spec_key=spec_key,
        )

    @staticmethod
    def _normalize_duration(raw: str) -> str:
        s = raw.lower().replace(" ", "")
        s = re.sub(r"tháng|months|month", "m", s)
        s = re.sub(r"năm|years|year", "y", s)
        s = re.sub(r"ngày|days|day", "d", s)
        s = re.sub(r"vĩnhviễn|lifetime", "lifetime", s)
        return s

    @staticmethod
    def _extract_title(text: str, fallback: str) -> str:
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        # 1. Check for explicit name label (e.g. "Tên: Netflix Premium", "Sản phẩm: Spotify")
        for line in lines:
            m = re.match(
                r"^(?:tên|sản phẩm|gói|dịch vụ|product|item)[:\s]+(.+)", line, re.IGNORECASE
            )
            if m:
                cleaned = re.sub(r"[*_`#⭐\-\–]", "", m.group(1)).strip()
                if len(cleaned) >= 3:
                    return cleaned

        # Explicit product name wins over button labels, which may omit the plan/tier.
        if fallback:
            cleaned = re.sub(r"^[0-9\.\-\–\s]+", "", fallback).strip()
            if len(cleaned) >= 3 and not any(
                h in cleaned.lower() for h in ["mua ngay", "đặt hàng", "quay lại", "back"]
            ):
                return cleaned

        # 2. Skip decorative headers and metadata lines
        for line in lines:
            clean_line = re.sub(r"[*_`#⭐\-\–]", "", line).strip()
            clean_line = re.sub(r"^[0-9\.\s]+", "", clean_line).strip()
            lower = clean_line.lower()
            if any(
                h in lower
                for h in ["thông tin", "bảng giá", "chi tiết", "chào mừng", "menu", "store", "shop"]
            ):
                continue
            if not any(
                k in lower
                for k in ["giá:", "price:", "tình trạng:", "bảo hành:", "stock:", "thời hạn:"]
            ):
                if len(clean_line) >= 3:
                    return clean_line[:80]

        return lines[0][:80] if lines else "Unknown Product"
