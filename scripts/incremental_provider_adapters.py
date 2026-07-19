import time

try:
    from .build_news_dashboard import collect_gdelt
    from .fetch_naver_news import NaverRequestError, collect_naver_articles
    from .score_news import assess_relevance
except ImportError:
    from build_news_dashboard import collect_gdelt
    from fetch_naver_news import NaverRequestError, collect_naver_articles
    from score_news import assess_relevance


class NaverIncrementalProvider:
    name = "naver"

    def fetch(self, company, start_at, end_at, request_budget, continuation=None):
        articles, meta = collect_naver_articles(
            company, start_at, end_at, query_budget=request_budget, sorts=("date",),
        )
        if meta.get("credentials_status") == "naver_credentials_missing":
            raise NaverRequestError("NaverCredentialsMissing", 0)
        if meta.get("errors") and not articles:
            error_type = meta["errors"][0].get("type", "NaverProviderError")
            raise NaverRequestError(error_type, meta.get("request_count", 0))
        relevant = []
        rejected = {}
        for article in articles:
            accepted, reason, _ = assess_relevance(article, company)
            if accepted and article.get("relevance_score", 0) >= 60:
                relevant.append(article)
            else:
                key = reason or "relevance_score_below_threshold"
                rejected[key] = rejected.get(key, 0) + 1
        return relevant, {
            "request_count": meta.get("request_count", 0),
            "raw_count": meta.get("raw_count", len(articles)),
            "relevant_count": len(relevant),
            "rejected": rejected,
            "continuation": None,
        }


class GdeltIncrementalProvider:
    name = "gdelt"

    def __init__(self, request_delay_seconds=1):
        self.request_delay_seconds = max(0, request_delay_seconds)
        self.last_request_at = None

    def fetch(self, company, start_at, end_at, request_budget, continuation=None):
        if request_budget < 1:
            return [], {"request_count": 0, "raw_count": 0, "continuation": None}
        if self.last_request_at is not None:
            remaining = self.request_delay_seconds - (time.monotonic() - self.last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        articles, meta = collect_gdelt(company, start_at, end_at)
        self.last_request_at = time.monotonic()
        return articles, {
            "request_count": meta.get("request_count", 0),
            "raw_count": meta.get("raw_count", len(articles)),
            "relevant_count": len(articles),
            "rejected": dict(meta.get("rejected", {})),
            "continuation": None,
        }
