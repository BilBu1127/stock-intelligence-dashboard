import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


PARSER_VERSION = "1.0.0"
MONEY_TOKEN_RE = re.compile(
    r"N\s*/?\s*A|\(\s*\d[\d,]*(?:\.\d+)?\s*(?:조|억|백만|천)\s*원?\s*\)|"
    r"[+-]?\s*\d[\d,]*(?:\.\d+)?\s*(?:조|억|백만|천)\s*원?|(?<![\w\d])-(?=\s|[),/]|$)",
    re.IGNORECASE,
)
QUARTER_RE = re.compile(
    r"(?:(?P<year>20\d{2})\s*[.\-/ ]?\s*(?:Q\s*(?P<q1>[1-4])|(?P<q2>[1-4])\s*Q)|"
    r"(?P<q3>[1-4])\s*Q\s*(?P<short_year>\d{2}))",
    re.IGNORECASE,
)
DART_URL_RE = re.compile(r"https://dart\.fss\.or\.kr/[^\s<>)]+", re.IGNORECASE)
RECEIPT_RE = re.compile(r"(?:rcpNo=|접수번호\s*[:：]?\s*)(\d{14})", re.IGNORECASE)


def normalize_text(text):
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def parse_amount(raw_value):
    if raw_value is None:
        return None

    raw = str(raw_value).strip()
    compact = re.sub(r"\s+", "", raw).upper()
    if compact in {"-", "N/A", "NA", ""}:
        return {"raw": raw, "value_won": None}

    parenthesized = compact.startswith("(") and compact.endswith(")")
    if parenthesized:
        compact = compact[1:-1]
    match = re.fullmatch(r"([+-]?[\d,]+(?:\.\d+)?)(조|억|백만|천)원?", compact)
    if not match:
        return {"raw": raw, "value_won": None}

    try:
        number = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return {"raw": raw, "value_won": None}

    multipliers = {
        "조": Decimal("1000000000000"),
        "억": Decimal("100000000"),
        "백만": Decimal("1000000"),
        "천": Decimal("1000"),
    }
    if parenthesized:
        number = -abs(number)
    return {"raw": raw, "value_won": int(number * multipliers[match.group(2)])}


def find_amounts(text):
    return [parse_amount(match.group(0)) for match in MONEY_TOKEN_RE.finditer(text or "")]


def normalize_quarter(value):
    match = QUARTER_RE.search(value or "")
    if not match:
        return None
    quarter = match.group("q1") or match.group("q2") or match.group("q3")
    year = match.group("year") or f"20{match.group('short_year')}"
    return f"{year} Q{quarter}"


def quarter_index(quarter):
    normalized = normalize_quarter(quarter)
    if not normalized:
        return -1
    year, quarter_number = normalized.split(" Q")
    return int(year) * 4 + int(quarter_number) - 1


def classify_message(text):
    normalized = normalize_text(text)
    if re.search(r"정정(?:공시|보고서|신고서)?", normalized):
        return "correction"

    earnings_markers = [
        r"매출\s*액?",
        r"영업\s*(?:익|이익)",
        r"순\s*(?:익|이익)",
        r"최근\s*실적\s*추이",
        r"잠정\s*실적",
    ]
    marker_count = sum(bool(re.search(pattern, normalized)) for pattern in earnings_markers)
    if marker_count >= 2 or re.search(r"최근\s*실적\s*추이|잠정\s*실적", normalized):
        return "earnings"
    if re.search(r"공시|보고서|신고서|DART|dart\.fss\.or\.kr", normalized, re.IGNORECASE):
        return "disclosure"
    return "unknown"


def is_company_message(text, stock_code, company_name):
    normalized = normalize_text(text)
    code_pattern = re.compile(rf"(?<!\d)(?:A)?{re.escape(stock_code)}(?!\d)", re.IGNORECASE)
    if code_pattern.search(normalized):
        return True
    if company_name not in normalized:
        return False
    return bool(
        re.search(
            r"종목\s*코드|시가총액|공시|보고서|신고서|매출|영업(?:익|이익)|순(?:익|이익)|DART|dart\.fss\.or\.kr",
            normalized,
            re.IGNORECASE,
        )
    )


def extract_labeled_value(text, labels):
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?im)^\s*(?:{label_pattern})\s*[:：]\s*(.*?)\s*$",
        normalize_text(text),
    )
    return match.group(1).strip() if match else None


def extract_metric_values(text):
    metric_patterns = {
        "revenue": r"매출\s*액?",
        "operating_profit": r"영업\s*(?:익|이익)",
        "net_income": r"순\s*(?:익|이익)",
    }
    values = {}
    for key, pattern in metric_patterns.items():
        match = re.search(
            rf"(?im)^\s*{pattern}\s*[:：]?\s*(.*?)\s*$",
            normalize_text(text),
        )
        amounts = find_amounts(match.group(1)) if match else []
        values[f"{key}_actual"] = amounts[0] if amounts else None
        values[f"{key}_consensus"] = amounts[1] if len(amounts) > 1 else None
    return values


def extract_recent_earnings(text):
    rows = []
    seen = set()
    for line in normalize_text(text).splitlines():
        quarter_match = QUARTER_RE.search(line)
        if not quarter_match:
            continue
        fiscal_quarter = normalize_quarter(quarter_match.group(0))
        amounts = find_amounts(line[quarter_match.end():])
        if len(amounts) < 3 or fiscal_quarter in seen:
            continue
        seen.add(fiscal_quarter)
        rows.append(
            {
                "fiscal_quarter": fiscal_quarter,
                "revenue": amounts[0],
                "operating_profit": amounts[1],
                "net_income": amounts[2],
            }
        )
    return rows


def parse_datetime(value):
    if not value:
        return None
    cleaned = value.strip().replace(".", "-").replace("/", "-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    try:
        return datetime.fromisoformat(cleaned).isoformat()
    except ValueError:
        match = re.search(
            r"(20\d{2})[-년 ]\s*(\d{1,2})[-월 ]\s*(\d{1,2})(?:일)?(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?",
            value,
        )
        if not match:
            return None
        parts = [int(part) if part else 0 for part in match.groups()]
        return datetime(parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]).isoformat()


def infer_report_period(report_name, explicit_period):
    if explicit_period:
        return explicit_period.strip()
    match = re.search(r"\((20\d{2}[.\-/]\d{1,2})\)", report_name or "")
    return match.group(1) if match else None


def report_period_to_quarter(report_period):
    if not report_period:
        return None
    direct_quarter = normalize_quarter(report_period)
    if direct_quarter:
        return direct_quarter
    match = re.search(r"(20\d{2})[.\-/](\d{1,2})", report_period)
    if not match:
        return None
    month = int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return f"{match.group(1)} Q{((month - 1) // 3) + 1}"


def parse_provisional(text):
    match = re.search(r"잠정\s*실적\s*[:：]?\s*([YN])\b", text, re.IGNORECASE)
    if match:
        return match.group(1).upper() == "Y"
    if re.search(r"잠정\s*실적", text):
        return True
    return None


def extract_report_name(text, company_name):
    labeled = extract_labeled_value(text, ["보고서명", "공시명"])
    if labeled:
        return labeled
    for line in normalize_text(text).splitlines():
        if re.search(r"보고서|신고서|결정|계약|배당", line):
            cleaned = re.sub(rf"^\s*\[?{re.escape(company_name or '')}\]?\s*", "", line).strip()
            return cleaned or None
    return None


def parse_awake_message(text, telegram_message_id=None, message_datetime=None, default_company_name=None, default_stock_code=None):
    normalized = normalize_text(text)
    company_name = extract_labeled_value(normalized, ["기업명", "회사명", "종목명"])
    if not company_name:
        bracketed = re.search(r"^\s*\[([^\]]+)]", normalized)
        company_name = bracketed.group(1).strip() if bracketed else default_company_name
    if default_company_name and company_name and default_company_name in company_name:
        company_name = default_company_name

    stock_code = extract_labeled_value(normalized, ["종목코드", "종목 코드"])
    if stock_code:
        code_match = re.search(r"(?:A)?(\d{6})", stock_code, re.IGNORECASE)
        stock_code = code_match.group(1) if code_match else None
    if not stock_code:
        code_match = re.search(r"(?<!\d)(?:A)?(\d{6})(?!\d)", normalized, re.IGNORECASE)
        stock_code = code_match.group(1) if code_match else default_stock_code

    report_name = extract_report_name(normalized, company_name)
    report_period = infer_report_period(
        report_name,
        extract_labeled_value(normalized, ["보고기간", "보고서기간", "귀속기간", "실적기간"]),
    )
    disclosure_value = extract_labeled_value(normalized, ["공시 시각", "공시시각", "공시일시", "공시 일시"])
    disclosure_datetime = parse_datetime(disclosure_value) or message_datetime
    dart_match = DART_URL_RE.search(normalized)
    dart_url = dart_match.group(0).rstrip(".,") if dart_match else None
    receipt_match = RECEIPT_RE.search(normalized)
    dart_receipt_number = receipt_match.group(1) if receipt_match else None
    if not dart_receipt_number and dart_url:
        receipt_match = re.search(r"rcpNo=(\d{14})", dart_url, re.IGNORECASE)
        dart_receipt_number = receipt_match.group(1) if receipt_match else None

    result = {
        "classification": classify_message(normalized),
        "company_name": company_name,
        "stock_code": stock_code,
        "market_cap_text": extract_labeled_value(normalized, ["시가총액", "시총"]),
        "report_name": report_name,
        "report_period": report_period,
        "disclosure_datetime": disclosure_datetime,
        "provisional": parse_provisional(normalized),
        "dart_url": dart_url,
        "dart_receipt_number": dart_receipt_number,
        "telegram_message_id": telegram_message_id,
        "recent_earnings": extract_recent_earnings(normalized),
    }
    result.update(extract_metric_values(normalized))
    result["has_earnings_data"] = bool(
        result["recent_earnings"]
        or any(result[key] is not None for key in (
            "revenue_actual",
            "operating_profit_actual",
            "net_income_actual",
        ))
    )
    return result


def comparison_result(actual_won, comparison_won):
    if actual_won is None or comparison_won in (None, 0):
        return {"percentage": None, "status": None}
    if comparison_won < 0 < actual_won:
        return {"percentage": None, "status": "흑자전환"}
    if comparison_won > 0 > actual_won:
        return {"percentage": None, "status": "적자전환"}
    if comparison_won < 0 and actual_won < 0:
        status = "적자축소" if actual_won > comparison_won else "적자확대" if actual_won < comparison_won else "적자지속"
        return {"percentage": None, "status": status}
    percentage = (actual_won - comparison_won) / abs(comparison_won) * 100
    return {"percentage": percentage, "status": None}


def amount_value(amount):
    return amount.get("value_won") if isinstance(amount, dict) else None


def _candidate_from_row(parsed, row):
    return {
        "fiscal_quarter": row["fiscal_quarter"],
        "revenue": row.get("revenue"),
        "operating_profit": row.get("operating_profit"),
        "net_income": row.get("net_income"),
        "revenue_consensus": None,
        "operating_profit_consensus": None,
        "net_income_consensus": None,
        "provisional": parsed.get("provisional"),
        "correction": parsed.get("classification") == "correction",
        "disclosure_datetime": parsed.get("disclosure_datetime"),
        "telegram_message_id": parsed.get("telegram_message_id"),
        "report_name": parsed.get("report_name"),
        "dart_url": parsed.get("dart_url"),
        "dart_receipt_number": parsed.get("dart_receipt_number"),
    }


def _current_candidate(parsed):
    fiscal_quarter = report_period_to_quarter(parsed.get("report_period"))
    if not fiscal_quarter or not parsed.get("has_earnings_data"):
        return None
    return {
        "fiscal_quarter": fiscal_quarter,
        "revenue": parsed.get("revenue_actual"),
        "operating_profit": parsed.get("operating_profit_actual"),
        "net_income": parsed.get("net_income_actual"),
        "revenue_consensus": parsed.get("revenue_consensus"),
        "operating_profit_consensus": parsed.get("operating_profit_consensus"),
        "net_income_consensus": parsed.get("net_income_consensus"),
        "provisional": parsed.get("provisional"),
        "correction": parsed.get("classification") == "correction",
        "disclosure_datetime": parsed.get("disclosure_datetime"),
        "telegram_message_id": parsed.get("telegram_message_id"),
        "report_name": parsed.get("report_name"),
        "dart_url": parsed.get("dart_url"),
        "dart_receipt_number": parsed.get("dart_receipt_number"),
    }


def _candidate_values(candidate):
    return tuple(
        amount_value(candidate.get(key))
        for key in (
            "revenue",
            "operating_profit",
            "net_income",
            "revenue_consensus",
            "operating_profit_consensus",
            "net_income_consensus",
        )
    )


def merge_quarter_records(parsed_messages):
    grouped = {}
    for parsed in parsed_messages:
        candidates = [_candidate_from_row(parsed, row) for row in parsed.get("recent_earnings", [])]
        current = _current_candidate(parsed)
        if current:
            candidates.append(current)
        for candidate in candidates:
            grouped.setdefault(candidate["fiscal_quarter"], []).append(candidate)

    merged = []
    warnings = []
    for fiscal_quarter, candidates in grouped.items():
        candidates.sort(
            key=lambda item: (
                item.get("disclosure_datetime") or "",
                item.get("telegram_message_id") or 0,
            ),
            reverse=True,
        )

        unique_histories = []
        history_by_key = {}
        for candidate in candidates:
            history_key = (_candidate_values(candidate), candidate.get("provisional"), candidate.get("correction"))
            if history_key in history_by_key:
                message_id = candidate.get("telegram_message_id")
                if message_id is not None and message_id not in history_by_key[history_key]["telegram_message_ids"]:
                    history_by_key[history_key]["telegram_message_ids"].append(message_id)
                continue
            history = dict(candidate)
            history["telegram_message_ids"] = []
            if candidate.get("telegram_message_id") is not None:
                history["telegram_message_ids"].append(candidate["telegram_message_id"])
            history.pop("telegram_message_id", None)
            history_by_key[history_key] = history
            unique_histories.append(history)

        distinct_values = {_candidate_values(candidate) for candidate in candidates}
        if len(distinct_values) > 1:
            warnings.append(
                {
                    "type": "quarter_value_conflict",
                    "stock_code": parsed_messages[0].get("stock_code") if parsed_messages else None,
                    "fiscal_quarter": fiscal_quarter,
                    "message_ids": sorted(
                        {candidate.get("telegram_message_id") for candidate in candidates if candidate.get("telegram_message_id") is not None}
                    ),
                }
            )

        final_candidates = [candidate for candidate in candidates if candidate.get("provisional") is False]
        selected = final_candidates[0] if final_candidates else candidates[0]
        status = "final" if selected.get("provisional") is False else "provisional" if selected.get("provisional") is True else "latest_unverified"
        merged.append({**selected, "status": status, "source_history": unique_histories})

    merged.sort(key=lambda item: quarter_index(item["fiscal_quarter"]))
    return merged, warnings
