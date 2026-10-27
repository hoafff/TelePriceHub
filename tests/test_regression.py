"""Regression tests for the defects found during independent review."""
import asyncio
import os
import tempfile
import unittest

from teleprice.parser import MessageParser
from teleprice.crawler import TelegramCrawler
from teleprice.mock import MockBotSimulator, MockTelegramClient, MockButton
from teleprice.db import Database
from teleprice.comparator import PriceComparator
from teleprice.bot import QueryBot

class RegressionTests(unittest.TestCase):
    def test_usd_prefix_price(self):
        p=MessageParser.parse("Product: Tool Pro\nPrice: $9.99")
        self.assertEqual((p.price,p.currency),(9.99,"USD"))

    def test_discounted_price_wins(self):
        p=MessageParser.parse("Tên: App Pro\nGiá gốc: 50k\nGiá khuyến mãi: 35k")
        self.assertEqual(p.price,35000)

    def test_delivery_types_are_not_equal(self):
        a=MessageParser.parse("Tên: ChatGPT Plus tài khoản riêng\nGiá: 50k")
        b=MessageParser.parse("Tên: ChatGPT Plus shared\nGiá: 30k")
        self.assertNotEqual(a.spec_key,b.spec_key)

    def test_backup_and_cashback_are_not_back(self):
        self.assertTrue(TelegramCrawler._safe_button(MockButton("Cloud Backup")))
        self.assertTrue(TelegramCrawler._safe_button(MockButton("Cashback")))

    def test_checkout_and_payment_never_pressed(self):
        for label in ("Mua ngay","💳 Thanh toán","Buy now","Confirm order","Nạp tiền"):
            self.assertFalse(TelegramCrawler._safe_button(MockButton(label)))

    def test_refresh_full_catalog_on_second_run(self):
        with tempfile.TemporaryDirectory() as d:
            db=Database(os.path.join(d,"prices.db"))
            sim=MockBotSimulator()
            crawler=TelegramCrawler(client=MockTelegramClient(sim),db=db)
            crawler.enable_throttle=False
            first=asyncio.run(crawler.crawl_supplier("@mock_supplier_bot",max_depth=4))
            second=asyncio.run(crawler.crawl_supplier("@mock_supplier_bot",max_depth=4))
            self.assertGreater(first,0)
            self.assertEqual(first,second)

    def test_currency_groups_are_separate(self):
        offers=[
          {"canonical_name":"Test","spec_key":"duration:1m","currency":"USD","price":2,"in_stock":1,"supplier_username":"@a"},
          {"canonical_name":"Test","spec_key":"duration:1m","currency":"VND","price":60000,"in_stock":1,"supplier_username":"@b"}
        ]
        self.assertEqual(len(PriceComparator.compare(offers)),2)

    def test_out_of_stock_is_not_cheapest(self):
        offers=[
          {"canonical_name":"Test","spec_key":"duration:1m","currency":"VND","price":20000,"in_stock":0,"supplier_username":"@a"},
          {"canonical_name":"Test","spec_key":"duration:1m","currency":"VND","price":30000,"in_stock":1,"supplier_username":"@b"}
        ]
        result=PriceComparator.compare(offers)
        self.assertEqual(result[0].min_price,30000)

    def test_query_bot_deny_if_no_whitelist(self):
        with tempfile.TemporaryDirectory() as d:
            bot=QueryBot(bot_token="fake:test",db=Database(os.path.join(d,"test.db")),allowed_users=[])
            messages=[]
            bot.send_message=lambda chat_id,text,**kw:messages.append(text)
            bot.handle_update({"message":{"chat":{"id":12},"from":{"id":12},"text":"/status"}})
            self.assertTrue(messages and "không có quyền" in messages[0].lower())

if __name__=="__main__":
    unittest.main()
