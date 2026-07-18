import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

try:
    from .backfill_company import (
        build_disclosure,
        disclosure_identity,
        load_credentials,
        public_quarter,
        to_seoul_iso,
    )
    from .news_batch_pipeline import read_json, write_json_atomic
    from .onboard_portfolio import build_public_indexes
    from .parse_awake_message import merge_quarter_records, parse_awake_message
    from .telegram_incremental import distribute_messages
except ImportError:
    from backfill_company import build_disclosure, disclosure_identity, load_credentials, public_quarter, to_seoul_iso
    from news_batch_pipeline import read_json, write_json_atomic
    from onboard_portfolio import build_public_indexes
    from parse_awake_message import merge_quarter_records, parse_awake_message
    from telegram_incremental import distribute_messages


ROOT = Path(__file__).resolve().parents[1]
CURSOR_PATH = ROOT / "data" / "state" / "telegram-cursor.json"
REPORT_PATH = ROOT / "data" / "telegram-portfolio-report.json"
CHANNEL_USERNAME = "darthacking"
SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")


async def fetch_messages_once(last_message_id, days=7, max_messages=5000):
    api_id, api_hash, session_string = load_credentials()
    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    messages = []
    channel_title = None
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise PermissionError("TelegramSessionUnauthorized")
        channel = await client.get_entity(CHANNEL_USERNAME)
        channel_title = getattr(channel, "title", None)
        kwargs = {"limit": max_messages}
        if last_message_id:
            kwargs["min_id"] = int(last_message_id)
        async for message in client.iter_messages(channel, **kwargs):
            if message.date and message.date.astimezone(timezone.utc) < cutoff and not last_message_id:
                break
            text = message.message or ""
            if text:
                messages.append({"id": message.id, "date": to_seoul_iso(message.date), "text": text})
    finally:
        await client.disconnect()
    return channel_title, messages


def merge_public_quarters(existing, new_records):
    by_period = {item.get("period"): item for item in existing if item.get("period")}
    for item in new_records:
        by_period[item.get("period")] = item
    return sorted(by_period.values(), key=lambda item: item.get("period") or "")[-8:]


def process_company(company, messages, generated_at, data_root=None):
    data_root = Path(data_root or ROOT / "data")
    parsed = []
    parse_failures = []
    for message in messages:
        result = parse_awake_message(
            message["text"], telegram_message_id=message["id"], message_datetime=message["date"],
            default_company_name=company["company_name"], default_stock_code=company["stock_code"],
        )
        parsed.append(result)
        if result.get("classification") == "unknown":
            parse_failures.append(message["id"])

    quarters, warnings = merge_quarter_records(parsed)
    new_quarters = [public_quarter(item) for item in quarters]
    earnings_path = data_root / "earnings" / "by-company" / f"{company['stock_code']}.json"
    earnings_payload = read_json(earnings_path, {}) or {}
    detail = earnings_payload.get("company", {})
    merged_quarters = merge_public_quarters(detail.get("earnings", []), new_quarters)
    if new_quarters:
        earnings_payload.update({"generatedAt": generated_at, "currencyUnit": "억원"})
        earnings_payload["company"] = {
            "name": company["company_name"], "code": company["stock_code"],
            "market": company.get("sector"), "earnings": merged_quarters, "news": [],
        }
        write_json_atomic(earnings_path, earnings_payload)

    disclosure_path = data_root / "disclosures" / "by-company" / f"{company['stock_code']}.json"
    disclosure_payload = read_json(disclosure_path, {}) or {}
    existing = list(disclosure_payload.get("disclosures", []))
    positions = {disclosure_identity(item): index for index, item in enumerate(existing)}
    new_disclosures = []
    for result in parsed:
        item = build_disclosure(result)
        if not item:
            continue
        identity = disclosure_identity(item)
        if identity in positions:
            existing[positions[identity]] = item
        else:
            positions[identity] = len(existing)
            existing.append(item)
            new_disclosures.append(item)
    existing.sort(key=lambda item: item.get("disclosedAt") or "", reverse=True)
    if new_disclosures:
        disclosure_payload.update({
            "generatedAt": generated_at, "companyName": company["company_name"],
            "stockCode": company["stock_code"], "status": "ok", "disclosures": existing[:100],
        })
        write_json_atomic(disclosure_path, disclosure_payload)
    return {
        "matched_messages": len(messages),
        "parsed_messages": len(parsed) - len(parse_failures),
        "parse_failure_count": len(parse_failures),
        "new_quarters": len(new_quarters),
        "new_disclosures": len(new_disclosures),
        "warning_count": len(warnings),
    }


async def run(data_root=None, force_full_refresh=False, progress_callback=None, raise_on_error=True):
    data_root = Path(data_root or ROOT / "data")
    cursor_path = data_root / "state" / "telegram-cursor.json"
    report_path = data_root / "telegram-portfolio-report.json"
    started = datetime.now(SEOUL)
    cursor = read_json(cursor_path, {}) or {}
    companies = read_json(data_root / "companies.json", {"companies": []}).get("companies", [])
    active = [
        item for item in companies
        if item.get("status") == "active"
        and item.get("validation_status") in {"verified", "corrected"}
        and item.get("disclosure_enabled", True)
    ]
    errors = []
    try:
        last_message_id = None if force_full_refresh else cursor.get("last_processed_message_id")
        channel_title, messages = await fetch_messages_once(last_message_id)
    except Exception as error:
        channel_title, messages = None, []
        errors.append({"type": type(error).__name__})

    distribution = distribute_messages(messages, active) if not errors else {item["stock_code"]: [] for item in active}
    generated_at = datetime.now(SEOUL).isoformat()
    company_results = {}
    if not errors:
        for company in active:
            try:
                company_results[company["stock_code"]] = process_company(
                    company, distribution.get(company["stock_code"], []), generated_at, data_root=data_root,
                )
            except Exception as error:
                errors.append({"stock_code": company["stock_code"], "type": type(error).__name__})

    cursor_updated = False
    if not errors:
        if messages:
            cursor["last_processed_message_id"] = max(item["id"] for item in messages)
            cursor_updated = True
        cursor.update({
            "version": "1.0.0", "channel_username": CHANNEL_USERNAME,
            "last_successful_run": generated_at, "last_error": None, "consecutive_failures": 0,
        })
        write_json_atomic(cursor_path, cursor)
        build_public_indexes(active, generated_at, data_root=data_root)
    else:
        cursor["last_error"] = errors[0]["type"]
        cursor["consecutive_failures"] = cursor.get("consecutive_failures", 0) + 1
        write_json_atomic(cursor_path, cursor)

    matched_ids = {message["id"] for items in distribution.values() for message in items}
    report = {
        "executed_at": generated_at,
        "channel_title": channel_title,
        "companies_considered": len(active),
        "messages_fetched": len(messages),
        "unique_matched_messages": len(matched_ids),
        "total_company_assignments": sum(item["matched_messages"] for item in company_results.values()),
        "companies_with_matches": sum(item["matched_messages"] > 0 for item in company_results.values()),
        "new_quarters": sum(item["new_quarters"] for item in company_results.values()),
        "new_disclosures": sum(item["new_disclosures"] for item in company_results.values()),
        "parse_failure_count": sum(item["parse_failure_count"] for item in company_results.values()),
        "company_results": company_results,
        "errors": errors,
        "cursor_updated": cursor_updated,
        "duration_seconds": round((datetime.now(SEOUL) - started).total_seconds(), 3),
    }
    write_json_atomic(report_path, report)
    if progress_callback:
        progress_callback(report)
    print(f"Messages fetched: {report['messages_fetched']}")
    print(f"Unique matched messages: {report['unique_matched_messages']}")
    print(f"Companies with matches: {report['companies_with_matches']}")
    print(f"Errors: {len(errors)}")
    if errors and raise_on_error:
        raise SystemExit(1)
    return report


if __name__ == "__main__":
    asyncio.run(run())
