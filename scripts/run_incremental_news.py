import argparse
from datetime import datetime, timezone
from pathlib import Path

try:
    from .incremental_provider_adapters import GdeltIncrementalProvider, NaverIncrementalProvider
    from .news_batch_pipeline import BatchNewsPipeline, load_pipeline_config, read_json
except ImportError:
    from incremental_provider_adapters import GdeltIncrementalProvider, NaverIncrementalProvider
    from news_batch_pipeline import BatchNewsPipeline, load_pipeline_config, read_json


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="Run the incremental multi-company news pipeline.")
    parser.add_argument("--backfill", action="store_true", help="Use the configured seven-day initial window.")
    args = parser.parse_args()
    config = load_pipeline_config()
    companies = read_json(ROOT / "data" / "companies.json", {"companies": []}).get("companies", [])
    providers = {
        "naver": NaverIncrementalProvider(),
        "gdelt": GdeltIncrementalProvider(config["budgets"]["gdelt"]["request_delay_seconds"]),
    }
    def show_progress(item):
        print(
            f"Batch {item['batch']} complete: "
            f"{item['processed_total']}/{item['active_total']} companies",
            flush=True,
        )

    report = BatchNewsPipeline(ROOT / "data", config, providers, progress_callback=show_progress).run(
        companies, now=datetime.now(timezone.utc), backfill=args.backfill,
    )
    print(f"Processed companies: {report['processed_companies']}")
    print(f"Failed companies: {len(report['failed_companies'])}")
    print(f"Naver calls: {report['provider_api_calls'].get('naver', 0)}")
    print(f"GDELT calls: {report['provider_api_calls'].get('gdelt', 0)}")
    if report["severe_failure"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
