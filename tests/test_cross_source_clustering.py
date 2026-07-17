import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.build_news_dashboard import run_integrated_pipeline
from scripts.cluster_news_events import (
    build_public_event,
    cluster_event_articles,
    deduplicate_standard_articles,
    score_event,
)
from scripts.normalize_news import FORBIDDEN_PUBLIC_FIELDS
from scripts.normalize_news import event_signals


NOW = datetime(2026, 7, 17, 3, 0, tzinfo=timezone.utc)
COMPANY = {
    "company_name": "SK하이닉스", "stock_code": "000660", "aliases": ["SK하이닉스"],
    "english_aliases": ["SK hynix"], "important_keywords": ["HBM", "투자"],
    "official_sources": ["news.skhynix.com"], "major_source_domains": ["reuters.com", "yna.co.kr", "bloomberg.com"],
}


def article(title, url, provider="gdelt", region="international", published="2026-07-17T02:00:00Z",
            keywords=None, domain="example.com", tier="other"):
    return {
        "article_id": f"{provider}-{url}", "provider": provider, "providers": [provider],
        "company_name": "SK하이닉스", "stock_code": "000660", "title": title,
        "normalized_title": title.lower(), "url": url, "canonical_url": url,
        "source_domain": domain, "source_name": domain, "published_at": published,
        "collected_at": "2026-07-17T12:00:00+09:00", "language": "Korean" if region == "domestic" else "English",
        "region": region, "matched_alias": "SK하이닉스" if "SK하이닉스" in title else "SK hynix",
        "categories": ["투자·생산"], "event_keywords": keywords or ["investment", "hbm"],
        "official_source": tier == "official", "source_tier": tier, "relevance_score": 90,
    }


class CrossSourceClusteringTests(unittest.TestCase):
    def test_same_url_from_gdelt_and_naver_is_deduplicated(self):
        items = [article("SK hynix HBM investment", "https://example.com/a", "gdelt"),
                 article("SK하이닉스 HBM 투자", "https://example.com/a", "naver", "domestic")]
        unique, meta = deduplicate_standard_articles(items)
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0]["providers"], ["gdelt", "naver"])
        self.assertEqual(meta["cross_provider_url_duplicates"], 1)

    def test_tracking_urls_merge(self):
        items = [article("SK hynix HBM", "https://example.com/a?utm_source=x"),
                 article("SK hynix HBM", "https://example.com/a")]
        unique, _ = deduplicate_standard_articles(items)
        self.assertEqual(len(unique), 1)

    def test_korean_and_english_same_event_cluster(self):
        clusters = cluster_event_articles([
            article("SK하이닉스 HBM 투자 확대", "https://a.com/1", "naver", "domestic"),
            article("SK hynix expands HBM investment", "https://b.com/2", "gdelt", "international"),
        ])
        self.assertEqual(len(clusters), 1)

    def test_bilingual_executive_shareholder_message_signals(self):
        korean = set(event_signals("최태원 회장, 주식 팔지 말고 보유"))
        english = set(event_signals("SK Group chief says hold onto your shares"))
        self.assertGreaterEqual(len(korean & english), 2)

    def test_different_events_stay_separate(self):
        first = article("SK하이닉스 HBM 투자", "https://a.com/1", keywords=["investment", "hbm"])
        second = article("SK하이닉스 분기 실적", "https://b.com/2", keywords=["earnings", "2026"])
        self.assertEqual(len(cluster_event_articles([first, second])), 2)

    def test_events_over_72_hours_stay_separate(self):
        first = article("SK hynix HBM investment", "https://a.com/1", published="2026-07-10T01:00:00Z")
        second = article("SK hynix HBM investment expands", "https://b.com/2", published="2026-07-14T02:00:00Z")
        self.assertEqual(len(cluster_event_articles([first, second])), 2)

    def test_domestic_and_international_bonus(self):
        raw = {"articles": [article("SK하이닉스 HBM 투자", "https://yna.co.kr/1", "naver", "domestic", domain="yna.co.kr", tier="tier1"),
                            article("SK hynix HBM investment", "https://reuters.com/2", domain="reuters.com", tier="tier1")]}
        public = build_public_event(raw, COMPANY, now=NOW)
        self.assertIn("국내·해외 교차 보도 +10", public["scoring_reasons"])

    def test_duplicate_press_release_does_not_inflate_source_bonus(self):
        members = [article(f"SK hynix HBM investment {index}", f"https://news.skhynix.com/{index}", domain="news.skhynix.com", tier="official") for index in range(5)]
        public = build_public_event({"articles": members}, COMPANY, now=NOW)
        self.assertNotIn("서로 다른 신뢰 매체 3곳 이상 +10", public["scoring_reasons"])

    def test_score_is_not_inflated_by_article_count(self):
        one = build_public_event({"articles": [article("SK hynix HBM investment", "https://example.com/1")]}, COMPANY, now=NOW)
        many = build_public_event({"articles": [article(f"SK hynix HBM investment report {index}", f"https://example.com/{index}") for index in range(5)]}, COMPANY, now=NOW)
        self.assertEqual(one["importance_score"], many["importance_score"])

    def test_public_event_has_no_body_or_description(self):
        item = article("SK hynix HBM investment", "https://example.com/1")
        item["_description"] = "temporary relevance text"
        public = build_public_event({"articles": [item]}, COMPANY, now=NOW)
        serialized = json.dumps(public)
        for key in FORBIDDEN_PUBLIC_FIELDS:
            self.assertNotIn(f'"{key}"', serialized)

    def test_integrated_failure_preserves_existing_news(self):
        with tempfile.TemporaryDirectory() as directory:
            news_path = Path(directory) / "news.json"
            report_path = Path(directory) / "report.json"
            original = {"generated_at": "keep", "news": [{"cluster_id": "keep"}]}
            news_path.write_text(json.dumps(original), encoding="utf-8")
            def fail(*_args):
                raise RuntimeError("offline")
            success, _ = run_integrated_pipeline(COMPANY, NOW - timedelta(days=7), NOW,
                                                 news_path, report_path, fail, fail)
            self.assertFalse(success)
            self.assertEqual(json.loads(news_path.read_text(encoding="utf-8")), original)


if __name__ == "__main__":
    unittest.main()
