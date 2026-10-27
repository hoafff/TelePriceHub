"""Comprehensive test suite for TelePriceHub core modules.

Executes assertions on parser, database, product matcher, price comparator,
and end-to-end crawler traversal with the mock bot.
"""

import asyncio
import os
import tempfile
import unittest

from teleprice.comparator import PriceComparator
from teleprice.crawler import TelegramCrawler
from teleprice.db import Database
from teleprice.matcher import ProductMatcher
from teleprice.mock import MockBotSimulator, MockTelegramClient
from teleprice.parser import MessageParser


class TestMessageParser(unittest.TestCase):
    def test_vnd_price_and_duration_extraction(self):
        text = (
            "⭐ THÔNG TIN SẢN PHẨM ⭐\n"
            "Tên: Netflix Premium Ultra HD\n"
            "Thời hạn: 1 tháng\n"
            "Chất lượng: 4K UHD\n"
            "Tình trạng: Còn hàng\n"
            "Giá: 65.000đ"
        )
        parsed = MessageParser.parse(text)
        self.assertTrue(parsed.is_product)
        self.assertEqual(parsed.price, 65000.0)
        self.assertEqual(parsed.currency, "VND")
        self.assertEqual(parsed.in_stock, 1)
        self.assertEqual(parsed.duration, "1m")
        self.assertIn("duration:1m", parsed.spec_key)
        self.assertIn("quality:4k", parsed.spec_key)

    def test_k_suffix_and_out_of_stock(self):
        text = "Tài khoản Canva Pro 1 năm. Tình trạng: Hết hàng. Giá: 180k"
        parsed = MessageParser.parse(text)
        self.assertTrue(parsed.is_product)
        self.assertEqual(parsed.price, 180000.0)
        self.assertEqual(parsed.in_stock, 0)
        self.assertEqual(parsed.duration, "1y")

    def test_hardware_specs_extraction(self):
        text = "VPS Singapore. CPU: 4 Core, 8GB RAM, 128GB SSD. Giá: $15.5 USDT. Sẵn hàng."
        parsed = MessageParser.parse(text)
        self.assertTrue(parsed.is_product)
        self.assertEqual(parsed.price, 15.5)
        self.assertEqual(parsed.currency, "USDT")
        self.assertEqual(parsed.specs.get("cpu"), "4core")
        self.assertEqual(parsed.specs.get("ram"), "8gb")
        self.assertEqual(parsed.specs.get("storage"), "128gb")
        self.assertIn("cpu:4core", parsed.spec_key)
        self.assertIn("ram:8gb", parsed.spec_key)

    def test_category_menu_not_a_product(self):
        text = "🤖 Vui lòng chọn danh mục bạn muốn mua bên dưới:"
        parsed = MessageParser.parse(text)
        self.assertFalse(parsed.is_product)
        self.assertIsNone(parsed.price)


class TestProductMatcher(unittest.TestCase):
    def setUp(self):
        self.matcher = ProductMatcher(gemini_api_key="")

    def test_deterministic_brand_and_tier_match(self):
        raw = "Netflix Premium 4K tài khoản chính chủ"
        specs = {"duration": "1m", "quality": "4k"}
        spec_key = "duration:1m|quality:4k"

        canonical, brand, model = self.matcher.match(raw, specs, spec_key)
        self.assertEqual(brand, "Netflix")
        self.assertEqual(model, "Premium")
        self.assertEqual(canonical, "Netflix Premium")

    def test_spec_isolation_never_collapse(self):
        # 1 Month vs 3 Months must preserve distinct spec_key
        raw1 = "Netflix Ultra HD Gói 1 Tháng"
        raw2 = "Netflix Ultra HD Gói 3 Tháng"
        spec1 = "duration:1m|quality:4k"
        spec2 = "duration:3m|quality:4k"

        c1, _, _ = self.matcher.match(raw1, {"duration": "1m"}, spec1)
        c2, _, _ = self.matcher.match(raw2, {"duration": "3m"}, spec2)

        self.assertEqual(c1, c2)  # Canonical name matches
        self.assertNotEqual(spec1, spec2)  # Spec keys remain distinct


class TestDatabaseAndComparator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.db = Database(self.tmp.name)

    def tearDown(self):
        self.tmp.close()
        if os.path.exists(self.tmp.name):
            os.remove(self.tmp.name)

    def test_pricing_and_ranking_flow(self):
        supp1 = self.db.upsert_supplier("@shop_alpha", "Shop Alpha")
        supp2 = self.db.upsert_supplier("@shop_beta", "Shop Beta")

        prod_id = self.db.upsert_product(
            raw_name="Netflix 1T",
            canonical_name="Netflix Premium",
            brand="Netflix",
            model="Premium",
            spec_key="duration:1m|quality:4k",
        )

        # Alpha sells for 70k, Beta sells for 65k
        self.db.save_offer(supp1, prod_id, 70000.0, "VND", 1, "1m", "detail")
        self.db.save_offer(supp2, prod_id, 65000.0, "VND", 1, "1m", "detail")

        offers = self.db.get_comparison("Netflix")
        self.assertEqual(len(offers), 2)

        comps = PriceComparator.compare(offers)
        self.assertEqual(len(comps), 1)

        c = comps[0]
        self.assertEqual(c.min_price, 65000.0)
        self.assertEqual(c.rankings[0].supplier_username, "@shop_beta")
        self.assertEqual(c.rankings[0].rank, 1)
        self.assertEqual(c.rankings[0].delta_amount, 0.0)

        self.assertEqual(c.rankings[1].supplier_username, "@shop_alpha")
        self.assertEqual(c.rankings[1].rank, 2)
        self.assertEqual(c.rankings[1].delta_amount, 5000.0)

        # Verify markdown table generation
        md = PriceComparator.format_markdown_table(c)
        self.assertIn("Bảng so sánh: Netflix Premium", md)
        self.assertIn("#1", md)
        self.assertIn("#2", md)


class TestMockCrawlerIntegration(unittest.TestCase):
    def test_end_to_end_mock_crawl(self):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        try:
            db = Database(tmp.name)
            sim = MockBotSimulator("@mock_bot")
            client = MockTelegramClient(sim)

            crawler = TelegramCrawler(client=client, db=db)
            crawler.enable_throttle = False

            # Run crawler
            asyncio.run(crawler.crawl_supplier("@mock_bot", max_depth=4))

            # Validate products stored
            offers = db.get_comparison()
            self.assertGreater(len(offers), 0)

            # Check that Netflix 1 month, Netflix 3 months, Spotify, and VPS were extracted
            canonicals = {o["canonical_name"] for o in offers}
            self.assertIn("Netflix Premium", canonicals)
            self.assertIn("Spotify Premium", canonicals)
        finally:
            tmp.close()
            if os.path.exists(tmp.name):
                os.remove(tmp.name)


if __name__ == "__main__":
    unittest.main()
