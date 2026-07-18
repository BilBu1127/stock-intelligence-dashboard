import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

try:
    from .credentials import load_values, missing_names
    from .parse_awake_message import (
        PARSER_VERSION,
        comparison_result,
        is_company_message,
        merge_quarter_records,
        parse_awake_message,
    )
except ImportError:
    from credentials import load_values, missing_names
    from parse_awake_message import (
        PARSER_VERSION,
        comparison_result,
        is_company_message,
        merge_quarter_records,
        parse_awake_message,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRETS_ENV_PATH = PROJECT_ROOT / ".secrets" / "telegram.env"
SESSION_PATH = PROJECT_ROOT / ".secrets" / "telegram_session.txt"
EARNINGS_PATH = PROJECT_ROOT / "data" / "earnings.json"
DISCLOSURES_PATH = PROJECT_ROOT / "data" / "disclosures.json"
PARSE_REPORT_PATH = PROJECT_ROOT / "data" / "parse-report.json"
PRIVATE_ROOT = PROJECT_ROOT / "private_samples"
CHANNEL_USERNAME = "darthacking"
SEOUL_TZ = timezone(timedelta(hours=9), "KST")


def load_environment(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_credentials():
    values = load_values(
        ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION"),
        fallback_path=SECRETS_ENV_PATH, session_path=SESSION_PATH,
    )
    missing = missing_names(values)
    if missing:
        raise FileNotFoundError("MissingCredentialVariables:" + ",".join(missing))
    api_id = int(values["TELEGRAM_API_ID"])
    api_hash = values["TELEGRAM_API_HASH"]
    session_string = values["TELEGRAM_SESSION"]
    return api_id, api_hash, session_string


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path, value):
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def to_seoul_iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SEOUL_TZ).isoformat()


def won_to_eok(value):
    if value is None:
        return None
    quotient, remainder = divmod(value, 100_000_000)
    return quotient if remainder == 0 else value / 100_000_000


def amount_won(amount):
    return amount.get("value_won") if isinstance(amount, dict) else None


def public_amount(amount):
    if not isinstance(amount, dict):
        return None
    return {"raw": amount.get("raw"), "valueWon": amount.get("value_won")}


def public_history(history):
    return {
        "telegramMessageIds": history.get("telegram_message_ids", []),
        "disclosureDatetime": history.get("disclosure_datetime"),
        "provisional": history.get("provisional"),
        "correction": history.get("correction", False),
        "reportName": history.get("report_name"),
        "dartUrl": history.get("dart_url"),
        "dartReceiptNumber": history.get("dart_receipt_number"),
        "amounts": {
            "revenue": public_amount(history.get("revenue")),
            "operatingIncome": public_amount(history.get("operating_profit")),
            "netIncome": public_amount(history.get("net_income")),
            "estimateRevenue": public_amount(history.get("revenue_consensus")),
            "estimateOperatingIncome": public_amount(history.get("operating_profit_consensus")),
            "estimateNetIncome": public_amount(history.get("net_income_consensus")),
        },
    }


def public_quarter(record):
    revenue = amount_won(record.get("revenue"))
    operating_profit = amount_won(record.get("operating_profit"))
    net_income = amount_won(record.get("net_income"))
    revenue_consensus = amount_won(record.get("revenue_consensus"))
    operating_consensus = amount_won(record.get("operating_profit_consensus"))
    net_consensus = amount_won(record.get("net_income_consensus"))
    return {
        "period": record["fiscal_quarter"],
        "revenue": won_to_eok(revenue),
        "operatingIncome": won_to_eok(operating_profit),
        "netIncome": won_to_eok(net_income),
        "estimateRevenue": won_to_eok(revenue_consensus),
        "estimateOperatingIncome": won_to_eok(operating_consensus),
        "estimateNetIncome": won_to_eok(net_consensus),
        "sourceStatus": record.get("status"),
        "telegramMessageId": record.get("telegram_message_id"),
        "disclosureDatetime": record.get("disclosure_datetime"),
        "provisional": record.get("provisional"),
        "dartUrl": record.get("dart_url"),
        "dartReceiptNumber": record.get("dart_receipt_number"),
        "estimateComparison": {
            "revenue": comparison_result(revenue, revenue_consensus),
            "operatingIncome": comparison_result(operating_profit, operating_consensus),
            "netIncome": comparison_result(net_income, net_consensus),
        },
        "sourceAmounts": {
            "revenue": public_amount(record.get("revenue")),
            "operatingIncome": public_amount(record.get("operating_profit")),
            "netIncome": public_amount(record.get("net_income")),
            "estimateRevenue": public_amount(record.get("revenue_consensus")),
            "estimateOperatingIncome": public_amount(record.get("operating_profit_consensus")),
            "estimateNetIncome": public_amount(record.get("net_income_consensus")),
        },
        "sourceHistory": [public_history(item) for item in record.get("source_history", [])],
    }


def disclosure_category(report_name):
    value = report_name or ""
    if "시설" in value or "투자" in value:
        return "시설투자"
    if "공급" in value or "계약" in value:
        return "공급계약"
    if any(token in value for token in ("자사주", "배당", "자기주식")):
        return "자사주·배당"
    if any(token in value for token in ("증자", "사채", "전환사채", "신주")):
        return "증자·사채"
    if any(token in value for token in ("지분", "주식등의대량보유", "임원ㆍ주요주주")):
        return "지분"
    return "기타"


def build_disclosure(parsed):
    report_name = parsed.get("report_name")
    if not report_name or not parsed.get("disclosure_datetime"):
        return None
    return {
        "disclosedAt": parsed["disclosure_datetime"],
        "companyName": parsed.get("company_name") or "동원금속",
        "code": parsed.get("stock_code") or "018500",
        "reportName": report_name,
        "category": disclosure_category(report_name),
        "provisionalEarnings": False,
        "summary": f"{report_name} 관련 공시.",
        "dartUrl": parsed.get("dart_url"),
        "dartReceiptNumber": parsed.get("dart_receipt_number"),
        "telegramMessageId": parsed.get("telegram_message_id"),
    }


def update_earnings_file(company_name, stock_code, quarters, generated_at):
    data = read_json(EARNINGS_PATH)
    company = next((item for item in data.get("companies", []) if item.get("code") == stock_code), None)
    if company is None:
        raise KeyError("Target company is not present in earnings.json")
    if quarters:
        company["name"] = company_name
        company["earnings"] = [public_quarter(item) for item in quarters[-8:]]
        data["generatedAt"] = generated_at
        write_json_atomic(EARNINGS_PATH, data)


def disclosure_identity(item):
    return (
        item.get("dartReceiptNumber")
        or item.get("telegramMessageId")
        or (item.get("code"), item.get("disclosedAt"), item.get("reportName"))
    )


def update_disclosures_file(stock_code, parsed_messages, generated_at):
    data = read_json(DISCLOSURES_PATH)
    parsed_general = []
    for parsed in parsed_messages:
        if parsed.get("has_earnings_data") or parsed.get("classification") == "unknown":
            continue
        item = build_disclosure(parsed)
        if item:
            parsed_general.append(item)
    parsed_general.sort(key=lambda item: item["disclosedAt"], reverse=True)
    parsed_general = parsed_general[:30]

    existing = list(data.get("disclosures", []))
    existing_positions = {disclosure_identity(item): index for index, item in enumerate(existing)}
    for item in parsed_general:
        identity = disclosure_identity(item)
        if identity in existing_positions:
            existing[existing_positions[identity]] = item
        else:
            existing_positions[identity] = len(existing)
            existing.append(item)
    existing.sort(key=lambda item: item.get("disclosedAt") or "", reverse=True)
    data["disclosures"] = existing
    if parsed_general:
        data["generatedAt"] = generated_at
    write_json_atomic(DISCLOSURES_PATH, data)
    return len(parsed_general)


def validate_public_quarters(quarters):
    warnings = []
    checked = 0
    for quarter in quarters:
        for key in ("revenue", "operating_profit", "net_income"):
            amount = quarter.get(key)
            if not isinstance(amount, dict) or amount.get("value_won") is None:
                continue
            checked += 1
            raw = amount.get("raw") or ""
            if not raw:
                warnings.append(
                    {"type": "missing_raw_amount", "fiscal_quarter": quarter["fiscal_quarter"], "field": key}
                )
            if checked >= 3:
                return warnings
    if checked < 3:
        warnings.append({"type": "insufficient_amount_samples", "checked": checked})
    return warnings


async def collect_messages(stock_code, company_name, max_messages):
    api_id, api_hash, session_string = load_credentials()
    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    searched_count = 0
    related = []
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise PermissionError("The local Telegram session is not authorized")
        channel = await client.get_entity(CHANNEL_USERNAME)
        async for message in client.iter_messages(channel, limit=max_messages):
            searched_count += 1
            text = message.message or ""
            if not text or not is_company_message(text, stock_code, company_name):
                continue
            related.append(
                {
                    "message_id": message.id,
                    "datetime": to_seoul_iso(message.date),
                    "text": text,
                }
            )
    finally:
        await client.disconnect()
    return searched_count, related


def save_private_samples(stock_code, messages):
    target = PRIVATE_ROOT / stock_code
    target.mkdir(parents=True, exist_ok=True)
    for message in messages:
        (target / f"{message['message_id']}.txt").write_text(message["text"], encoding="utf-8")


def build_report(searched_count, related_messages, parsed_messages, quarters, warnings, failed_ids, general_count):
    earnings_count = sum(item.get("has_earnings_data", False) for item in parsed_messages)
    unknown_count = sum(item.get("classification") == "unknown" for item in parsed_messages)
    return {
        "executedAt": datetime.now(SEOUL_TZ).isoformat(),
        "searchedTelegramMessageCount": searched_count,
        "relatedCompanyMessageCount": len(related_messages),
        "earningsMessageCount": earnings_count,
        "generalDisclosureCount": general_count,
        "unknownMessageCount": unknown_count,
        "uniqueQuarterCount": len(quarters),
        "quarters": [item["fiscal_quarter"] for item in quarters],
        "warnings": warnings,
        "failedMessageIds": sorted(set(failed_ids)),
        "parserVersion": PARSER_VERSION,
    }


async def run(args):
    searched_count, related_messages = await collect_messages(
        args.stock_code,
        args.company_name,
        args.max_messages,
    )
    save_private_samples(args.stock_code, related_messages)

    parsed_messages = []
    failed_ids = []
    for message in related_messages:
        parsed = parse_awake_message(
            message["text"],
            telegram_message_id=message["message_id"],
            message_datetime=message["datetime"],
            default_company_name=args.company_name,
            default_stock_code=args.stock_code,
        )
        parsed_messages.append(parsed)
        if parsed["classification"] == "unknown" or (
            parsed["classification"] == "earnings" and not parsed["has_earnings_data"]
        ):
            failed_ids.append(message["message_id"])

    quarters, warnings = merge_quarter_records(parsed_messages)
    warnings.extend(validate_public_quarters(quarters))
    generated_at = datetime.now(SEOUL_TZ).isoformat()
    update_earnings_file(args.company_name, args.stock_code, quarters, generated_at)
    general_count = update_disclosures_file(args.stock_code, parsed_messages, generated_at)
    report = build_report(
        searched_count,
        related_messages,
        parsed_messages,
        quarters,
        warnings,
        failed_ids,
        general_count,
    )
    write_json_atomic(PARSE_REPORT_PATH, report)

    print(f"Searched message count: {searched_count}")
    print(f"Earnings message count: {report['earningsMessageCount']}")


def parse_args():
    parser = argparse.ArgumentParser(description="Backfill one company from the local Telegram session.")
    parser.add_argument("--stock-code", required=True)
    parser.add_argument("--company-name", required=True)
    parser.add_argument("--max-messages", type=int, default=5000)
    args = parser.parse_args()
    if not 1 <= args.max_messages <= 5000:
        parser.error("--max-messages must be between 1 and 5000")
    return args


if __name__ == "__main__":
    try:
        asyncio.run(run(parse_args()))
    except Exception as error:
        print(f"Backfill failed ({type(error).__name__}).")
        raise SystemExit(1)
