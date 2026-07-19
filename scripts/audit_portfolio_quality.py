import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .news_batch_pipeline import read_json, write_json_atomic
    from .onboard_portfolio import build_public_indexes
    from .score_news import assess_relevance
except ImportError:
    from news_batch_pipeline import read_json, write_json_atomic
    from onboard_portfolio import build_public_indexes
    from score_news import assess_relevance


ROOT = Path(__file__).resolve().parents[1]
SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")


def audit(companies, apply_changes=False):
    excluded = Counter()
    excluded_by_company = defaultdict(Counter)
    removed_cluster_ids = []
    remaining_urls = defaultdict(set)
    for company in companies:
        code = company["stock_code"]
        path = ROOT / "data" / "news" / "by-company" / f"{code}.json"
        payload = read_json(path, {}) or {}
        retained = []
        for event in payload.get("news", []):
            article = {
                "title": event.get("representative_title"),
                "url": event.get("representative_url"),
                "source_domain": event.get("representative_source"),
            }
            relevant, reason, _ = assess_relevance(article, company)
            if relevant:
                retained.append(event)
                if event.get("representative_url"):
                    remaining_urls[event["representative_url"]].add(code)
                continue
            excluded[reason] += 1
            excluded_by_company[code][reason] += 1
            removed_cluster_ids.append(event.get("cluster_id"))
        if apply_changes and len(retained) != len(payload.get("news", [])):
            payload["news"] = retained
            payload["quality_audited_at"] = datetime.now(SEOUL).isoformat()
            write_json_atomic(path, payload)
    cross_duplicates = [
        {"url": url, "stock_codes": sorted(codes)}
        for url, codes in remaining_urls.items() if len(codes) > 1
    ]
    return {
        "audited_at": datetime.now(SEOUL).isoformat(),
        "excluded_event_count": sum(excluded.values()),
        "exclusion_reasons": dict(excluded),
        "company_exclusion_reasons": {code: dict(reasons) for code, reasons in excluded_by_company.items()},
        "removed_cluster_ids": [cluster_id for cluster_id in removed_cluster_ids if cluster_id],
        "remaining_cross_company_duplicate_assignments": cross_duplicates,
    }


def main():
    companies = read_json(ROOT / "data" / "companies.json", {"companies": []}).get("companies", [])
    report_path = ROOT / "data" / "portfolio-quality-audit.json"
    previous = read_json(report_path, {}) or {}
    report = audit(companies, apply_changes=True)
    previous_ids = set(previous.get("removed_cluster_ids", []))
    new_ids = [item for item in report["removed_cluster_ids"] if item not in previous_ids]
    if new_ids:
        merged_reasons = Counter(previous.get("exclusion_reasons", {}))
        merged_reasons.update(report.get("exclusion_reasons", {}))
        report["exclusion_reasons"] = dict(merged_reasons)
        report["removed_cluster_ids"] = list(previous_ids) + new_ids
        report["excluded_event_count"] = len(report["removed_cluster_ids"])
        merged_company_reasons = defaultdict(Counter)
        for code, reasons in previous.get("company_exclusion_reasons", {}).items():
            merged_company_reasons[code].update(reasons)
        for code, reasons in report.get("company_exclusion_reasons", {}).items():
            merged_company_reasons[code].update(reasons)
        report["company_exclusion_reasons"] = {code: dict(reasons) for code, reasons in merged_company_reasons.items()}
    elif previous_ids:
        report["excluded_event_count"] = previous.get("excluded_event_count", len(previous_ids))
        report["exclusion_reasons"] = previous.get("exclusion_reasons", {})
        report["company_exclusion_reasons"] = previous.get("company_exclusion_reasons", {})
        report["removed_cluster_ids"] = list(previous_ids)
    write_json_atomic(report_path, report)
    build_public_indexes(companies, report["audited_at"])
    print(f"Excluded events: {report['excluded_event_count']}")
    print(f"Remaining cross-company duplicates: {len(report['remaining_cross_company_duplicate_assignments'])}")


if __name__ == "__main__":
    main()
