"""External-provider validation that writes only under a supplied temporary directory."""

import argparse
import asyncio
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from .backfill_portfolio_telegram import fetch_messages_once
    from .incremental_provider_adapters import GdeltIncrementalProvider, NaverIncrementalProvider
    from .news_batch_pipeline import BatchNewsPipeline, load_pipeline_config
    from .parse_awake_message import parse_awake_message
    from .telegram_incremental import distribute_messages
except ImportError:
    from backfill_portfolio_telegram import fetch_messages_once
    from incremental_provider_adapters import GdeltIncrementalProvider, NaverIncrementalProvider
    from news_batch_pipeline import BatchNewsPipeline, load_pipeline_config
    from parse_awake_message import parse_awake_message
    from telegram_incremental import distribute_messages


ROOT = Path(__file__).resolve().parents[1]


async def validate_telegram(companies):
    cursor_path = ROOT / "data" / "state" / "telegram-cursor.json"
    cursor = json.loads(cursor_path.read_text(encoding="utf-8")) if cursor_path.is_file() else {}
    title, messages = await fetch_messages_once(cursor.get("last_processed_message_id"), max_messages=5000)
    distribution = distribute_messages(messages, companies)
    parsed = 0
    for company in companies:
        for message in distribution[company["stock_code"]]:
            result = parse_awake_message(message.get("text") or "", default_company_name=company["company_name"], default_stock_code=company["stock_code"])
            parsed += int(result.get("classification") != "unknown")
    return {
        "status": "ok", "channel_title": title, "messages_fetched": len(messages),
        "matched_messages": len({item["id"] for rows in distribution.values() for item in rows}),
        "parsed_messages": parsed, "cursor_updated": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Validate external sources without changing repository data.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    companies = json.loads((ROOT / "data" / "companies.json").read_text(encoding="utf-8"))["companies"]
    active = [item for item in companies if item.get("status") == "active" and item.get("news_enabled", True)]
    with tempfile.TemporaryDirectory(prefix="portfolio-validation-") as directory:
        temp_data = Path(directory) / "data"
        shutil.copytree(ROOT / "data", temp_data)
        config = load_pipeline_config()
        providers = {
            "naver": NaverIncrementalProvider(),
            "gdelt": GdeltIncrementalProvider(config["budgets"]["gdelt"]["request_delay_seconds"]),
        }
        news = BatchNewsPipeline(temp_data, config, providers).run(active, now=datetime.now(timezone.utc))
        telegram = asyncio.run(validate_telegram(active))
        public_files = len(list(temp_data.rglob("*.json")))
        public_output = args.output.parent / "public-json"
        for name in ("news", "earnings", "disclosures"):
            source = temp_data / name
            if source.exists():
                shutil.copytree(source, public_output / name, dirs_exist_ok=True)
    report = {
        "mode": "temporary_validation_only", "news": {
            "provider_api_calls": news.get("provider_api_calls", {}),
            "successful_companies": len(news.get("successful_companies", [])),
            "failed_companies": len(news.get("failed_companies", [])),
            "raw_articles": news.get("raw_article_count", 0),
            "new_event_clusters": news.get("new_event_cluster_count", 0),
        },
        "telegram": telegram, "temporary_public_json_files": public_files,
        "public_json_artifact": "public-json",
        "cursor_updated": False, "repository_writes": False,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("External validation completed")


if __name__ == "__main__":
    main()
