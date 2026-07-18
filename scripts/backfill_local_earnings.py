import argparse
import hashlib
import html
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .parse_awake_message import (
        comparison_result,
        normalize_quarter,
        parse_amount,
        parse_awake_message,
        QUARTER_RE,
        quarter_index,
        report_period_to_quarter,
    )
except ImportError:
    from parse_awake_message import (
        comparison_result,
        normalize_quarter,
        parse_amount,
        parse_awake_message,
        QUARTER_RE,
        quarter_index,
        report_period_to_quarter,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_ROOT = ROOT / "private_samples" / "earnings_backfill"
LEGACY_INPUT_ROOT = ROOT / "private_samples"
PRIVATE_REPORT_PATH = ROOT / "private_samples" / "earnings_backfill_report.json"
REVIEW_PATH = ROOT / "review" / "earnings-backfill-review.html"
SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")
CODE_RE = re.compile(r"^[0-9A-Z]{6}$")
EXPLICIT_CODE_RE = re.compile(r"(?<![0-9A-Z])(?:A)?([0-9A-Z]{6})(?![0-9A-Z])", re.IGNORECASE)
MESSAGE_ID_RE = re.compile(r"(?im)(?:telegram\s*)?(?:message[_ ]?id|메시지\s*(?:id|번호))\s*[:#]?\s*(\d+)")


def read_json(path, default=None):
    path = Path(path)
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def choose_input_root(preferred=DEFAULT_INPUT_ROOT):
    preferred = Path(preferred)
    if preferred.is_dir():
        return preferred
    legacy_folders = [item for item in LEGACY_INPUT_ROOT.iterdir() if item.is_dir() and CODE_RE.fullmatch(item.name)]
    if legacy_folders:
        return LEGACY_INPUT_ROOT
    return preferred


def decode_private_file(path):
    raw = Path(path).read_bytes()
    if not raw:
        return "", "empty", raw
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding), encoding, raw
        except UnicodeDecodeError:
            continue
    return None, "unreadable", raw


def split_messages(text):
    clean = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not clean:
        return [], False
    header_pattern = re.compile(r"(?im)^(?=\s*(?:\[?기업명\]?|회사명|종목명)\s*[:：])")
    positions = [match.start() for match in header_pattern.finditer(clean)]
    message_id_count = len(MESSAGE_ID_RE.findall(clean))
    if len(positions) <= 1 or message_id_count <= 1:
        return [clean], False
    parts = []
    for index, start in enumerate(positions):
        end = positions[index + 1] if index + 1 < len(positions) else len(clean)
        part = clean[start:end].strip("\n- ")
        if part:
            parts.append(part)
    certain = len(parts) == len(positions) and all(parse_awake_message(part).get("has_earnings_data") for part in parts)
    return (parts if certain else [clean]), not certain


def explicit_company_signals(text, companies):
    code_match = re.search(
        r"(?im)^\s*(?:종목\s*코드|stock\s*code)\s*[:：]\s*(?:A)?([0-9A-Z]{6})\b",
        text or "",
    )
    detected_known_codes = {code_match.group(1).upper()} if code_match and code_match.group(1).upper() in companies else set()
    detected_names = []
    name_match = re.search(r"(?im)^\s*(?:기업명|회사명|종목명)\s*[:：]\s*(.+?)\s*$", text or "")
    explicit_name = name_match.group(1).strip() if name_match else None
    if explicit_name:
        for company in companies.values():
            terms = [
                company.get("company_name"), company.get("input_company_name"),
                *company.get("aliases", []), *company.get("previous_names", []),
            ]
            for term in terms:
                if term and explicit_name.casefold() == term.casefold():
                    detected_names.append((company["stock_code"], term, term == company.get("company_name")))
                    break
    return detected_known_codes, detected_names


def company_match_status(folder_code, text, companies):
    company = companies.get(folder_code)
    if company is None:
        return "unknown_company", []
    codes, names = explicit_company_signals(text, companies)
    mismatched_codes = sorted(code for code in codes if code != folder_code)
    mismatched_names = sorted({code for code, _, _ in names if code != folder_code})
    if mismatched_codes or mismatched_names:
        return "company_mismatch", sorted(set(mismatched_codes + mismatched_names))
    own_names = [(term, exact) for code, term, exact in names if code == folder_code]
    if folder_code in codes and any(exact for _, exact in own_names):
        return "exact_match", []
    if folder_code in codes and own_names:
        return "alias_match", []
    return "folder_only_match", []


def detect_basis(text):
    has_consolidated = "연결" in text
    has_separate = "별도" in text or "개별" in text
    if has_consolidated and has_separate:
        return "mixed", True
    if has_consolidated:
        return "consolidated", False
    if has_separate:
        return "separate", False
    return "unspecified", False


def detect_accounting_standard(text):
    normalized = text.casefold()
    if "k-ifrs" in normalized or "kifrs" in normalized or "한국채택국제회계기준" in text:
        return "K-IFRS"
    if "ifrs" in normalized:
        return "IFRS"
    return None


def metric_basis(text):
    if "지배주주순이익" in text or "지배기업 소유주지분" in text:
        return "controlling_net_income"
    if "당기순이익" in text:
        return "net_income"
    return "reported_net_income"


def message_record(text, company, filename, file_hash, split_index):
    parsed = parse_awake_message(text, default_company_name=company["company_name"], default_stock_code=company["stock_code"])
    basis, mixed_basis = detect_basis(text)
    current_quarter = report_period_to_quarter(parsed.get("report_period"))
    corrected = parsed.get("classification") == "correction" or "정정" in text
    message_id = None
    id_match = MESSAGE_ID_RE.search(text)
    if id_match:
        message_id = int(id_match.group(1))
    text_without_links = re.sub(r"https?://\S+", " ", text)
    cumulative_suspected = "누적" in text_without_links and "누적 아님" not in text_without_links
    unit_uncertain = any(
        QUARTER_RE.search(line)
        and len(re.findall(r"[-+()]?\d[\d,.]*", line)) >= 4
        and not re.search(r"조|억|백만|천", line)
        for line in text_without_links.splitlines()
    )
    return {
        "company_name": parsed.get("company_name") or company["company_name"],
        "stock_code": company["stock_code"],
        "report_name": parsed.get("report_name"),
        "report_period": parsed.get("report_period"),
        "disclosure_datetime": parsed.get("disclosure_datetime"),
        "provisional": parsed.get("provisional"),
        "corrected": corrected,
        "consolidated_or_separate": basis,
        "mixed_basis_suspected": mixed_basis,
        "accounting_standard": detect_accounting_standard(text),
        "fiscal_year_end": None,
        "metric_basis": metric_basis(text),
        "dart_url": parsed.get("dart_url"),
        "dart_receipt_number": parsed.get("dart_receipt_number"),
        "telegram_message_id": message_id,
        "private_source_filename": filename,
        "private_source_hash": file_hash,
        "split_index": split_index,
        "current_quarter": current_quarter,
        "recent_earnings": parsed.get("recent_earnings", []),
        "current_values": {
            "revenue": parsed.get("revenue_actual"),
            "operating_profit": parsed.get("operating_profit_actual"),
            "net_income": parsed.get("net_income_actual"),
            "revenue_consensus": parsed.get("revenue_consensus"),
            "operating_profit_consensus": parsed.get("operating_profit_consensus"),
            "net_income_consensus": parsed.get("net_income_consensus"),
        },
        "cumulative_suspected": cumulative_suspected,
        "unit_uncertain": unit_uncertain,
    }


def amount_value(value):
    if isinstance(value, dict):
        return value.get("value_won")
    if isinstance(value, (int, float)):
        return int(value)
    return None


def candidate_signature(candidate):
    return tuple(amount_value(candidate.get(key)) for key in ("revenue", "operating_profit", "net_income"))


def build_candidates(message):
    candidates = []
    for row in message["recent_earnings"]:
        is_current = row["fiscal_quarter"] == message.get("current_quarter")
        candidates.append({
            "fiscal_quarter": row["fiscal_quarter"],
            "revenue": row.get("revenue"),
            "operating_profit": row.get("operating_profit"),
            "net_income": row.get("net_income"),
            "revenue_consensus": None,
            "operating_profit_consensus": None,
            "net_income_consensus": None,
            "current_or_historical": "current" if is_current else "historical",
            "provisional": message["provisional"] if is_current else None,
            "corrected": message["corrected"] if is_current else False,
            "source_status": "corrected" if is_current and message["corrected"] else "provisional" if is_current and message["provisional"] is True else "final" if is_current and message["provisional"] is False else "historical_reference",
            **{key: message.get(key) for key in (
                "consolidated_or_separate", "accounting_standard", "metric_basis", "disclosure_datetime",
                "dart_url", "dart_receipt_number", "telegram_message_id", "private_source_filename",
                "private_source_hash", "split_index",
            )},
        })
    current = message.get("current_quarter")
    values = message.get("current_values", {})
    if current and any(values.get(key) is not None for key in ("revenue", "operating_profit", "net_income")):
        candidates.append({
            "fiscal_quarter": current,
            **values,
            "current_or_historical": "current",
            "provisional": message["provisional"],
            "corrected": message["corrected"],
            "source_status": "corrected" if message["corrected"] else "final" if message["provisional"] is False else "provisional" if message["provisional"] is True else "latest_unverified",
            **{key: message.get(key) for key in (
                "consolidated_or_separate", "accounting_standard", "metric_basis", "disclosure_datetime",
                "dart_url", "dart_receipt_number", "telegram_message_id", "private_source_filename",
                "private_source_hash", "split_index",
            )},
        })
    return candidates


def selection_rank(candidate):
    """Stable tie-break only; status never outranks a newer disclosure."""
    basis_rank = {"consolidated": 3, "unspecified": 2, "separate": 1, "mixed": 0}
    return (
        int(candidate.get("current_or_historical") == "current"),
        basis_rank.get(candidate.get("consolidated_or_separate"), 0),
        candidate.get("split_index") or 0,
    )


def public_source_history(candidates):
    """Keep structured value history without private filenames, hashes, or message text."""
    history = []
    seen = set()
    for item in candidates:
        entry = {
            "source_status": item.get("source_status"),
            "provisional": item.get("provisional"),
            "corrected": bool(item.get("corrected")),
            "disclosure_datetime": item.get("disclosure_datetime"),
            "revenue": amount_value(item.get("revenue")),
            "operating_profit": amount_value(item.get("operating_profit")),
            "net_income": amount_value(item.get("net_income")),
            "dart_url": item.get("dart_url"),
        }
        signature = tuple(entry.items())
        if signature not in seen:
            seen.add(signature)
            history.append(entry)
    return history


def select_quarters(messages):
    grouped = defaultdict(list)
    for message in messages:
        for candidate in build_candidates(message):
            key = (candidate["fiscal_quarter"], candidate["metric_basis"])
            grouped[key].append(candidate)
    selected = []
    conflicts = []
    selection_history = []
    for key, candidates in grouped.items():
        corrected_candidates = [item for item in candidates if item.get("corrected")]
        eligible = corrected_candidates or candidates
        signatures = {candidate_signature(item) for item in eligible}
        timestamps = [item.get("disclosure_datetime") for item in eligible]
        all_timestamps_known = all(timestamps)
        if all_timestamps_known:
            latest_timestamp = max(timestamps)
            top_ranked = [item for item in eligible if item.get("disclosure_datetime") == latest_timestamp]
        else:
            latest_timestamp = None
            top_ranked = list(eligible)
        top_signatures = {candidate_signature(item) for item in top_ranked}
        conflict_reason = None
        if len(signatures) > 1 and not all_timestamps_known:
            conflict_reason = "conflicting_values_without_comparable_disclosure_datetime"
        elif len(top_signatures) > 1:
            conflict_reason = "conflicting_values_at_same_disclosure_datetime"
        if conflict_reason:
            conflicts.append({
                "fiscal_quarter": key[0],
                "basis": sorted({item.get("consolidated_or_separate") for item in candidates}),
                "metric_basis": key[1],
                "candidate_count": len(candidates),
                "source_files": sorted({item["private_source_filename"] for item in candidates}),
                "reason": conflict_reason,
            })
        top_ranked.sort(key=selection_rank, reverse=True)
        selected_original = top_ranked[0]
        choice = dict(selected_original)
        choice["source_history"] = public_source_history(candidates)
        selected.append(choice)
        selection_history.append({
            "fiscal_quarter": key[0],
            "selected_source": choice["private_source_filename"],
            "selected_hash": choice["private_source_hash"],
            "selected_status": choice["source_status"],
            "selected_disclosure_datetime": choice.get("disclosure_datetime"),
            "selection_reason": "corrected > latest disclosure_datetime; status is informational only",
            "candidate_count": len(candidates),
            "rejected_candidates": [
                {
                    "source_file": item["private_source_filename"],
                    "source_hash": item["private_source_hash"],
                    "status": item["source_status"],
                    "disclosure_datetime": item["disclosure_datetime"],
                }
                for item in sorted(candidates, key=selection_rank, reverse=True)
                if item is not selected_original
            ],
        })
    selected.sort(key=lambda item: quarter_index(item["fiscal_quarter"]))
    return selected[-8:], conflicts, selection_history


def expected_quarters(latest_quarter, count=8):
    latest = quarter_index(latest_quarter)
    result = []
    for value in range(latest - count + 1, latest + 1):
        year, quarter_offset = divmod(value, 4)
        result.append(f"{year} Q{quarter_offset + 1}")
    return result


def missing_quarters(quarters):
    if not quarters:
        return []
    actual = {item["fiscal_quarter"] for item in quarters}
    return [quarter for quarter in expected_quarters(quarters[-1]["fiscal_quarter"], 8) if quarter not in actual]


def completion_status(quarters, missing, conflicts, needs_review=False):
    if needs_review:
        return "needs_review"
    if conflicts:
        return "needs_review"
    if len(quarters) >= 8 and not missing:
        return "complete_8q"
    if len(quarters) >= 5:
        return "partial_5_to_7q"
    if quarters:
        return "partial_1_to_4q"
    return "no_valid_quarter"


def comparison(current, previous):
    result = comparison_result(current, previous)
    percentage = result.get("percentage")
    return {"percentage": round(percentage, 2) if percentage is not None else None, "status": result.get("status")}


def with_comparisons(quarters):
    by_index = {quarter_index(item["fiscal_quarter"]): item for item in quarters}
    output = []
    for item in quarters:
        index = quarter_index(item["fiscal_quarter"])
        enriched = dict(item)
        enriched["comparisons"] = {}
        for metric in ("revenue", "operating_profit", "net_income"):
            current = amount_value(item.get(metric))
            enriched["comparisons"][metric] = {
                "qoq": comparison(current, amount_value(by_index.get(index - 1, {}).get(metric))),
                "yoy": comparison(current, amount_value(by_index.get(index - 4, {}).get(metric))),
            }
        output.append(enriched)
    return output


def public_quarter(candidate):
    return {
        "fiscal_quarter": candidate["fiscal_quarter"],
        "fiscal_year": int(candidate["fiscal_quarter"][:4]),
        "quarter_number": int(candidate["fiscal_quarter"][-1]),
        "revenue": amount_value(candidate.get("revenue")),
        "operating_profit": amount_value(candidate.get("operating_profit")),
        "net_income": amount_value(candidate.get("net_income")),
        "revenue_raw": candidate.get("revenue", {}).get("raw") if candidate.get("revenue") else None,
        "operating_profit_raw": candidate.get("operating_profit", {}).get("raw") if candidate.get("operating_profit") else None,
        "net_income_raw": candidate.get("net_income", {}).get("raw") if candidate.get("net_income") else None,
        "revenue_consensus": amount_value(candidate.get("revenue_consensus")),
        "operating_profit_consensus": amount_value(candidate.get("operating_profit_consensus")),
        "net_income_consensus": amount_value(candidate.get("net_income_consensus")),
        "current_or_historical": candidate.get("current_or_historical"),
        "source_status": candidate.get("source_status"),
        "provisional": candidate.get("provisional"),
        "corrected": bool(candidate.get("corrected")),
        "consolidated_or_separate": candidate.get("consolidated_or_separate"),
        "accounting_standard": candidate.get("accounting_standard"),
        "metric_basis": candidate.get("metric_basis"),
        "disclosure_datetime": candidate.get("disclosure_datetime"),
        "dart_url": candidate.get("dart_url"),
        "source_history": candidate.get("source_history", []),
    }


def legacy_quarter(item):
    def eok(value):
        return value / 100_000_000 if value is not None else None
    return {
        "period": item["fiscal_quarter"],
        "revenue": eok(item["revenue"]),
        "operatingIncome": eok(item["operating_profit"]),
        "netIncome": eok(item["net_income"]),
        "estimateRevenue": eok(item["revenue_consensus"]),
        "estimateOperatingIncome": eok(item["operating_profit_consensus"]),
        "estimateNetIncome": eok(item["net_income_consensus"]),
        "provisional": item["provisional"],
        "corrected": item["corrected"],
        "sourceStatus": item["source_status"],
        "consolidatedOrSeparate": item["consolidated_or_separate"],
        "dartUrl": item["dart_url"],
        "comparisons": item["comparisons"],
    }


def render_review(report):
    rows = []
    reviews = []
    for code, result in report["companies"].items():
        rows.append(
            f"<tr><td>{html.escape(result['company_name'])}</td><td>{code}</td><td>{result['file_count']}</td>"
            f"<td>{result['quarter_count']}</td><td>{result['completion_status']}</td>"
            f"<td>{len(result['missing_quarters'])}</td><td>{result['warning_count']}</td></tr>"
        )
        if result["human_review_files"]:
            reviews.append(
                f"<li><b>{html.escape(result['company_name'])} ({code})</b>: "
                + ", ".join(html.escape(item) for item in result["human_review_files"]) + "</li>"
            )
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>실적 백필 검토</title><style>
body{{margin:0;background:#f3f6f4;color:#18201f;font:14px/1.55 Arial,'Noto Sans KR',sans-serif}}main{{width:min(1200px,calc(100% - 28px));margin:28px auto}}section{{background:#fff;border:1px solid #dce2df;border-radius:6px;padding:18px;margin-bottom:16px}}h1{{margin:0}}p{{color:#64706d}}.metrics{{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:#dce2df}}.metric{{background:#fff;padding:14px}}.metric b{{display:block;font-size:22px}}.metric span{{color:#64706d;font-size:12px}}.table{{overflow:auto}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{text-align:left;padding:9px;border-bottom:1px solid #dce2df}}th{{background:#f3f6f4}}@media(max-width:700px){{.metrics{{grid-template-columns:repeat(2,1fr)}}section{{padding:13px}}}}</style></head><body><main>
<section><h1>실적 백필 로컬 검토</h1><p>Telegram 원문은 표시하지 않으며 비공개 파일명과 구조화된 진단만 제공합니다.</p></section>
<section><div class="metrics"><div class="metric"><b>{report['inventory']['company_folder_count']}</b><span>종목 폴더</span></div><div class="metric"><b>{report['inventory']['txt_file_count']}</b><span>TXT 파일</span></div><div class="metric"><b>{report['summary']['parsed_file_count']}</b><span>파싱 성공</span></div><div class="metric"><b>{report['summary']['complete_8q']}</b><span>8분기 완성</span></div><div class="metric"><b>{report['summary']['unique_quarter_count']}</b><span>고유 분기</span></div></div></section>
<section><h2>기업별 완성도</h2><div class="table"><table><thead><tr><th>기업</th><th>코드</th><th>파일</th><th>분기</th><th>상태</th><th>누락</th><th>경고</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
<section><h2>사람 확인 필요</h2><ul>{''.join(reviews) or '<li>없음</li>'}</ul></section>
</main></body></html>"""


def process(input_root=None, apply=True):
    input_root = choose_input_root(input_root or DEFAULT_INPUT_ROOT)
    companies_data = read_json(ROOT / "data" / "companies.json", {"companies": []})
    companies = {item["stock_code"]: item for item in companies_data.get("companies", [])}
    folders = [item for item in input_root.iterdir() if item.is_dir() and CODE_RE.fullmatch(item.name)] if input_root.is_dir() else []
    files = sorted(path for folder in folders for path in folder.rglob("*.txt"))
    hashes = Counter()
    seen_hashes = set()
    file_records = []
    company_messages = defaultdict(list)
    company_files = defaultdict(list)
    inventory_warnings = []
    for path in files:
        folder_code = path.relative_to(input_root).parts[0]
        text, encoding, raw = decode_private_file(path)
        digest = hashlib.sha256(raw).hexdigest()
        hashes[digest] += 1
        relative_name = str(path.relative_to(input_root))
        record = {
            "stock_code_folder": folder_code,
            "private_source_filename": relative_name,
            "size_bytes": len(raw),
            "sha256": digest,
            "encoding": encoding,
            "empty": not bool(text and text.strip()),
            "match_status": "unknown_company",
            "message_count": 0,
            "message_split_uncertain": False,
            "parse_status": "failed",
            "warnings": [],
        }
        if digest in seen_hashes:
            record["parse_status"] = "skipped_duplicate"
            record["warnings"].append("duplicate_file_hash")
            file_records.append(record)
            continue
        seen_hashes.add(digest)
        if text is None or not text.strip():
            record["warnings"].append("unreadable_or_empty")
            file_records.append(record)
            continue
        match_status, mismatches = company_match_status(folder_code, text, companies)
        record["match_status"] = match_status
        if mismatches:
            record["warnings"].append("company_mismatch:" + ",".join(mismatches))
        messages, split_uncertain = split_messages(text)
        record["message_count"] = len(messages)
        record["message_split_uncertain"] = split_uncertain
        if split_uncertain:
            record["warnings"].append("message_split_uncertain")
        if match_status in {"company_mismatch", "unknown_company"}:
            file_records.append(record)
            continue
        company = companies[folder_code]
        parsed_messages = [message_record(message, company, relative_name, digest, index) for index, message in enumerate(messages)]
        valid_rows = sum(len(message["recent_earnings"]) for message in parsed_messages)
        record["parse_status"] = "success" if valid_rows else "failed"
        record["parsed_quarter_rows"] = valid_rows
        record["unit_uncertain"] = any(message["unit_uncertain"] for message in parsed_messages)
        record["cumulative_suspected"] = any(message["cumulative_suspected"] for message in parsed_messages)
        record["mixed_basis_suspected"] = any(message["mixed_basis_suspected"] for message in parsed_messages)
        company_files[folder_code].append(record)
        if valid_rows:
            company_messages[folder_code].extend(parsed_messages)
        file_records.append(record)

    generated_at = datetime.now(SEOUL).isoformat()
    private_company_results = {}
    public_index_companies = []
    summary_counts = Counter()
    quarter_labels = set()
    quarter_record_count = 0
    for code, company in companies.items():
        messages = company_messages.get(code, [])
        selected, conflicts, history = select_quarters(messages)
        public_quarters = with_comparisons([public_quarter(item) for item in selected])
        missing = missing_quarters(public_quarters)
        files_for_company = company_files.get(code, [])
        needs_review = any(
            item["match_status"] in {"company_mismatch", "unknown_company"}
            or item["message_split_uncertain"]
            or item.get("unit_uncertain")
            or item.get("cumulative_suspected")
            or item.get("mixed_basis_suspected")
            for item in files_for_company
        )
        status = completion_status(public_quarters, missing, conflicts, needs_review)
        warning_count = len(conflicts) + len(missing) + sum(len(item["warnings"]) for item in files_for_company)
        current_basis_values = {item.get("consolidated_or_separate") for item in public_quarters if item.get("consolidated_or_separate")}
        current_basis = next(iter(current_basis_values)) if len(current_basis_values) == 1 else "mixed" if current_basis_values else "unspecified"
        human_review_files = sorted({
            item["private_source_filename"] for item in files_for_company
            if item["warnings"] or item.get("unit_uncertain") or item.get("cumulative_suspected") or item.get("mixed_basis_suspected")
        })
        private_company_results[code] = {
            "company_name": company["company_name"],
            "file_count": len(files_for_company),
            "quarter_count": len(public_quarters),
            "completion_status": status,
            "missing_quarters": missing,
            "conflicts": conflicts,
            "selection_history": history,
            "current_basis": current_basis,
            "warning_count": warning_count,
            "human_review_files": human_review_files,
        }
        summary_counts[status] += 1
        quarter_labels.update(item["fiscal_quarter"] for item in public_quarters)
        quarter_record_count += len(public_quarters)
        payload = {
            "company_name": company["company_name"],
            "stock_code": code,
            "updated_at": generated_at,
            "completion_status": status,
            "quarter_count": len(public_quarters),
            "missing_quarters": missing,
            "current_basis": current_basis,
            "quarters": public_quarters,
            "source_count": len(files_for_company),
            "warning_count": warning_count,
            "company": {
                "name": company["company_name"], "code": code, "market": company.get("sector"),
                "category": company.get("category"), "monitoringTier": company.get("monitoring_tier"),
                "completionStatus": status, "missingQuarters": missing, "currentBasis": current_basis,
                "earnings": [legacy_quarter(item) for item in public_quarters], "news": [],
            },
        }
        if apply and messages and status not in {"needs_review", "no_valid_quarter"}:
            write_json_atomic(ROOT / "data" / "earnings" / "by-company" / f"{code}.json", payload)
        public_index_companies.append({
            "name": company["company_name"], "code": code, "market": company.get("sector"),
            "category": company.get("category"), "monitoringTier": company.get("monitoring_tier"),
            "validationStatus": company.get("validation_status"), "hasDetails": bool(public_quarters),
            "completionStatus": status, "missingQuarters": missing, "currentBasis": current_basis,
            "earnings": [legacy_quarter(item) for item in public_quarters],
        })

    duplicate_hashes = {digest: count for digest, count in hashes.items() if count > 1}
    report = {
        "generated_at": generated_at,
        "input_root": str(input_root),
        "inventory": {
            "company_folder_count": len(folders), "txt_file_count": len(files),
            "empty_file_count": sum(item["empty"] for item in file_records),
            "unreadable_file_count": sum(item["encoding"] == "unreadable" for item in file_records),
            "encoding_issue_count": sum(item["encoding"] not in {"utf-8-sig", "empty"} for item in file_records),
            "unknown_folder_codes": sorted(folder.name for folder in folders if folder.name not in companies),
            "companies_without_folder": sorted(set(companies) - {folder.name for folder in folders}),
            "duplicate_file_count": sum(count - 1 for count in duplicate_hashes.values()),
            "duplicate_hashes": duplicate_hashes,
            "message_split_uncertain_count": sum(item["message_split_uncertain"] for item in file_records),
            "company_mismatch_file_count": sum(item["match_status"] == "company_mismatch" for item in file_records),
        },
        "summary": {
            "parsed_file_count": sum(item["parse_status"] == "success" for item in file_records),
            "failed_file_count": sum(item["parse_status"] == "failed" for item in file_records),
            "matched_company_count": sum(bool(company_messages.get(code)) for code in companies),
            "unique_quarter_count": len(quarter_labels),
            "quarter_record_count": quarter_record_count,
            "conflict_quarter_count": sum(len(item["conflicts"]) for item in private_company_results.values()),
            "unit_uncertain_count": sum(bool(item.get("unit_uncertain")) for item in file_records),
            "mixed_basis_suspected_count": sum(bool(item.get("mixed_basis_suspected")) for item in file_records),
            "cumulative_suspected_count": sum(bool(item.get("cumulative_suspected")) for item in file_records),
            **{status: summary_counts.get(status, 0) for status in (
                "complete_8q", "partial_5_to_7q", "partial_1_to_4q", "no_valid_quarter", "needs_review", "conflicting_data",
            )},
        },
        "files": file_records,
        "companies": private_company_results,
        "inventory_warnings": inventory_warnings,
    }
    if apply:
        write_json_atomic(ROOT / "data" / "earnings" / "index.json", {
            "generatedAt": generated_at, "currencyUnit": "억원",
            "watchlist": [
                {key: item[key] for key in ("name", "code", "market", "category", "monitoringTier", "validationStatus")}
                for item in public_index_companies
            ],
            "companies": public_index_companies,
        })
        write_json_atomic(PRIVATE_REPORT_PATH, report)
        REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        REVIEW_PATH.write_text(render_review(report), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Backfill earnings from ignored local Telegram text samples only.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = process(args.input_root, apply=not args.dry_run)
    print(f"Company folders: {report['inventory']['company_folder_count']}")
    print(f"TXT files: {report['inventory']['txt_file_count']}")
    print(f"Parsed files: {report['summary']['parsed_file_count']}")
    print(f"Complete 8Q: {report['summary']['complete_8q']}")
    print(f"Needs review: {report['summary']['needs_review'] + report['summary']['conflicting_data']}")


if __name__ == "__main__":
    main()
