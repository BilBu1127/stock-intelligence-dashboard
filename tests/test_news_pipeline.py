import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.fetch_gdelt_news import GdeltRequestError, run_pipeline
from scripts.score_news import (
    assess_relevance,
    cluster_articles,
    deduplicate_articles,
    match_company_alias,
    normalize_url,
    public_cluster,
    score_cluster,
    valid_aliases,
)


NOW = datetime(2026, 7, 17, 3, 0, tzinfo=timezone.utc)
COMPANY = {
    "company_name": "SK하이닉스",
    "stock_code": "000660",
    "aliases": ["SK하이닉스", "SK", "hynix"],
    "english_aliases": ["SK hynix", "SK Hynix Inc"],
    "important_keywords": ["HBM", "DRAM", "NAND", "AI memory"],
    "excluded_keywords": ["price target", "stock picks"],
    "official_sources": ["news.skhynix.com"],
    "major_source_domains": ["reuters.com", "bloomberg.com"],
}


def article(title, url, domain="example.com", published="2026-07-17T02:00:00Z"):
    return {
        "title": title,
        "url": url,
        "source_domain": domain,
        "published_at": published,
        "language": "English",
        "source_type": "other",
    }


def cluster_for(article_item, sources=None):
    return {
        "cluster_id": "test-cluster",
        "representative_article": article_item,
        "articles": [article_item],
        "article_count": 1,
        "source_domains": sources or [article_item["source_domain"]],
        "first_published_at": article_item["published_at"],
        "last_published_at": article_item["published_at"],
    }


class NewsPipelineTests(unittest.TestCase):
    def test_exact_company_alias_matching(self):
        self.assertEqual(match_company_alias("SK hynix unveils HBM4", COMPANY), "SK hynix")
        self.assertEqual(match_company_alias("SK하이닉스 HBM 투자 확대", COMPANY), "SK하이닉스")

    def test_ambiguous_aliases_are_excluded(self):
        self.assertNotIn("SK", valid_aliases(COMPANY))
        self.assertNotIn("hynix", valid_aliases(COMPANY))
        self.assertIsNone(match_company_alias("SK expands investment", COMPANY))
        self.assertIsNone(match_company_alias("Hynix mentioned alone", COMPANY))

    def test_url_normalization(self):
        first = normalize_url("http://www.example.com/news/1/?utm_source=x&b=2&a=1#top")
        second = normalize_url("https://example.com/news/1?a=1&b=2")
        self.assertEqual(first, second)

    def test_exact_article_deduplication(self):
        articles = [
            article("SK hynix unveils HBM4", "https://example.com/a?utm_source=x"),
            article("SK hynix unveils HBM4", "https://example.com/a"),
        ]
        unique, duplicate_count = deduplicate_articles(articles)
        self.assertEqual(len(unique), 1)
        self.assertEqual(duplicate_count, 1)

    def test_similar_titles_form_one_cluster(self):
        articles = [
            article("SK hynix begins mass production of HBM4 memory", "https://a.com/1", "a.com"),
            article("SK Hynix starts mass production of HBM4 memory", "https://b.com/2", "b.com"),
        ]
        clusters = cluster_articles(articles, COMPANY)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["article_count"], 2)

    def test_major_source_score(self):
        item = article("SK hynix unveils new memory", "https://reuters.com/a", "reuters.com")
        score, _, reasons = score_cluster(cluster_for(item), COMPANY, now=NOW)
        self.assertGreaterEqual(score, 50)
        self.assertIn("주요 언론 출처 +25", reasons)

    def test_important_keywords_are_capped_at_twenty(self):
        item = article("SK hynix HBM DRAM NAND AI memory roadmap", "https://example.com/a")
        score, _, reasons = score_cluster(cluster_for(item), COMPANY, now=NOW)
        self.assertTrue(any(reason.endswith("+20") for reason in reasons))
        self.assertLessEqual(score, 100)

    def test_stock_recommendation_penalty(self):
        item = article("SK hynix price target and stock picks", "https://example.com/a")
        _, _, reasons = score_cluster(cluster_for(item), COMPANY, now=NOW)
        self.assertIn("단순 주가·종목 추천 성격 -25", reasons)

    def test_three_sources_receive_bonus(self):
        item = article("SK hynix launches HBM4", "https://example.com/a")
        score, _, reasons = score_cluster(
            cluster_for(item, ["a.com", "b.com", "c.com"]),
            COMPANY,
            now=NOW,
        )
        self.assertIn("서로 다른 3개 이상 매체 보도 +15", reasons)
        self.assertGreaterEqual(score, 40)

    def test_score_is_clamped_to_range(self):
        item = article(
            "SK hynix HBM DRAM NAND AI memory",
            "https://news.skhynix.com/a",
            "news.skhynix.com",
        )
        score, level, _ = score_cluster(
            cluster_for(item, ["news.skhynix.com", "a.com", "b.com"]),
            COMPANY,
            now=NOW,
        )
        self.assertEqual(score, 100)
        self.assertEqual(level, "critical")

    def test_other_company_title_is_excluded(self):
        is_relevant, reason, _ = assess_relevance(
            article("Samsung launches new memory", "https://example.com/a"),
            COMPANY,
        )
        self.assertFalse(is_relevant)
        self.assertEqual(reason, "company_alias_not_in_title")

    def test_multi_company_market_article_is_excluded(self):
        is_relevant, reason, _ = assess_relevance(
            article(
                "SpaceX, Alphabet and SK Hynix flash a bullish signal for investors",
                "https://example.com/a",
            ),
            COMPANY,
        )
        self.assertFalse(is_relevant)
        self.assertEqual(reason, "multi_company_market_article")

    def test_other_company_main_topic_is_excluded(self):
        is_relevant, reason, _ = assess_relevance(
            article(
                "Commentator blames SK Hynix volatility for TSMC fall",
                "https://example.com/a",
            ),
            COMPANY,
        )
        self.assertFalse(is_relevant)
        self.assertEqual(reason, "other_company_is_main_topic")

    def test_api_failure_preserves_existing_news_json(self):
        with tempfile.TemporaryDirectory() as directory:
            news_path = Path(directory) / "news.json"
            report_path = Path(directory) / "news-report.json"
            original = {"generated_at": "existing", "news": [{"cluster_id": "keep"}]}
            news_path.write_text(json.dumps(original), encoding="utf-8")

            def fail_request(_url):
                raise GdeltRequestError("HTTP429", 3)

            success, report = run_pipeline(
                COMPANY,
                NOW - timedelta(days=7),
                NOW,
                news_path=news_path,
                report_path=report_path,
                request_fn=fail_request,
            )
            self.assertFalse(success)
            self.assertEqual(json.loads(news_path.read_text(encoding="utf-8")), original)
            self.assertEqual(report["errors"], [{"type": "HTTP429"}])

    def test_public_cluster_contains_no_article_body(self):
        item = article("SK hynix launches HBM4", "https://example.com/a")
        public = public_cluster(cluster_for(item), COMPANY, now=NOW)
        forbidden = {"body", "content", "html", "summary", "description", "image"}
        self.assertTrue(forbidden.isdisjoint(public))
        self.assertEqual(
            set(public),
            {
                "cluster_id",
                "company_name",
                "stock_code",
                "representative_title",
                "representative_url",
                "representative_source",
                "published_at",
                "source_count",
                "sources",
                "language",
                "importance_score",
                "importance_level",
                "categories",
                "scoring_reasons",
            },
        )


if __name__ == "__main__":
    unittest.main()
