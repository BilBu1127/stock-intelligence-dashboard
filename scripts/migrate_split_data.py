import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .news_batch_pipeline import load_pipeline_config, public_event_summary, read_json, retain_public_events, write_json_atomic
    from .score_news import parse_datetime
except ImportError:
    from news_batch_pipeline import load_pipeline_config, public_event_summary, read_json, retain_public_events, write_json_atomic
    from score_news import parse_datetime


ROOT = Path(__file__).resolve().parents[1]
SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")


def migrate_news(data_root, companies, config, index_limit=3):
    legacy = read_json(Path(data_root) / "news.json", {"generated_at": None, "news": []}) or {"news": []}
    generated_at = legacy.get("generated_at") or datetime.now(SEOUL).isoformat()
    by_code = {}
    for event in legacy.get("news", []):
        by_code.setdefault(event.get("stock_code"), []).append(event)
    index_news, company_rows, retained_legacy = [], [], []
    retention_now = parse_datetime(generated_at) or datetime.now(timezone.utc)
    for company in companies:
        code = company["stock_code"]
        events = sorted(
            by_code.get(code, []),
            key=lambda item: parse_datetime(item.get("last_published_at") or item.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        events = retain_public_events(events, retention_now, config["retention"])
        retained_legacy.extend(events)
        payload = {
            "generated_at": generated_at,
            "company_name": company["company_name"],
            "stock_code": code,
            "status": "ok" if events else "not_collected",
            "last_successful_update": generated_at if events else None,
            "errors": [],
            "news": events,
        }
        write_json_atomic(Path(data_root) / "news" / "by-company" / f"{code}.json", payload)
        index_news.extend(public_event_summary(item) for item in events[:index_limit])
        company_rows.append({
            "company_name": company["company_name"], "stock_code": code,
            "monitoring_tier": company.get("monitoring_tier", "watch"), "event_count": len(events),
            "latest_event_at": events[0].get("last_published_at") if events else None,
            "last_successful_update": payload["last_successful_update"], "status": payload["status"],
        })
    write_json_atomic(Path(data_root) / "news" / "index.json", {
        "generated_at": generated_at, "companies": company_rows, "news": index_news,
    })
    write_json_atomic(Path(data_root) / "news.json", {"generated_at": generated_at, "news": retained_legacy})


def migrate_earnings(data_root):
    legacy = read_json(Path(data_root) / "earnings.json", {}) or {}
    generated_at = legacy.get("generatedAt")
    index_companies = []
    for company in legacy.get("companies", []):
        code = company.get("code")
        payload = {
            "generatedAt": generated_at, "currencyUnit": legacy.get("currencyUnit", "억원"),
            "company": company,
        }
        write_json_atomic(Path(data_root) / "earnings" / "by-company" / f"{code}.json", payload)
        summary_keys = (
            "period", "revenue", "operatingIncome", "netIncome",
            "estimateRevenue", "estimateOperatingIncome", "estimateNetIncome",
        )
        summary_earnings = [
            {key: quarter.get(key) for key in summary_keys}
            for quarter in company.get("earnings", [])[-8:]
        ]
        index_companies.append({
            "name": company.get("name"), "code": code, "market": company.get("market"),
            "hasDetails": bool(company.get("earnings")), "earnings": summary_earnings,
        })
    write_json_atomic(Path(data_root) / "earnings" / "index.json", {
        "generatedAt": generated_at, "currencyUnit": legacy.get("currencyUnit", "억원"),
        "watchlist": legacy.get("watchlist", []), "companies": index_companies,
    })


def migrate_disclosures(data_root, companies):
    legacy = read_json(Path(data_root) / "disclosures.json", {}) or {}
    generated_at = legacy.get("generatedAt")
    index_items, rows = [], []
    for company in companies:
        code = company["stock_code"]
        items = sorted(
            [item for item in legacy.get("disclosures", []) if item.get("code") == code],
            key=lambda item: item.get("disclosedAt") or "",
            reverse=True,
        )
        write_json_atomic(Path(data_root) / "disclosures" / "by-company" / f"{code}.json", {
            "generatedAt": generated_at, "companyName": company["company_name"],
            "stockCode": code, "categories": legacy.get("categories", []), "disclosures": items,
        })
        index_items.extend(items[:1])
        rows.append({
            "companyName": company["company_name"], "stockCode": code, "disclosureCount": len(items),
            "latestDisclosureAt": items[0].get("disclosedAt") if items else None,
        })
    write_json_atomic(Path(data_root) / "disclosures" / "index.json", {
        "generatedAt": generated_at, "categories": legacy.get("categories", []),
        "companies": rows, "disclosures": index_items,
    })


def migrate_all(root=ROOT):
    companies_data = read_json(Path(root) / "data" / "companies.json", {"companies": []})
    companies = companies_data.get("companies", [])
    data_root = Path(root) / "data"
    config = load_pipeline_config(Path(root) / "data" / "config" / "pipeline.json")
    migrate_news(data_root, companies, config, config["dashboard"]["index_event_limit_per_company"])
    migrate_earnings(data_root)
    migrate_disclosures(data_root, companies)


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy dashboard JSON into index and per-company files.")
    parser.parse_args()
    migrate_all()
    print("Split data migration completed")


if __name__ == "__main__":
    main()
