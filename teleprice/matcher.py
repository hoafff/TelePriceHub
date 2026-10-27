"""Product deduplication & canonical matching engine.

Level 1: Zero-cost rule-based deterministic matching.
Level 2: Gemini API fallback with strict spec-preservation guardrails.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


class ProductMatcher:
    # Common software/subscription brand dictionary for deterministic match
    CANONICAL_BRANDS = [
        "netflix",
        "spotify",
        "youtube",
        "chatgpt",
        "claude",
        "office 365",
        "canva",
        "telegram premium",
        "jetbrains",
        "capcut",
        "adobe",
        "duolingo",
        "zoom",
        "vps",
        "google one",
        "apple one",
    ]

    def __init__(self, gemini_api_key: str = "", gemini_model: str = "gemini-2.0-flash") -> None:
        self.api_key = gemini_api_key
        self.model = gemini_model
        # ponytail: in-memory normalization cache; database persistence handles cross-restart deduplication
        self._cache: Dict[str, Tuple[str, str, str]] = {}

    def match(
        self,
        raw_name: str,
        specs: Dict[str, Any],
        spec_key: str,
        existing_products: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, str, str]:
        """Returns (canonical_name, brand, model).

        Ensures spec_key is strictly considered.
        """
        cache_key = f"{raw_name.lower().strip()}:{spec_key}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 1. Deterministic Rule-based matching (0 cost)
        canonical, brand, model = self._rule_based_match(raw_name)

        # Check existing catalog for exact brand/model match
        if existing_products:
            for p in existing_products:
                if (
                    p.get("canonical_name", "").lower() == canonical.lower()
                    and p.get("spec_key") == spec_key
                ):
                    result = (p["canonical_name"], p.get("brand", brand), p.get("model", model))
                    self._cache[cache_key] = result
                    return result

        # 2. If ambiguous and Gemini API Key is provided, ask Gemini
        if self.api_key and self._needs_ai_disambiguation(raw_name, canonical):
            ai_res = self._ask_gemini(raw_name, specs, spec_key, existing_products or [])
            if ai_res:
                self._cache[cache_key] = ai_res
                return ai_res

        result = (canonical, brand, model)
        self._cache[cache_key] = result
        return result

    def _rule_based_match(self, raw_name: str) -> Tuple[str, str, str]:
        cleaned = re.sub(r"[*_`#\[\]\(\)\{\}\-]", " ", raw_name)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        lower = cleaned.lower()

        detected_brand = ""
        for brand in self.CANONICAL_BRANDS:
            if brand in lower:
                detected_brand = brand.title()
                break

        # Extract tier/sub-brand
        sub_type = ""
        for tier in ["premium", "plus", "pro", "family", "extra", "vip", "student"]:
            if tier in lower:
                sub_type = tier.title()
                break

        if detected_brand:
            canonical_name = f"{detected_brand} {sub_type}".strip()
            return canonical_name, detected_brand, sub_type

        # Fallback to cleaned title if brand not recognized
        canonical_name = cleaned.title()
        return canonical_name, "", ""

    def _needs_ai_disambiguation(self, raw_name: str, canonical_name: str) -> bool:
        # ponytail: only invoke Gemini when rule-based matcher yields a generic or single-word unmapped name
        words = raw_name.split()
        return len(words) > 4 or canonical_name == raw_name.title()

    def _ask_gemini(
        self,
        raw_name: str,
        specs: Dict[str, Any],
        spec_key: str,
        catalog: List[Dict[str, Any]],
    ) -> Optional[Tuple[str, str, str]]:
        # ponytail: direct REST call using urllib.request; avoids 50MB google-genai dependency
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        catalog_sample = [
            {"id": p.get("id"), "name": p.get("canonical_name"), "spec_key": p.get("spec_key")}
            for p in catalog[:20]
        ]

        prompt = f"""You are a strict product catalog deduplicator.
Target Raw Product: "{raw_name}"
Extracted Specs: {json.dumps(specs, ensure_ascii=False)}
Spec Key: "{spec_key}"
Existing Catalog: {json.dumps(catalog_sample, ensure_ascii=False)}

CRITICAL RULE:
NEVER merge products if they have different specifications (different RAM, storage, duration, plan tier).
Return JSON only:
{{
  "canonical_name": "Standard Title",
  "brand": "Brand",
  "model": "Model/Plan"
}}"""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
            },
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                parsed = json.loads(text)
                return (
                    parsed.get("canonical_name", raw_name),
                    parsed.get("brand", ""),
                    parsed.get("model", ""),
                )
        except Exception as e:
            logger.warning("Gemini API call skipped/failed: %s", e)
            return None
