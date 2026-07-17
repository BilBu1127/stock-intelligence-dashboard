import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")


def write_json_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def company_match_terms(company):
    return [
        company.get("stock_code", ""),
        company.get("company_name", ""),
        *company.get("aliases", []),
        *company.get("english_aliases", []),
    ]


def distribute_messages(messages, companies):
    distribution = {company["stock_code"]: [] for company in companies}
    for message in messages:
        text = (message.get("text") or "").casefold()
        for company in companies:
            terms = [term.casefold() for term in company_match_terms(company) if term]
            if any(term in text for term in terms):
                distribution[company["stock_code"]].append(message)
    return distribution


def run_incremental(fetch_messages, process_company_messages, companies, cursor_path):
    cursor_path = Path(cursor_path)
    if cursor_path.is_file():
        cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
    else:
        cursor = {
            "version": "1.0.0", "channel_username": "darthacking",
            "last_processed_message_id": None, "last_successful_run": None,
            "last_error": None, "consecutive_failures": 0,
        }
    last_id = cursor.get("last_processed_message_id")
    messages = list(fetch_messages(last_id))
    messages.sort(key=lambda item: item.get("id", 0))
    distribution = distribute_messages(messages, companies)
    failures = []
    for company in companies:
        related = distribution.get(company["stock_code"], [])
        if not related:
            continue
        try:
            process_company_messages(company, related)
        except Exception as error:
            failures.append({"stock_code": company["stock_code"], "type": type(error).__name__})
    if failures:
        cursor["last_error"] = "PartialCompanyFailure"
        cursor["consecutive_failures"] = cursor.get("consecutive_failures", 0) + 1
        write_json_atomic(cursor_path, cursor)
        return False, {"messages_fetched": len(messages), "failures": failures, "cursor_updated": False}
    if messages:
        cursor["last_processed_message_id"] = max(item["id"] for item in messages)
    cursor["last_successful_run"] = datetime.now(SEOUL).isoformat()
    cursor["last_error"] = None
    cursor["consecutive_failures"] = 0
    write_json_atomic(cursor_path, cursor)
    return True, {"messages_fetched": len(messages), "failures": [], "cursor_updated": bool(messages)}
