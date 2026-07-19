import json
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.fetch_gdelt_news import build_query
from scripts.fetch_naver_news import build_company_queries
from scripts.news_batch_pipeline import BatchNewsPipeline, MockNewsProvider, collection_window, load_pipeline_config, provider_cursor_template
from scripts.onboard_portfolio import validate_portfolio
from scripts.score_news import assess_relevance
from scripts.telegram_incremental import distribute_messages


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


class PortfolioOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads((ROOT / "data" / "portfolio-input.json").read_text(encoding="utf-8"))
        cls.companies = json.loads((ROOT / "data" / "companies.json").read_text(encoding="utf-8"))["companies"]
        cls.config = load_pipeline_config()

    def test_portfolio_has_expected_count_and_tiers(self):
        self.assertEqual(len(self.source["companies"]), 61)
        self.assertEqual(Counter(item["monitoring_tier"] for item in self.source["companies"]), Counter({"core": 19, "watch": 26, "background": 16}))

    def test_leading_zero_codes_remain_strings(self):
        samsung = next(item for item in self.companies if item["company_name"] == "삼성전자")
        self.assertEqual(samsung["stock_code"], "005930")
        self.assertIsInstance(samsung["stock_code"], str)

    def test_alphanumeric_code_is_preserved(self):
        company = next(item for item in self.companies if item["input_company_name"] == "에스엔시스")
        self.assertEqual(company["stock_code"], "0008Z0")

    def test_validation_detects_duplicate_names_and_codes(self):
        items = [
            {"company_name": "A", "stock_code": "000001", "category": "반도체", "monitoring_tier": "watch"},
            {"company_name": "A", "stock_code": "000001", "category": "반도체", "monitoring_tier": "watch"},
        ]
        _, summary = validate_portfolio(items, {}, NOW.isoformat())
        self.assertEqual(summary["duplicate_company_names"], ["A"])
        self.assertEqual(summary["duplicate_stock_codes"], ["000001"])

    def test_previous_company_name_matches_telegram(self):
        lig = next(item for item in self.companies if item["stock_code"] == "079550")
        result = distribute_messages([{"id": 1, "text": "LIG넥스원 방산 수출 수주 공시"}], [lig])
        self.assertEqual([item["id"] for item in result["079550"]], [1])

    def test_ambiguous_search_names_are_never_standalone_queries(self):
        gst = next(item for item in self.companies if item["stock_code"] == "083450")
        self.assertNotIn("GST", build_company_queries(gst))
        self.assertIn(" AND ", build_query(gst))
        self.assertIn("083450", build_query(gst))

    def test_ambiguous_company_requires_context(self):
        gst = next(item for item in self.companies if item["stock_code"] == "083450")
        unrelated = {"title": "GST 정책 일반 안내", "url": "https://example.com/a", "source_domain": "example.com"}
        related = {"title": "GST 반도체 장비 공급 확대", "url": "https://example.com/b", "source_domain": "example.com"}
        self.assertEqual(assess_relevance(unrelated, gst)[1], "ambiguous_company_without_context")
        self.assertTrue(assess_relevance(related, gst)[0])

    def test_other_company_article_is_not_assigned(self):
        sk = next(item for item in self.companies if item["stock_code"] == "000660")
        article = {"title": "삼성전자 HBM 생산 확대", "url": "https://example.com/a", "source_domain": "example.com"}
        self.assertFalse(assess_relevance(article, sk)[0])

    def test_shorter_portfolio_name_does_not_match_longer_company(self):
        psk = next(item for item in self.companies if item["stock_code"] == "319660")
        article = {"title": "피에스케이홀딩스 리플로우 장비 수주", "url": "https://example.com/a", "source_domain": "example.com"}
        self.assertEqual(assess_relevance(article, psk)[1], "other_portfolio_company_in_title")

    def test_tier_api_budgets(self):
        expected = {"core": 3, "watch": 2, "background": 1}
        for company in self.companies:
            self.assertEqual(company["naver_query_budget"], expected[company["monitoring_tier"]])
            self.assertEqual(company["gdelt_query_budget"], 1)

    def test_batches_are_twenty_five_twenty_five_eleven(self):
        with tempfile.TemporaryDirectory() as directory:
            report = BatchNewsPipeline(
                Path(directory) / "data", self.config,
                {"naver": MockNewsProvider("naver", 1), "gdelt": MockNewsProvider("gdelt", 1)},
            ).run(self.companies, now=NOW, backfill=True)
        self.assertEqual([item["company_count"] for item in report["batch_duration_seconds"]], [25, 25, 11])

    def test_failed_company_is_prioritized_on_next_run(self):
        failed = self.companies[30]["stock_code"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            first = BatchNewsPipeline(root, self.config, {"naver": MockNewsProvider("naver", 1, {failed})}).run(self.companies, now=NOW)
            second = BatchNewsPipeline(root, self.config, {"naver": MockNewsProvider("naver", 1)}).run(self.companies, now=NOW + timedelta(hours=12))
        self.assertIn(failed, first["failed_companies"])
        self.assertEqual(second["cursor_updates"][0]["stock_code"], failed)

    def test_unverified_company_is_excluded_from_collection(self):
        companies = [dict(self.companies[0]), dict(self.companies[1])]
        companies[1]["validation_status"] = "needs_review"
        with tempfile.TemporaryDirectory() as directory:
            report = BatchNewsPipeline(Path(directory) / "data", self.config, {"naver": MockNewsProvider("naver", 1)}).run(companies, now=NOW)
        self.assertEqual(report["active_companies"], 1)
        self.assertEqual(report["validation_excluded_companies"], [companies[1]["stock_code"]])

    def test_backfill_then_incremental_window(self):
        cursor = provider_cursor_template()
        start, _ = collection_window(cursor, NOW, self.config, backfill=True)
        self.assertEqual(start, NOW - timedelta(days=7))
        cursor["last_successful_run"] = (NOW - timedelta(hours=20)).isoformat()
        next_start, _ = collection_window(cursor, NOW, self.config)
        self.assertEqual(next_start, NOW - timedelta(hours=16))

    def test_public_files_contain_no_body_or_secret_fields(self):
        forbidden = {"body", "content", "html", "description", "client_secret", "session", "phone"}
        for path in (ROOT / "data" / "news").rglob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            stack = [payload]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    self.assertTrue(forbidden.isdisjoint(key.casefold() for key in value))
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)


if __name__ == "__main__":
    unittest.main()
