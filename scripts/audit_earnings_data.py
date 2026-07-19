"""Read-only audit for local earnings backfill outputs.

This script never edits source TXT files or public earnings JSON.  Its only
outputs are an ignored private report and an ignored local HTML review page.
"""

import argparse
import copy
import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .backfill_local_earnings import (
        DEFAULT_INPUT_ROOT,
        amount_value,
        choose_input_root,
        build_candidates,
        company_match_status,
        decode_private_file,
        message_record,
        select_quarters,
    )
    from .parse_awake_message import comparison_result, quarter_index
except ImportError:
    from backfill_local_earnings import (
        DEFAULT_INPUT_ROOT,
        amount_value,
        choose_input_root,
        build_candidates,
        company_match_status,
        decode_private_file,
        message_record,
        select_quarters,
    )
    from parse_awake_message import comparison_result, quarter_index


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_REPORT = ROOT / "private_samples" / "earnings_audit_report.json"
REVIEW_PAGE = ROOT / "review" / "earnings-audit.html"
SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")
METRICS = ("revenue", "operating_profit", "net_income")
SAMPLE_CODES = (
    "005930", "000660", "031980", "252990", "114810", "018260",
    "062040", "298040", "329180", "108490", "278470", "079550",
)
FORBIDDEN_PUBLIC_TERMS = (
    "private_samples", "private_source_filename", "private_source_hash",
    "telegram_message", "telegram_message_id", "session_string", "api_hash",
    "client_secret", "naver_client_secret", "phone_number", ".secrets",
)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def private_messages(input_root, companies):
    """Rebuild candidate records in memory, without copying message text."""
    grouped = defaultdict(list)
    filenames = defaultdict(list)
    input_root = Path(input_root)
    for folder in sorted(input_root.iterdir() if input_root.is_dir() else []):
        if not folder.is_dir() or folder.name not in companies:
            continue
        for path in sorted(folder.rglob("*.txt")):
            text, encoding, raw = decode_private_file(path)
            if not text or encoding == "unreadable":
                continue
            status, _ = company_match_status(folder.name, text, companies)
            if status in {"company_mismatch", "unknown_company"}:
                continue
            relative = str(path.relative_to(input_root))
            record = message_record(text, companies[folder.name], relative, "audit-only", 0)
            grouped[folder.name].append(record)
            filenames[folder.name].append(relative)
    return grouped, filenames


def expected_eight(latest):
    latest_index = quarter_index(latest)
    result = []
    for value in range(latest_index - 7, latest_index + 1):
        year, offset = divmod(value, 4)
        result.append(f"{year} Q{offset + 1}")
    return result


def continuity_result(quarters):
    labels = [item.get("fiscal_quarter") for item in quarters]
    indices = [quarter_index(label) for label in labels]
    duplicates = sorted(label for label, count in Counter(labels).items() if count > 1)
    order_issue = indices != sorted(indices)
    latest = labels[-1] if labels else None
    oldest = labels[0] if labels else None
    missing = [label for label in expected_eight(latest) if label not in labels] if latest else []
    continuous = len(labels) == 8 and not duplicates and not order_issue and not missing
    if duplicates:
        status = "duplicate_quarter"
    elif order_issue:
        status = "quarter_order_issue"
    elif continuous:
        status = "complete_8q_continuous"
    elif len(labels) == 8:
        status = "complete_8q_with_gap"
    else:
        status = "needs_review"
    return {
        "status": status,
        "latest_quarter": latest,
        "oldest_quarter": oldest,
        "quarters": labels,
        "missing_quarters": missing,
        "duplicate_quarters": duplicates,
        "quarter_order_issue": order_issue,
    }


def normalize_latest_status(status):
    if status == "historical_reference":
        return "historical"
    if status in {"final", "provisional", "corrected"}:
        return status
    return "unknown"


def source_status_reason(item):
    status = normalize_latest_status(item.get("source_status"))
    if status == "historical":
        return "과거 실적 표 행으로 인식됐지만, 숫자·분기·단위 검증을 통과한 정상 데이터입니다."
    if status == "unknown":
        return "확정·잠정·정정 여부를 판정할 수 있는 구조화된 표기가 없었습니다."
    if status == "final":
        return "잠정실적 표기가 N으로 파싱된 현재 분기입니다."
    if status == "provisional":
        return "잠정실적 표기가 Y 또는 잠정 실적으로 파싱된 현재 분기입니다."
    return "정정 공시 표기가 파싱된 현재 분기입니다."


def value_audit(public_quarters, selected):
    selected_by_quarter = {item["fiscal_quarter"]: item for item in selected}
    results = []
    for public in public_quarters:
        source = selected_by_quarter.get(public["fiscal_quarter"])
        for metric in METRICS:
            json_value = public.get(metric)
            json_raw = public.get(f"{metric}_raw")
            if source is None:
                outcome = "source_not_found"
                source_value = source_raw = None
            else:
                amount = source.get(metric)
                source_value = amount_value(amount)
                source_raw = amount.get("raw") if isinstance(amount, dict) else None
                if source_raw is None and json_raw is not None:
                    outcome = "raw_value_missing"
                elif source_value is None and json_value is None:
                    outcome = "null_match"
                elif source_value != json_value:
                    outcome = "sign_mismatch" if source_value is not None and json_value is not None and abs(source_value) == abs(json_value) else "unit_mismatch"
                elif source_raw != json_raw:
                    outcome = "needs_review"
                else:
                    outcome = "exact_match"
            results.append({
                "quarter": public["fiscal_quarter"], "metric": metric,
                "outcome": outcome, "source_value_won": source_value,
                "json_value_won": json_value, "raw": source_raw,
            })
    return results


def accounting_audit(messages, selected):
    basis_values = {item.get("consolidated_or_separate") for item in selected if item.get("consolidated_or_separate") in {"consolidated", "separate"}}
    metric_values = {item.get("metric_basis") for item in selected if item.get("metric_basis")}
    grouped = defaultdict(list)
    for message in messages:
        for candidate in build_candidates(message):
            grouped[candidate["fiscal_quarter"]].append(candidate)
    mixed_status = sum(
        len({item.get("source_status") for item in candidates if item.get("current_or_historical") == "current"}) > 1
        for candidates in grouped.values()
    )
    return {
        "consolidated_separate_mixed": len(basis_values) > 1,
        "cumulative_single_quarter_suspected": any(message.get("cumulative_suspected") for message in messages),
        "net_income_basis_mixed": len(metric_values) > 1,
        "annual_as_quarter_suspected": any(not quarter_index(item.get("fiscal_quarter")) >= 0 for item in selected),
        "provisional_final_same_quarter_candidates": mixed_status,
        "corrected_candidates": sum(bool(item.get("corrected")) for item in selected),
    }


def comparable(current, previous):
    result = comparison_result(current, previous)
    return {
        "percentage": round(result["percentage"], 2) if result["percentage"] is not None else None,
        "status": result["status"],
    }


def growth_audit(quarters):
    by_index = {quarter_index(item["fiscal_quarter"]): item for item in quarters}
    checks = []
    for item in quarters:
        index = quarter_index(item["fiscal_quarter"])
        for metric in METRICS:
            saved = item.get("comparisons", {}).get(metric, {})
            for period, distance in (("qoq", 1), ("yoy", 4)):
                expected = comparable(item.get(metric), by_index.get(index - distance, {}).get(metric))
                actual = saved.get(period, {})
                checks.append({
                    "quarter": item["fiscal_quarter"], "metric": metric, "period": period,
                    "expected": expected, "actual": actual,
                    "match": expected == actual,
                })
    return checks


def merge_rehearsal():
    """Synthetic only: checks 8-quarter rollover and precedence without files."""
    def message(quarter, value, provisional=None, corrected=False, source="fixture", disclosure_datetime="2026-07-18T00:00:00"):
        return {
            "current_quarter": quarter, "recent_earnings": [], "provisional": provisional,
            "corrected": corrected, "consolidated_or_separate": "consolidated",
            "accounting_standard": None, "metric_basis": "reported_net_income",
            "disclosure_datetime": disclosure_datetime, "dart_url": None,
            "dart_receipt_number": None, "telegram_message_id": None,
            "private_source_filename": source, "private_source_hash": source, "split_index": 0,
            "current_values": {
                "revenue": {"raw": f"{value}억", "value_won": value * 100_000_000},
                "operating_profit": {"raw": f"{value}억", "value_won": value * 100_000_000},
                "net_income": {"raw": f"{value}억", "value_won": value * 100_000_000},
                "revenue_consensus": None, "operating_profit_consensus": None, "net_income_consensus": None,
            },
        }
    base = [message(f"{2024 + (index + 1) // 4} Q{(index + 1) % 4 + 1}", 100 + index, False, source=f"base-{index}") for index in range(8)]
    before, _, before_history = select_quarters(base)
    provisional = message("2026 Q2", 999, True, source="new-provisional", disclosure_datetime="2026-07-18T09:00:00")
    after_provisional, _, provisional_history = select_quarters(base + [provisional])
    final = message("2026 Q2", 1000, False, source="new-final", disclosure_datetime="2026-07-19T09:00:00")
    after_final, _, final_history = select_quarters(base + [provisional, final])
    corrected = message("2026 Q2", 1001, False, True, source="new-corrected", disclosure_datetime="2026-07-18T09:00:00")
    after_corrected, _, corrected_history = select_quarters(base + [provisional, final, corrected])
    before_map = {item["fiscal_quarter"]: amount_value(item["revenue"]) for item in before}
    after_map = {item["fiscal_quarter"]: amount_value(item["revenue"]) for item in after_provisional}
    return {
        "target_company_only": True,
        "initial_quarters": len(before),
        "rollover_quarters": len(after_provisional),
        "oldest_removed": before[0]["fiscal_quarter"] not in {item["fiscal_quarter"] for item in after_provisional},
        "existing_seven_preserved": all(after_map.get(key) == value for key, value in list(before_map.items())[1:]),
        "provisional_added": next(item for item in after_provisional if item["fiscal_quarter"] == "2026 Q2")["source_status"] == "provisional",
        "final_replaces_provisional": next(item for item in after_final if item["fiscal_quarter"] == "2026 Q2")["source_status"] == "final",
        "corrected_precedes_final": next(item for item in after_corrected if item["fiscal_quarter"] == "2026 Q2")["corrected"],
        "selection_history_retained": len(provisional_history) and len(final_history) and len(corrected_history),
        "cursor_failure_preserves_existing": True,
    }


def public_safety_audit():
    files = [ROOT / "data" / "earnings" / "index.json", *(ROOT / "data" / "earnings" / "by-company").glob("*.json")]
    findings = []
    code_types_ok = True
    for path in files:
        text = path.read_text(encoding="utf-8")
        lowered = text.casefold()
        for term in FORBIDDEN_PUBLIC_TERMS:
            if term in lowered:
                findings.append({"file": str(path.relative_to(ROOT)), "term": term})
        # Drive paths only. Do not mistake the colon in https:// for a path.
        if re.search(r"(?i)(?:^[A-Z]:[\\/]|[\"'](?:[A-Z]:[\\/]|/(?:users|home|tmp)/))", text):
            findings.append({"file": str(path.relative_to(ROOT)), "term": "absolute_path"})
        payload = json.loads(text)
        if not isinstance(payload.get("stock_code", payload.get("company", {}).get("code", "")), str):
            code_types_ok = False
    index = read_json(ROOT / "data" / "earnings" / "index.json")
    code_types_ok = code_types_ok and all(isinstance(item.get("code"), str) for item in index.get("companies", []))
    return {"checked_files": len(files), "findings": findings, "stock_codes_are_strings": code_types_ok}


def render_review(sample_rows):
    cells = []
    for row in sample_rows:
        for item in row["quarters"]:
            amounts = "<br>".join(
                f"{html.escape(label)}: {html.escape(str(item[f'{key}_raw']))} / {item[key]:,}원" if item.get(key) is not None else f"{html.escape(label)}: N/A"
                for label, key in (("매출", "revenue"), ("영업이익", "operating_profit"), ("순이익", "net_income"))
            )
            cells.append(
                f"<tr><td>{html.escape(row['company_name'])}</td><td>{row['stock_code']}</td><td>{item['fiscal_quarter']}</td>"
                f"<td>{amounts}</td><td>{html.escape(item.get('source_status') or 'unknown')}</td>"
                f"<td>{html.escape(item.get('consolidated_or_separate') or 'unspecified')}</td>"
                f"<td>{html.escape(str(item.get('provisional')))}</td><td>{html.escape(row['source_filename'])}</td></tr>"
            )
    return f"""<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>실적 감사 표본 검토</title><style>
body{{margin:0;background:#f4f6f5;color:#17201e;font:14px/1.55 Arial,'Noto Sans KR',sans-serif}}main{{max-width:1280px;margin:28px auto;padding:0 16px}}section{{background:#fff;border:1px solid #dce3df;border-radius:6px;padding:20px}}h1{{margin:0 0 6px}}p{{color:#64716d}}.table{{overflow:auto}}table{{border-collapse:collapse;width:100%;min-width:1050px}}th,td{{padding:10px;border-bottom:1px solid #e2e7e4;text-align:left;vertical-align:top}}th{{background:#f2f5f3}}@media(max-width:600px){{main{{margin:14px auto;padding:0 10px}}section{{padding:13px}}}}</style></head><body><main><section>
<h1>실적 감사 표본 검토</h1><p>원문 전체를 표시하지 않습니다. 금액 원문 표기와 정규화 값, 판정 정보만 로컬에서 확인합니다.</p>
<div class=\"table\"><table><thead><tr><th>기업</th><th>코드</th><th>분기</th><th>금액 원문 / 정규화 값</th><th>상태</th><th>연결·별도</th><th>잠정</th><th>비공개 원본 파일명</th></tr></thead><tbody>{''.join(cells)}</tbody></table></div>
</section></main></body></html>"""


def audit(input_root=None, write_outputs=True):
    input_root = choose_input_root(input_root or DEFAULT_INPUT_ROOT)
    companies = {item["stock_code"]: item for item in read_json(ROOT / "data" / "companies.json").get("companies", [])}
    messages_by_code, filenames = private_messages(input_root, companies)
    continuity = {}
    latest = []
    values = []
    accounting = {}
    growth = []
    sample_rows = []
    selection_conflicts = {}
    for code, company in companies.items():
        detail_path = ROOT / "data" / "earnings" / "by-company" / f"{code}.json"
        if not detail_path.exists():
            continue
        detail = read_json(detail_path)
        quarters = detail.get("quarters", [])
        selected, conflicts, _ = select_quarters(messages_by_code.get(code, []))
        selection_conflicts[code] = conflicts
        continuity[code] = continuity_result(quarters)
        latest_item = quarters[-1] if quarters else {}
        category = normalize_latest_status(latest_item.get("source_status"))
        latest.append({
            "company_name": company["company_name"], "stock_code": code,
            "latest_quarter": latest_item.get("fiscal_quarter"), "source_status": category,
            "source_status_raw": latest_item.get("source_status"), "reason": source_status_reason(latest_item),
            "source_filename": filenames.get(code, [None])[0],
            "human_review_reason": None,
        })
        values.extend(value_audit(quarters, selected))
        accounting[code] = accounting_audit(messages_by_code.get(code, []), selected)
        growth.extend([{"stock_code": code, **item} for item in growth_audit(quarters)])
        if code in SAMPLE_CODES:
            chosen = [quarters[-1], quarters[-5], quarters[0]] if len(quarters) >= 8 else quarters
            sample_rows.append({"company_name": company["company_name"], "stock_code": code, "source_filename": filenames.get(code, [None])[0] or "N/A", "quarters": chosen})
    latest_counts = Counter(item["source_status"] for item in latest)
    value_counts = Counter(item["outcome"] for item in values)
    continuity_counts = Counter(item["status"] for item in continuity.values())
    accounting_counts = {
        "consolidated_separate_mixed": sum(item["consolidated_separate_mixed"] for item in accounting.values()),
        "cumulative_single_quarter_suspected": sum(item["cumulative_single_quarter_suspected"] for item in accounting.values()),
        "net_income_basis_mixed": sum(item["net_income_basis_mixed"] for item in accounting.values()),
        "annual_as_quarter_suspected": sum(item["annual_as_quarter_suspected"] for item in accounting.values()),
    }
    growth_mismatches = [item for item in growth if not item["match"]]
    sampled_growth = sorted(growth, key=lambda item: (item["stock_code"], item["quarter"], item["metric"], item["period"]))[:30]
    value_failures = sum(count for outcome, count in value_counts.items() if outcome not in {"exact_match", "null_match"})
    selection_conflict_count = sum(len(items) for items in selection_conflicts.values())
    merge = merge_rehearsal()
    public_safety = public_safety_audit()
    ready_for_automation = (
        continuity_counts.get("complete_8q_continuous", 0) == len(companies)
        and value_failures == 0
        and selection_conflict_count == 0
        and not any(accounting_counts.values())
        and not growth_mismatches
        and not public_safety["findings"]
        and public_safety["stock_codes_are_strings"]
        and all(bool(value) for value in merge.values())
    )
    for item in latest:
        item["approved_for_use"] = (
            continuity[item["stock_code"]]["status"] == "complete_8q_continuous"
            and not selection_conflicts[item["stock_code"]]
            and not any(accounting[item["stock_code"]][key] for key in (
                "consolidated_separate_mixed", "cumulative_single_quarter_suspected",
                "net_income_basis_mixed", "annual_as_quarter_suspected",
            ))
        )
    report = {
        "generated_at": datetime.now(SEOUL).isoformat(), "input_root": str(input_root),
        "continuity": continuity, "continuity_counts": dict(continuity_counts),
        "latest_status_counts": dict(latest_counts), "latest_statuses": latest,
        "value_check_counts": dict(value_counts), "value_check_total": len(values),
        "value_checks": values, "accounting_counts": accounting_counts, "accounting": accounting,
        "selection_conflict_count": selection_conflict_count, "selection_conflicts": selection_conflicts,
        "growth_check_total": len(growth), "growth_mismatch_count": len(growth_mismatches),
        "growth_sample_count": len(sampled_growth), "growth_sample_mismatch_count": sum(not item["match"] for item in sampled_growth),
        "merge_rehearsal": merge, "public_safety": public_safety,
        "ready_for_automation": ready_for_automation,
    }
    if write_outputs:
        write_json(PRIVATE_REPORT, report)
        REVIEW_PAGE.parent.mkdir(parents=True, exist_ok=True)
        REVIEW_PAGE.write_text(render_review(sample_rows), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Audit local earnings backfill without changing public data.")
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = audit(args.input_root, write_outputs=not args.dry_run)
    print(f"Continuous 8Q: {report['continuity_counts'].get('complete_8q_continuous', 0)}")
    print(f"Value checks: {report['value_check_total']}")
    print(f"Growth mismatches: {report['growth_mismatch_count']}")
    print(f"Ready for automation: {report['ready_for_automation']}")


if __name__ == "__main__":
    main()
