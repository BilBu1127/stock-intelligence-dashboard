import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.news_batch_pipeline import (
    BatchNewsPipeline,
    MockNewsProvider,
    collection_window,
    load_pipeline_config,
    provider_cursor_template,
    retain_public_events,
)
from scripts.run_load_test import synthetic_companies
from scripts.telegram_incremental import distribute_messages, run_incremental


NOW = datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc)


class ScalablePipelineTests(unittest.TestCase):
    def setUp(self):
        self.config = load_pipeline_config()

    def test_incremental_window_uses_sixteen_hours_and_overlap(self):
        cursor = provider_cursor_template()
        cursor["last_successful_run"] = (NOW - timedelta(hours=12)).isoformat()
        start, end = collection_window(cursor, NOW, self.config)
        self.assertEqual(start, NOW - timedelta(hours=15))
        self.assertEqual(end, NOW)

    def test_new_company_uses_seven_day_backfill(self):
        start, _ = collection_window(provider_cursor_template(), NOW, self.config)
        self.assertEqual(start, NOW - timedelta(days=7))

    def test_low_retention_is_capped_at_ten(self):
        events = []
        for index in range(20):
            published = (NOW - timedelta(hours=index)).isoformat()
            events.append({"cluster_id": str(index), "last_published_at": published, "importance_level": "low"})
        self.assertEqual(len(retain_public_events(events, NOW, self.config["retention"])), 10)

    def test_batch_failure_does_not_advance_failed_cursor(self):
        companies = synthetic_companies(3)
        failed_code = companies[1]["stock_code"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            providers = {
                "naver": MockNewsProvider("naver", 2),
                "gdelt": MockNewsProvider("gdelt", 1, {failed_code}),
            }
            report = BatchNewsPipeline(root, self.config, providers).run(companies, now=NOW)
            state = json.loads((root / "state" / "news-cursors.json").read_text(encoding="utf-8"))
            failed_cursor = state["companies"][failed_code]["providers"]["gdelt"]
            self.assertIsNone(failed_cursor["last_successful_run"])
            self.assertEqual(failed_cursor["consecutive_failures"], 1)
            self.assertIn(failed_code, report["successful_companies"])
            self.assertTrue((root / "news" / "by-company" / f"{companies[0]['stock_code']}.json").is_file())
            success_state = state["companies"][companies[0]["stock_code"]]
            self.assertTrue(success_state["event_fingerprints"])
            self.assertTrue(success_state["article_hashes"])

    def test_api_budgets_are_respected(self):
        companies = synthetic_companies(10)
        with tempfile.TemporaryDirectory() as directory:
            report = BatchNewsPipeline(
                Path(directory) / "data", self.config,
                {"naver": MockNewsProvider("naver", 20), "gdelt": MockNewsProvider("gdelt", 20)},
            ).run(companies, now=NOW)
            self.assertLessEqual(report["provider_api_calls"]["naver"], 30)
            self.assertLessEqual(report["provider_api_calls"]["gdelt"], 10)

    def test_dashboard_index_has_no_article_arrays(self):
        companies = synthetic_companies(2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            BatchNewsPipeline(
                root, self.config,
                {"naver": MockNewsProvider("naver", 2), "gdelt": MockNewsProvider("gdelt", 1)},
            ).run(companies, now=NOW)
            index = json.loads((root / "news" / "index.json").read_text(encoding="utf-8"))
            self.assertFalse(any("articles" in item for item in index["news"]))
            self.assertEqual(len(index["companies"]), 2)

    def test_telegram_messages_are_fetched_once_and_distributed(self):
        companies = synthetic_companies(2)
        calls = []
        processed = []
        def fetch(last_id):
            calls.append(last_id)
            return [{"id": 11, "text": "테스트기업1 000001 공시"}, {"id": 12, "text": "테스트기업2 실적"}]
        def process(company, messages):
            processed.append((company["stock_code"], [item["id"] for item in messages]))
        with tempfile.TemporaryDirectory() as directory:
            cursor = Path(directory) / "telegram.json"
            success, report = run_incremental(fetch, process, companies, cursor)
            self.assertTrue(success)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(processed), 2)
            self.assertEqual(json.loads(cursor.read_text(encoding="utf-8"))["last_processed_message_id"], 12)
            self.assertTrue(report["cursor_updated"])

    def test_telegram_cursor_does_not_advance_on_partial_failure(self):
        companies = synthetic_companies(2)
        def fetch(_last_id):
            return [{"id": 21, "text": "테스트기업1 공시"}, {"id": 22, "text": "테스트기업2 공시"}]
        def process(company, _messages):
            if company["stock_code"] == "000002":
                raise RuntimeError("parse failure")
        with tempfile.TemporaryDirectory() as directory:
            cursor = Path(directory) / "telegram.json"
            success, report = run_incremental(fetch, process, companies, cursor)
            self.assertFalse(success)
            self.assertIsNone(json.loads(cursor.read_text(encoding="utf-8"))["last_processed_message_id"])
            self.assertFalse(report["cursor_updated"])


if __name__ == "__main__":
    unittest.main()
