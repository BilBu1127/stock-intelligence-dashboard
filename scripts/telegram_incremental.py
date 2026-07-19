import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")
URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
EMAIL_RE = re.compile(r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+82[- ]?10|010)[- ]\d{3,4}[- ]\d{4}(?!\d)")
CODE_RE = re.compile(r"(?<![A-Z0-9])A?((?=[A-Z0-9]{0,5}\d)[A-Z0-9]{6})(?![A-Z0-9])", re.IGNORECASE)
LABELED_CODE_RE = re.compile(
    r"(?im)^\s*(?:종목코드|종목\s*코드)\s*[:：]\s*A?((?=[A-Z0-9]{0,5}\d)[A-Z0-9]{6})(?![A-Z0-9])"
)
COMPANY_FIELD_RE = re.compile(r"(?im)^\s*(?:기업명|회사명|종목명)\s*[:：]\s*([^\n]+)")
BLOCKED_FALLBACK_LINE_RE = re.compile(
    r"계약\s*상대|거래\s*상대|원고(?:이름|명)?|피고(?:이름|명)?|비교기업|경쟁사|연구원|기관명"
)


def write_json_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def company_match_terms(company):
    return [
        company.get("company_name", ""),
        *company.get("aliases", []),
        *company.get("english_aliases", []),
        *company.get("previous_names", []),
    ]


def searchable_message_text(text):
    without_urls = URL_RE.sub(" ", text or "")
    without_email = EMAIL_RE.sub(" ", without_urls)
    return re.sub(r"[ \t]+", " ", without_email)


def normalize_code(value):
    match = CODE_RE.search(str(value or ""))
    return match.group(1).upper() if match else None


def _codes_from_urls(text):
    codes = []
    for match in URL_RE.finditer(text or ""):
        parsed = urlsplit(match.group(0).rstrip(".,;)]}"))
        for key, values in parse_qs(parsed.query).items():
            if key.casefold() not in {"code", "stock_code", "stockcode"}:
                continue
            codes.extend(code for value in values if (code := normalize_code(value)))
    return codes


def extract_message_code(text):
    text = text or ""
    labeled = [match.group(1).upper() for match in LABELED_CODE_RE.finditer(text)]
    company_lines = COMPANY_FIELD_RE.findall(text)
    company_field = [match.group(1).upper() for line in company_lines for match in CODE_RE.finditer(line)]
    url_query = _codes_from_urls(text)
    general = [match.group(1).upper() for match in CODE_RE.finditer(URL_RE.sub(" ", text))]
    for source, candidates in (
        ("labeled_stock_code", labeled),
        ("company_name_field", company_field),
        ("url_query_code", url_query),
        ("standalone_code", general),
    ):
        unique = list(dict.fromkeys(candidates))
        if len(unique) == 1:
            return {"code": unique[0], "source": source, "explicit": True, "ambiguous_codes": []}
        if len(unique) > 1:
            return {"code": None, "source": source, "explicit": True, "ambiguous_codes": unique}
    return {"code": None, "source": None, "explicit": False, "ambiguous_codes": []}


def alias_pattern(term):
    if re.search(r"[가-힣]", term):
        suffix = r"(?=$|[^가-힣A-Za-z0-9]|(?:은|는|이|가|와|과|을|를|의|도|에)(?=$|[^가-힣A-Za-z0-9]))"
    else:
        suffix = r"(?![가-힣A-Za-z0-9])"
    return re.compile(rf"(?<![가-힣A-Za-z0-9]){re.escape(term)}{suffix}", re.IGNORECASE)


def term_in_text(text, term):
    return bool(term and alias_pattern(term).search(text or ""))


def _company_field_matches(text, companies):
    matches = set()
    for field_value in COMPANY_FIELD_RE.findall(text or ""):
        for company in companies:
            if any(term_in_text(field_value, term) for term in company_match_terms(company) if term):
                matches.add(company["stock_code"])
    return matches


def _fallback_alias_matches(text, companies):
    safe_lines = [line for line in searchable_message_text(text).splitlines() if not BLOCKED_FALLBACK_LINE_RE.search(line)]
    safe_text = "\n".join(safe_lines)
    matches = set()
    for company in companies:
        if any(term_in_text(safe_text, term) for term in company_match_terms(company) if term):
            matches.add(company["stock_code"])
    return matches


def _sanitized_context(text, term=None):
    clean = PHONE_RE.sub("[PHONE]", EMAIL_RE.sub("[EMAIL]", URL_RE.sub("[URL]", text or "")))
    clean = re.sub(r"\s+", " ", clean).strip()
    if term:
        match = alias_pattern(term).search(clean)
        if match:
            clean = clean[max(0, match.start() - 30):match.end() + 30]
    return clean[:60]


def quarantine_record(message, parsed_code, attempted_target, reason, stage, context=None):
    return {
        "telegramMessageId": message.get("id"),
        "parsedCompanyCode": parsed_code,
        "attemptedTargetCode": attempted_target,
        "reason": reason,
        "parserStage": stage,
        "detectedAt": message.get("date") or datetime.now(SEOUL).isoformat(),
        "sanitizedMatchContext": _sanitized_context(context if context is not None else message.get("text", "")),
    }


def route_message(message, companies):
    text = message.get("text") or ""
    by_code = {str(company["stock_code"]): company for company in companies}
    code_result = extract_message_code(text)
    if code_result["ambiguous_codes"]:
        return [], [quarantine_record(message, None, None, "ambiguous_explicit_codes", "distribution")]
    if code_result["code"]:
        code = code_result["code"]
        if code in by_code:
            return [code], []
        return [], [quarantine_record(message, code, None, "code_not_in_portfolio", "distribution")]

    structured = _company_field_matches(searchable_message_text(text), companies)
    fallback = structured or _fallback_alias_matches(text, companies)
    requires_code = {company["stock_code"] for company in companies if company.get("telegram_match_requires_code")}
    blocked = fallback & requires_code
    permitted = fallback - requires_code
    quarantine = [
        quarantine_record(message, None, code, "target_requires_explicit_code", "distribution")
        for code in sorted(blocked)
    ]
    if len(permitted) == 1:
        return list(permitted), quarantine
    if len(permitted) > 1:
        quarantine.append(quarantine_record(message, None, None, "ambiguous_alias_match", "distribution"))
    return [], quarantine


def message_matches_company(message_text, company):
    assignments, _ = route_message({"id": None, "text": message_text}, [company])
    return company["stock_code"] in assignments


def distribute_messages_with_quarantine(messages, companies):
    distribution = {company["stock_code"]: [] for company in companies}
    quarantine = []
    for message in messages:
        assignments, blocked = route_message(message, companies)
        quarantine.extend(blocked)
        for code in assignments:
            distribution[code].append(message)
    return distribution, quarantine


def distribute_messages(messages, companies):
    distribution, _ = distribute_messages_with_quarantine(messages, companies)
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
    distribution, quarantine = distribute_messages_with_quarantine(messages, companies)
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
        return False, {"messages_fetched": len(messages), "failures": failures, "cursor_updated": False, "quarantine": quarantine}
    if messages:
        cursor["last_processed_message_id"] = max(item["id"] for item in messages)
    cursor["last_successful_run"] = datetime.now(SEOUL).isoformat()
    cursor["last_error"] = None
    cursor["consecutive_failures"] = 0
    write_json_atomic(cursor_path, cursor)
    return True, {"messages_fetched": len(messages), "failures": [], "cursor_updated": bool(messages), "quarantine": quarantine}
