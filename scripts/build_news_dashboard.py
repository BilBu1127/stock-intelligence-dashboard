import argparse
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .cluster_news_events import PIPELINE_VERSION, build_public_event, cluster_event_articles, deduplicate_standard_articles
    from .fetch_gdelt_news import build_gdelt_url, load_company, normalize_gdelt_article, request_gdelt_json
    from .fetch_naver_news import collect_naver_articles
    from .normalize_news import normalize_gdelt_item
    from .score_news import assess_relevance
except ImportError:
    from cluster_news_events import PIPELINE_VERSION, build_public_event, cluster_event_articles, deduplicate_standard_articles
    from fetch_gdelt_news import build_gdelt_url, load_company, normalize_gdelt_article, request_gdelt_json
    from fetch_naver_news import collect_naver_articles
    from normalize_news import normalize_gdelt_item
    from score_news import assess_relevance


ROOT = Path(__file__).resolve().parents[1]
NEWS_PATH = ROOT / "data" / "news.json"
REPORT_PATH = ROOT / "data" / "news-report.json"
SEOUL = timezone(timedelta(hours=9))


def write_json_atomic(path, value):
    temporary = Path(path).with_suffix(Path(path).suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def collect_gdelt(company, start_at, end_at, request_fn=request_gdelt_json):
    payload, request_count = request_fn(build_gdelt_url(company, start_at, end_at))
    collected_at = datetime.now(SEOUL).isoformat()
    articles, rejected = [], Counter()
    for raw in payload.get("articles", []):
        legacy = normalize_gdelt_article(raw, company, collected_at)
        relevant, reason, _ = assess_relevance(legacy, company)
        if not relevant:
            rejected[reason] += 1
            continue
        articles.append(normalize_gdelt_item(legacy, company, collected_at))
    return articles, {"request_count": request_count, "raw_count": len(payload.get("articles", [])), "rejected": rejected, "errors": []}


def run_integrated_pipeline(company, start_at, end_at, news_path=NEWS_PATH, report_path=REPORT_PATH,
                            gdelt_collector=collect_gdelt, naver_collector=collect_naver_articles):
    executed_at = datetime.now(SEOUL).isoformat()
    errors = []
    try:
        gdelt_articles, gdelt_meta = gdelt_collector(company, start_at, end_at)
    except Exception as error:
        gdelt_articles, gdelt_meta = [], {"request_count": 0, "raw_count": 0, "rejected": Counter(), "errors": [{"provider": "gdelt", "type": type(error).__name__}]}
        errors.extend(gdelt_meta["errors"])
    try:
        naver_articles, naver_meta = naver_collector(company, start_at, end_at)
    except Exception as error:
        naver_articles, naver_meta = [], {"request_count": 0, "raw_count": 0, "credentials_status": "available", "errors": [{"provider": "naver", "type": type(error).__name__}]}
    errors.extend(naver_meta.get("errors", []))
    if not gdelt_articles and not naver_articles and errors:
        report = {"executed_at": executed_at, "errors": errors, "pipeline_version": PIPELINE_VERSION,
                  "credentials_status": naver_meta.get("credentials_status", "unknown")}
        write_json_atomic(report_path, report)
        return False, report

    candidates = [item for item in gdelt_articles + naver_articles if item.get("relevance_score", 0) >= 60]
    relevance_rejects = len(gdelt_articles) + len(naver_articles) - len(candidates)
    deduplicated, dedupe_meta = deduplicate_standard_articles(candidates)
    clusters = cluster_event_articles(deduplicated)
    public_events = [build_public_event(cluster, company, now=end_at) for cluster in clusters]
    public_events.sort(key=lambda item: (item["importance_score"], item["last_published_at"] or ""), reverse=True)
    levels = Counter(item["importance_level"] for item in public_events)
    report = {
        "executed_at": executed_at,
        "gdelt_request_count": gdelt_meta.get("request_count", 0), "naver_request_count": naver_meta.get("request_count", 0),
        "raw_gdelt_article_count": gdelt_meta.get("raw_count", 0), "raw_naver_article_count": naver_meta.get("raw_count", 0),
        "cross_provider_url_duplicate_count": dedupe_meta["cross_provider_url_duplicates"],
        "deduplicated_article_count": len(deduplicated), "event_cluster_count": len(public_events),
        "domestic_article_count": sum(item.get("region") == "domestic" for item in deduplicated),
        "international_article_count": sum(item.get("region") == "international" for item in deduplicated),
        "both_provider_cluster_count": sum(set(item["providers"]) == {"gdelt", "naver"} for item in public_events),
        "importance_counts": {key: levels.get(key, 0) for key in ("critical", "important", "watch", "low")},
        "relevance_reject_count": relevance_rejects + sum(gdelt_meta.get("rejected", {}).values()),
        "relevance_reject_reasons": dict(gdelt_meta.get("rejected", {})),
        "suspected_overmerge_count": sum(item["needs_review"] for item in public_events),
        "needs_review_count": sum(item["needs_review"] for item in public_events),
        "errors": errors, "credentials_status": naver_meta.get("credentials_status", "unknown"),
        "pipeline_version": PIPELINE_VERSION,
    }
    write_json_atomic(news_path, {"generated_at": executed_at, "news": public_events})
    write_json_atomic(report_path, report)
    return True, report


def main():
    parser = argparse.ArgumentParser(description="Build integrated GDELT and Naver event news data.")
    parser.add_argument("--stock-code", default="000660")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    company = load_company(args.stock_code)
    end_at = datetime.now(timezone.utc)
    success, report = run_integrated_pipeline(company, end_at - timedelta(days=args.days), end_at)
    print(f"GDELT articles: {report.get('raw_gdelt_article_count', 0)}")
    print(f"Naver articles: {report.get('raw_naver_article_count', 0)}")
    print(f"Event clusters: {report.get('event_cluster_count', 0)}")
    print(f"Naver status: {report.get('credentials_status', 'unknown')}")
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
