import argparse
import json
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from .news_batch_pipeline import BatchNewsPipeline, MockNewsProvider, load_pipeline_config, write_json_atomic
except ImportError:
    from news_batch_pipeline import BatchNewsPipeline, MockNewsProvider, load_pipeline_config, write_json_atomic


ROOT = Path(__file__).resolve().parents[1]


def synthetic_companies(count):
    companies = []
    for index in range(count):
        code = f"{index + 1:06d}"
        tier = "core" if index < max(1, count // 10) else "watch" if index < max(2, count // 2) else "background"
        companies.append({
            "company_name": f"테스트기업{index + 1}", "stock_code": code,
            "aliases": [f"테스트기업{index + 1}"], "english_aliases": [f"Test Company {index + 1}"],
            "status": "active", "monitoring_tier": tier, "news_enabled": True,
            "disclosure_enabled": True, "earnings_enabled": True,
            "naver_query_budget": 3, "gdelt_query_budget": 1,
            "official_sources": [], "important_keywords": ["material"], "excluded_keywords": [],
        })
    return companies


def run_scenario(count, config):
    companies = synthetic_companies(count)
    fully_failed = companies[-1]["stock_code"]
    with tempfile.TemporaryDirectory() as directory:
        data_root = Path(directory) / "data"
        providers = {
            "naver": MockNewsProvider("naver", 2, fail_codes={fully_failed}),
            "gdelt": MockNewsProvider("gdelt", 1, fail_codes={fully_failed}),
        }
        pipeline = BatchNewsPipeline(data_root, config, providers)
        report = pipeline.run(companies, now=datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc))
        index = json.loads((data_root / "news" / "index.json").read_text(encoding="utf-8"))
        company_files = list((data_root / "news" / "by-company").glob("*.json"))
        durations = list(report["company_duration_seconds"].values())
        total_calls = sum(report["provider_api_calls"].values())
        result = {
            "company_count": count,
            "processed_companies": report["processed_companies"],
            "successful_company_count": len(report["successful_companies"]),
            "failed_company_count": len(report["failed_companies"]),
            "batch_count": len(report["batch_duration_seconds"]),
            "provider_api_calls": report["provider_api_calls"],
            "average_api_calls_per_company": round(total_calls / count, 4),
            "average_company_duration_seconds": round(statistics.mean(durations), 6) if durations else 0,
            "total_duration_seconds": report["total_duration_seconds"],
            "public_json_total_bytes": report["public_json_total_bytes"],
            "average_company_json_bytes": round(statistics.mean(report["company_json_bytes"].values()), 2),
            "peak_memory_bytes": report["peak_memory_bytes"],
            "company_file_count": len(company_files),
            "index_company_count": len(index.get("companies", [])),
            "index_event_count": len(index.get("news", [])),
            "index_contains_article_details": any("articles" in item for item in index.get("news", [])),
            "failed_company_preserved_pipeline": fully_failed in report["failed_companies"],
            "budget_respected": report["provider_api_calls"].get("naver", 0) <= min(count * 3, config["budgets"]["naver"]["per_run_hard_limit"])
                and report["provider_api_calls"].get("gdelt", 0) <= min(count, config["budgets"]["gdelt"]["per_run_hard_limit"]),
        }
        return result


def main():
    parser = argparse.ArgumentParser(description="Run mock-only news pipeline load tests.")
    parser.add_argument("--output", default=str(ROOT / "data" / "load-test-report.json"))
    args = parser.parse_args()
    config = load_pipeline_config()
    scenarios = [run_scenario(count, config) for count in (10, 50, 100, 200)]
    report = {
        "executed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider_mode": "mock_only",
        "actual_api_requests": 0,
        "scenarios": scenarios,
        "performance_targets": {
            "one_hundred_companies_completed": scenarios[2]["processed_companies"] == 100,
            "two_hundred_companies_completed": scenarios[3]["processed_companies"] == 200,
            "index_excludes_article_details": all(not item["index_contains_article_details"] for item in scenarios),
            "budgets_respected": all(item["budget_respected"] for item in scenarios),
            "partial_failures_isolated": all(item["failed_company_count"] == 1 for item in scenarios),
        },
    }
    write_json_atomic(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
