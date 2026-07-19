import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import os

from scripts.fetch_naver_news import build_company_queries, collect_naver_articles, load_naver_credentials
from scripts.normalize_news import clean_markup, normalize_naver_item, parse_naver_pubdate


COMPANY = {
    "company_name": "SK하이닉스", "stock_code": "000660", "aliases": ["SK하이닉스"],
    "english_aliases": ["SK hynix"], "important_keywords": ["HBM", "투자"],
    "official_sources": ["news.skhynix.com"], "major_source_domains": ["yna.co.kr"],
}


def naver_item(**overrides):
    item = {
        "title": "<b>SK하이닉스</b> HBM 투자 확대",
        "description": "AI &amp; 메모리 생산 투자",
        "originallink": "https://www.yna.co.kr/view/AKR1?utm_source=naver",
        "link": "https://n.news.naver.com/article/001/1",
        "pubDate": "Fri, 17 Jul 2026 10:20:00 +0900",
    }
    item.update(overrides)
    return item


class NaverNewsTests(unittest.TestCase):
    def test_bold_markup_is_removed(self):
        self.assertEqual(clean_markup("<b>SK하이닉스</b>"), "SK하이닉스")

    def test_html_entity_is_decoded(self):
        self.assertEqual(clean_markup("HBM &amp; DRAM"), "HBM & DRAM")

    def test_original_link_is_preferred(self):
        article = normalize_naver_item(naver_item(), COMPANY, "2026-07-17T10:30:00+09:00")
        self.assertEqual(article["url"], "https://yna.co.kr/view/AKR1")

    def test_link_is_used_when_original_link_is_missing(self):
        article = normalize_naver_item(naver_item(originallink=""), COMPANY, "2026-07-17T10:30:00+09:00")
        self.assertEqual(article["url"], "https://n.news.naver.com/article/001/1")

    def test_pubdate_is_converted_to_seoul_timezone(self):
        self.assertEqual(parse_naver_pubdate("Fri, 17 Jul 2026 01:20:00 +0000"), "2026-07-17T10:20:00+09:00")

    def test_description_does_not_pollute_primary_event_signals(self):
        item = naver_item(
            title="<b>SK하이닉스</b> HBM 투자 확대",
            description="실적 공급 규제 인수 생산 관련 배경 설명",
        )
        article = normalize_naver_item(item, COMPANY, "2026-07-17T10:30:00+09:00")
        self.assertEqual(article["event_keywords"], ["hbm", "investment"])
        self.assertIn("earnings", article["_description_event_keywords"])

    def test_missing_credentials_safely_skips(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.env"
            # Keep this missing-credential contract independent of CI secrets and local files.
            with patch.dict(os.environ, {"NAVER_CLIENT_ID": "", "NAVER_CLIENT_SECRET": ""}, clear=False):
                self.assertIsNone(load_naver_credentials(missing))
                articles, report = collect_naver_articles(
                    COMPANY,
                    datetime(2026, 7, 10, tzinfo=timezone.utc),
                    datetime(2026, 7, 17, tzinfo=timezone.utc),
                    credentials_path=missing,
                )
            self.assertEqual(articles, [])
            self.assertEqual(report["credentials_status"], "naver_credentials_missing")

    def test_company_query_budget_is_capped(self):
        queries = build_company_queries(COMPANY, query_budget=3)
        self.assertEqual(len(queries), 3)
        self.assertEqual(queries[0], "SK하이닉스")
        self.assertFalse(any(query.strip().casefold() in {"sk", "hynix"} for query in queries))


if __name__ == "__main__":
    unittest.main()
