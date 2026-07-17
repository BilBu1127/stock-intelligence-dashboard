import argparse
import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

try:
    from .score_news import (
        PARSER_VERSION,
        assess_relevance,
        canonical_domain,
        cluster_articles,
        deduplicate_articles,
        match_company_alias,
        normalize_url,
        parse_datetime,
        public_cluster,
        source_type,
        valid_aliases,
    )
except ImportError:
    from score_news import (
        PARSER_VERSION,
        assess_relevance,
        canonical_domain,
        cluster_articles,
        deduplicate_articles,
        match_company_alias,
        normalize_url,
        parse_datetime,
        public_cluster,
        source_type,
        valid_aliases,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPANIES_PATH = PROJECT_ROOT / "data" / "companies.json"
NEWS_PATH = PROJECT_ROOT / "data" / "news.json"
NEWS_REPORT_PATH = PROJECT_ROOT / "data" / "news-report.json"
GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
SEOUL_TZ = timezone(timedelta(hours=9), "KST")


class GdeltRequestError(Exception):
    def __init__(self, error_type, attempts):
        super().__init__(error_type)
        self.error_type = error_type
        self.attempts = attempts


def read_json(path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path, value):
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def load_company(stock_code):
    data = read_json(COMPANIES_PATH, {"companies": []})
    company = next(
        (item for item in data.get("companies", []) if item.get("stock_code") == stock_code),
        None,
    )
    if company is None:
        raise KeyError("Company configuration was not found")
    return company


def build_query(company):
    aliases = valid_aliases(company)
    if not aliases:
        raise ValueError("No unambiguous company aliases are configured")
    return "(" + " OR ".join(f'\"{alias}\"' for alias in aliases) + ")"


def build_gdelt_url(company, start_at, end_at):
    params = {
        "query": build_query(company),
        "mode": "artlist",
        "maxrecords": "250",
        "format": "json",
        "sort": "datedesc",
        "startdatetime": start_at.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "enddatetime": end_at.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S"),
    }
    return f"{GDELT_ENDPOINT}?{urlencode(params)}"


def request_gdelt_json(url, timeout=30, retries=3):
    attempts = 0
    last_error_type = "UnknownError"
    for attempt in range(retries):
        attempts += 1
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "stock-intelligence-dashboard-local-prototype/1.0",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("articles", []), list):
                raise ValueError("Unexpected GDELT response structure")
            return payload, attempts
        except HTTPError as error:
            last_error_type = f"HTTP{error.code}"
            if error.code not in {429, 500, 502, 503, 504}:
                break
        except (URLError, TimeoutError) as error:
            last_error_type = type(error).__name__
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            last_error_type = type(error).__name__
            break
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    raise GdeltRequestError(last_error_type, attempts)


def article_domain(article):
    supplied = canonical_domain(article.get("domain"))
    if supplied:
        return supplied
    try:
        return canonical_domain(urlsplit(article.get("url") or "").netloc)
    except ValueError:
        return ""


def normalize_gdelt_article(article, company, collected_at):
    published = parse_datetime(article.get("seendate"))
    title = (article.get("title") or "").strip()
    domain = article_domain(article)
    return {
        "title": title,
        "url": normalize_url(article.get("url")),
        "source_domain": domain,
        "published_at": published.isoformat().replace("+00:00", "Z") if published else None,
        "language": article.get("language") or "Unknown",
        "matched_alias": match_company_alias(title, company),
        "company_name": company["company_name"],
        "stock_code": company["stock_code"],
        "source_type": source_type(domain, company),
        "collected_at": collected_at,
    }


def within_days(published_at, now, days):
    value = parse_datetime(published_at)
    if value is None:
        return False
    age = now - value
    return timedelta(0) <= age <= timedelta(days=days)


def build_report(
    executed_at,
    api_request_count,
    collected_count,
    relevant_count,
    deduplicated_count,
    clusters,
    excluded_reasons,
    errors,
):
    levels = Counter(item.get("importance_level") for item in clusters)
    return {
        "executed_at": executed_at,
        "api_request_count": api_request_count,
        "collected_article_count": collected_count,
        "company_relevant_article_count": relevant_count,
        "deduplicated_article_count": deduplicated_count,
        "cluster_count": len(clusters),
        "importance_counts": {
            "critical": levels.get("critical", 0),
            "important": levels.get("important", 0),
            "watch": levels.get("watch", 0),
            "low": levels.get("low", 0),
        },
        "excluded_article_count": sum(excluded_reasons.values()),
        "excluded_reason_counts": dict(sorted(excluded_reasons.items())),
        "errors": errors,
        "parser_version": PARSER_VERSION,
    }


def run_pipeline(
    company,
    start_at,
    end_at,
    news_path=NEWS_PATH,
    report_path=NEWS_REPORT_PATH,
    request_fn=request_gdelt_json,
):
    executed_at = datetime.now(SEOUL_TZ).isoformat()
    url = build_gdelt_url(company, start_at, end_at)
    try:
        payload, request_count = request_fn(url)
    except GdeltRequestError as error:
        report = build_report(
            executed_at,
            error.attempts,
            0,
            0,
            0,
            [],
            Counter(),
            [{"type": error.error_type}],
        )
        write_json_atomic(report_path, report)
        return False, report
    except Exception as error:
        report = build_report(
            executed_at,
            1,
            0,
            0,
            0,
            [],
            Counter(),
            [{"type": type(error).__name__}],
        )
        write_json_atomic(report_path, report)
        return False, report

    raw_articles = payload.get("articles", [])

    collected_at = executed_at
    relevant_articles = []
    excluded_reasons = Counter()
    for raw_article in raw_articles:
        article = normalize_gdelt_article(raw_article, company, collected_at)
        is_relevant, reason, matched_alias = assess_relevance(article, company)
        if not is_relevant:
            excluded_reasons[reason] += 1
            continue
        article["matched_alias"] = matched_alias
        relevant_articles.append(article)

    deduplicated, duplicate_count = deduplicate_articles(relevant_articles)
    if duplicate_count:
        excluded_reasons["exact_duplicate"] += duplicate_count
    clusters = cluster_articles(deduplicated, company)
    public_clusters = [public_cluster(cluster, company, now=end_at) for cluster in clusters]
    public_clusters.sort(
        key=lambda item: (item["importance_score"], item.get("published_at") or ""),
        reverse=True,
    )

    existing = read_json(news_path, {"generated_at": None, "news": []}) or {"news": []}
    retained = [
        item
        for item in existing.get("news", [])
        if item.get("stock_code") != company["stock_code"]
        and within_days(item.get("published_at"), end_at, 30)
    ]
    current = [item for item in public_clusters if within_days(item.get("published_at"), end_at, 30)]
    news_data = {
        "generated_at": executed_at,
        "news": sorted(
            retained + current,
            key=lambda item: item.get("published_at") or "",
            reverse=True,
        ),
    }
    report = build_report(
        executed_at,
        request_count,
        len(raw_articles),
        len(relevant_articles),
        len(deduplicated),
        public_clusters,
        excluded_reasons,
        [],
    )
    write_json_atomic(news_path, news_data)
    write_json_atomic(report_path, report)
    return True, report


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch and score recent GDELT news for one configured company.")
    parser.add_argument("--stock-code", default="000660")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.days <= 30:
        parser.error("--days must be between 1 and 30")
    return args


def main():
    args = parse_args()
    company = load_company(args.stock_code)
    end_at = datetime.now(timezone.utc)
    start_at = end_at - timedelta(days=args.days)
    success, report = run_pipeline(company, start_at, end_at)
    print(f"Collected article count: {report['collected_article_count']}")
    print(f"Relevant article count: {report['company_relevant_article_count']}")
    print(f"Cluster count: {report['cluster_count']}")
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
