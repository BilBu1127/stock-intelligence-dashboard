"""Repair the verified Telegram cross-company contamination without external calls."""

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")
BASELINE_REF = "0be967f"
NAVER_CODE = "035420"
NAVER_VALID_MESSAGE_ID = 146984
HIDDEN_ALPHANUMERIC_MISMATCH = {
    "telegramMessageId": 146943,
    "parsedCompanyCode": "0009K0",
    "attemptedTargetCode": NAVER_CODE,
    "reason": "parsed_code_target_mismatch",
    "parserStage": "historical_recovery",
    "sanitizedMatchContext": "alphanumeric stock code detected in company metadata",
}
ADDITIONAL_DUPLICATE_ASSIGNMENTS = {
    146805: {"005380", "005930", "126340"},
    146971: {"000660", "010120", "119850", "356860"},
    147068: {"047810", "278470", "375500"},
}
URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+82[- ]?10|010)[- ]\d{3,4}[- ]\d{4}(?!\d)")


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def write_json_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".repair.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_git_json(reference, relative_path, repository_root=ROOT):
    result = subprocess.run(
        ["git", "show", f"{reference}:{Path(relative_path).as_posix()}"],
        cwd=repository_root, check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


def sanitized_context(value):
    clean = URL_RE.sub("[URL]", str(value or ""))
    clean = EMAIL_RE.sub("[EMAIL]", clean)
    clean = PHONE_RE.sub("[PHONE]", clean)
    return re.sub(r"\s+", " ", clean).strip()[:60]


def build_quarantine(audit_payload, detected_at):
    records = []
    for item in audit_payload.get("mismatchDetails", []):
        records.append({
            "telegramMessageId": item.get("telegramMessageId"),
            "parsedCompanyCode": item.get("parsedActualStockCode"),
            "attemptedTargetCode": item.get("wrongTargetCode"),
            "reason": "historical_cross_company_assignment",
            "parserStage": "historical_recovery",
            "detectedAt": detected_at,
            "sanitizedMatchContext": sanitized_context(item.get("sanitizedContext")),
        })
    hidden = dict(HIDDEN_ALPHANUMERIC_MISMATCH, detectedAt=detected_at)
    records.append(hidden)
    for message_id, target_codes in ADDITIONAL_DUPLICATE_ASSIGNMENTS.items():
        for target_code in target_codes:
            records.append({
                "telegramMessageId": message_id,
                "parsedCompanyCode": None,
                "attemptedTargetCode": target_code,
                "reason": "historical_cross_company_duplicate",
                "parserStage": "integrity_recovery",
                "detectedAt": detected_at,
                "sanitizedMatchContext": "issuer in report metadata differs from assigned company",
            })
    unique = {(item["telegramMessageId"], item["attemptedTargetCode"]): item for item in records}
    return sorted(unique.values(), key=lambda item: (item["telegramMessageId"], item["attemptedTargetCode"]))


def rebuild_indexes(data_root, companies, generated_at):
    active = [item for item in companies if item.get("status") == "active"]
    earnings_index = read_json(data_root / "earnings" / "index.json", {}) or {}
    disclosure_index = read_json(data_root / "disclosures" / "index.json", {}) or {}
    watchlist = []
    earnings_companies = []
    disclosure_companies = []
    disclosures = []
    for company in active:
        code = company["stock_code"]
        common = {
            "category": company["category"],
            "monitoringTier": company["monitoring_tier"],
            "validationStatus": company["validation_status"],
        }
        watchlist.append({"name": company["company_name"], "code": code, "market": company.get("sector"), **common})
        earnings_payload = read_json(data_root / "earnings" / "by-company" / f"{code}.json", {}) or {}
        detail = earnings_payload.get("company", earnings_payload)
        earnings_companies.append({
            "name": company["company_name"], "code": code, "market": company.get("sector"),
            "hasDetails": bool(detail.get("earnings")), "earnings": detail.get("earnings", []), **common,
        })
        disclosure_payload = read_json(data_root / "disclosures" / "by-company" / f"{code}.json", {}) or {}
        company_disclosures = disclosure_payload.get("disclosures", [])
        disclosures.extend(company_disclosures)
        disclosure_companies.append({
            "companyName": company["company_name"], "stockCode": code,
            "disclosureCount": len(company_disclosures),
            "latestDisclosureAt": company_disclosures[0].get("disclosedAt") if company_disclosures else None,
            "category": company["category"], "monitoringTier": company["monitoring_tier"],
        })
    disclosures.sort(key=lambda item: item.get("disclosedAt") or "", reverse=True)
    write_json_atomic(data_root / "earnings" / "index.json", {
        "generatedAt": generated_at,
        "currencyUnit": earnings_index.get("currencyUnit", "억원"),
        "watchlist": watchlist,
        "companies": earnings_companies,
    })
    write_json_atomic(data_root / "disclosures" / "index.json", {
        "generatedAt": generated_at,
        "categories": disclosure_index.get("categories", []),
        "companies": disclosure_companies,
        "disclosures": disclosures,
    })


def repair(data_root, audit_path, quarantine_path, baseline_ref=BASELINE_REF, repository_root=ROOT):
    data_root = Path(data_root)
    audit = read_json(audit_path, {}) or {}
    mismatch_details = audit.get("mismatchDetails", [])
    if len(mismatch_details) != 102:
        raise ValueError("Expected102SanitizedMismatchRecords")
    generated_at = datetime.now(SEOUL).isoformat()
    cursor_path = data_root / "state" / "telegram-cursor.json"
    cursor_before = cursor_path.read_bytes()

    removals = {}
    for item in mismatch_details:
        removals.setdefault(str(item["wrongTargetCode"]), set()).add(item["telegramMessageId"])
    removals.setdefault(NAVER_CODE, set()).add(HIDDEN_ALPHANUMERIC_MISMATCH["telegramMessageId"])
    for message_id, target_codes in ADDITIONAL_DUPLICATE_ASSIGNMENTS.items():
        for target_code in target_codes:
            removals.setdefault(target_code, set()).add(message_id)
    removal_counts = {}
    for code, message_ids in removals.items():
        path = data_root / "disclosures" / "by-company" / f"{code}.json"
        payload = read_json(path, {}) or {}
        before = payload.get("disclosures", [])
        after = [item for item in before if item.get("telegramMessageId") not in message_ids]
        removal_counts[code] = len(before) - len(after)
        payload["disclosures"] = after
        payload["generatedAt"] = generated_at
        write_json_atomic(path, payload)

    naver_disclosures = read_json(data_root / "disclosures" / "by-company" / f"{NAVER_CODE}.json", {}) or {}
    naver_ids = {item.get("telegramMessageId") for item in naver_disclosures.get("disclosures", [])}
    if naver_ids != {NAVER_VALID_MESSAGE_ID}:
        raise ValueError("NaverDisclosureRecoveryMismatch")

    baseline_path = f"data/earnings/by-company/{NAVER_CODE}.json"
    baseline = load_git_json(baseline_ref, baseline_path, repository_root=repository_root)
    baseline_earnings = (baseline.get("company") or {}).get("earnings", [])
    if len(baseline_earnings) != 8:
        raise ValueError("NaverBaselineQuarterCountMismatch")
    write_json_atomic(data_root / "earnings" / "by-company" / f"{NAVER_CODE}.json", baseline)

    companies = (read_json(data_root / "companies.json", {}) or {}).get("companies", [])
    rebuild_indexes(data_root, companies, generated_at)
    quarantine = build_quarantine(audit, generated_at)
    if len(quarantine) != 113:
        raise ValueError("QuarantineCountMismatch")
    write_json_atomic(quarantine_path, {
        "generatedAt": generated_at,
        "rawMessagesStored": False,
        "quarantine": quarantine,
    })
    if cursor_path.read_bytes() != cursor_before:
        raise RuntimeError("TelegramCursorChanged")
    return {
        "removed_by_target": removal_counts,
        "naver_disclosure_count": len(naver_disclosures["disclosures"]),
        "naver_earnings_quarter_count": len(baseline_earnings),
        "quarantine_count": len(quarantine),
        "cursor": read_json(cursor_path, {}).get("last_processed_message_id"),
    }


def main():
    parser = argparse.ArgumentParser(description="Repair verified Telegram cross-company contamination.")
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--audit-report", type=Path, default=ROOT / "review" / "telegram-cross-company-root-cause.json")
    parser.add_argument("--quarantine-output", type=Path, default=ROOT / "review" / "telegram-quarantine.json")
    parser.add_argument("--baseline-ref", default=BASELINE_REF)
    args = parser.parse_args()
    result = repair(args.data_root, args.audit_report, args.quarantine_output, args.baseline_ref)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
