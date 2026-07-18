"""Generate and optionally apply a sanitized incremental portfolio update."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from .backfill_portfolio_telegram import run as run_telegram
    from .incremental_provider_adapters import GdeltIncrementalProvider, NaverIncrementalProvider
    from .news_batch_pipeline import BatchNewsPipeline, load_pipeline_config, read_json
except ImportError:
    from backfill_portfolio_telegram import run as run_telegram
    from incremental_provider_adapters import GdeltIncrementalProvider, NaverIncrementalProvider
    from news_batch_pipeline import BatchNewsPipeline, load_pipeline_config, read_json


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_GROUPS = ("news", "earnings", "disclosures")
FORBIDDEN_KEYS = {
    "body", "content", "html", "description", "client_secret", "api_hash",
    "session", "session_string", "phone", "phone_number", "telegram_message",
    "private_source_filename",
}
FORBIDDEN_TEXT = ("private_samples", ".secrets", "telegram_session", "naver_client_secret")
WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)(?<![A-Z0-9])[A-Z]:[\\/]")
PHONE_NUMBER = re.compile(r"(?<!\d)(?:\+82[- ]?10|010)[- ]\d{3,4}[- ]\d{4}(?!\d)")


def is_allowed_repository_path(relative_path):
    path = Path(relative_path).as_posix()
    if path.startswith("data/state/") and path.endswith(".json"):
        return True
    return any(
        path == f"data/{group}/index.json"
        or (path.startswith(f"data/{group}/by-company/") and path.endswith(".json"))
        for group in PUBLIC_GROUPS
    )


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_json_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).casefold()
            yield from iter_json_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_json_keys(child)


def find_non_string_stock_codes(value):
    findings = 0
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"stock_code", "stockCode", "code"} and child is not None and not isinstance(child, str):
                findings += 1
            findings += find_non_string_stock_codes(child)
    elif isinstance(value, list):
        findings += sum(find_non_string_stock_codes(child) for child in value)
    return findings


def public_json_checks(data_root):
    data_root = Path(data_root)
    findings = []
    files = []
    for group in PUBLIC_GROUPS:
        index_path = data_root / group / "index.json"
        files.append(index_path)
        files.extend(sorted((data_root / group / "by-company").glob("*.json")))
    files.extend(sorted((data_root / "state").glob("*.json")))
    for path in files:
        relative = path.relative_to(data_root.parent).as_posix()
        if not path.is_file():
            findings.append({"file": relative, "type": "missing_file"})
            continue
        try:
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            findings.append({"file": relative, "type": "invalid_json"})
            continue
        lowered = text.casefold()
        if any(term in lowered for term in FORBIDDEN_TEXT):
            findings.append({"file": relative, "type": "forbidden_term"})
        if WINDOWS_ABSOLUTE_PATH.search(text):
            findings.append({"file": relative, "type": "absolute_path"})
        if PHONE_NUMBER.search(text):
            findings.append({"file": relative, "type": "phone_number"})
        forbidden = sorted(set(iter_json_keys(payload)) & FORBIDDEN_KEYS)
        if forbidden:
            findings.append({"file": relative, "type": "forbidden_key", "keys": forbidden})
        if find_non_string_stock_codes(payload):
            findings.append({"file": relative, "type": "non_string_stock_code"})
    return {"files_checked": len(files), "findings": findings}


def changed_allowed_files(source_data, target_data):
    source_data = Path(source_data)
    target_data = Path(target_data)
    changes = []
    for group in PUBLIC_GROUPS:
        candidates = [source_data / group / "index.json"]
        candidates.extend(sorted((source_data / group / "by-company").glob("*.json")))
        for source in candidates:
            relative = source.relative_to(source_data.parent)
            target = target_data.parent / relative
            if source.is_file() and (not target.is_file() or sha256_file(source) != sha256_file(target)):
                changes.append(relative.as_posix())
    for source in sorted((source_data / "state").glob("*.json")):
        relative = source.relative_to(source_data.parent)
        target = target_data.parent / relative
        if not target.is_file() or sha256_file(source) != sha256_file(target):
            changes.append(relative.as_posix())
    return sorted(set(changes))


def apply_files_atomically(source_root, target_root, relative_paths):
    applied = []
    for relative_text in relative_paths:
        if not is_allowed_repository_path(relative_text):
            raise ValueError(f"DisallowedRepositoryPath:{relative_text}")
        relative = Path(relative_text)
        source = Path(source_root) / relative
        target = Path(target_root) / relative
        if not source.is_file():
            raise FileNotFoundError(f"MissingGeneratedFile:{relative_text}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".production.tmp")
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
        applied.append(relative_text)
    return applied


def sanitized_news_report(report):
    return {
        "processed_companies": report.get("processed_companies", 0),
        "successful_companies": len(report.get("successful_companies", [])),
        "failed_companies": len(report.get("failed_companies", [])),
        "skipped_companies": len(report.get("skipped_companies", [])),
        "provider_api_calls": report.get("provider_api_calls", {}),
        "company_api_calls": report.get("company_api_calls", {}),
        "successful_company_codes": report.get("successful_companies", []),
        "failed_company_codes": report.get("failed_companies", []),
        "provider_error_counts": report.get("provider_error_counts", {}),
        "raw_article_count": report.get("raw_article_count", 0),
        "new_article_count": report.get("new_article_count", 0),
        "duplicate_article_count": report.get("duplicate_article_count", 0),
        "new_event_cluster_count": report.get("new_event_cluster_count", 0),
        "cursor_updates": report.get("cursor_updates", []),
        "data_changed": report.get("data_changed", False),
        "severe_failure": report.get("severe_failure", False),
    }


def sanitized_telegram_report(report):
    return {
        "status": "ok" if not report.get("errors") else "failed",
        "companies_considered": report.get("companies_considered", 0),
        "messages_fetched": report.get("messages_fetched", 0),
        "unique_matched_messages": report.get("unique_matched_messages", 0),
        "companies_with_matches": report.get("companies_with_matches", 0),
        "new_quarters": report.get("new_quarters", 0),
        "new_disclosures": report.get("new_disclosures", 0),
        "parse_failure_count": report.get("parse_failure_count", 0),
        "company_results": report.get("company_results", {}),
        "error_types": [item.get("type", "UnknownError") for item in report.get("errors", [])],
        "cursor_updated": report.get("cursor_updated", False),
        "duration_seconds": report.get("duration_seconds", 0),
    }


def write_report(output_dir, report):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "production-update-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (output_dir / "file-change-summary.json").write_text(
        json.dumps({"changed_files": report.get("changed_files", [])}, indent=2) + "\n", encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description="Safely prepare a manual incremental production update.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--apply-changes", action="store_true")
    parser.add_argument("--force-full-refresh", action="store_true")
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    report = {
        "executed_at": started.isoformat(),
        "mode": "apply" if args.apply_changes else "dry_run",
        "apply_changes": args.apply_changes,
        "force_full_refresh": args.force_full_refresh,
        "repository_writes": False,
        "commit_eligible": False,
        "data_changed": False,
        "changed_files": [],
        "applied_files": [],
        "errors": [],
    }
    try:
        with tempfile.TemporaryDirectory(prefix="portfolio-production-") as directory:
            workspace = Path(directory)
            temp_data = workspace / "data"
            shutil.copytree(ROOT / "data", temp_data)
            companies = read_json(temp_data / "companies.json", {"companies": []}).get("companies", [])
            active = [item for item in companies if item.get("status") == "active" and item.get("news_enabled", True)]
            config = load_pipeline_config()
            providers = {
                "naver": NaverIncrementalProvider(),
                "gdelt": GdeltIncrementalProvider(config["budgets"]["gdelt"]["request_delay_seconds"]),
            }
            batch_total = max(1, (len(active) + int(config["batch"]["batch_size"]) - 1) // int(config["batch"]["batch_size"]))

            def show_news_progress(item):
                print(f"NAVER batch {item['batch']}/{batch_total} complete", flush=True)
                print(f"GDELT batch {item['batch']}/{batch_total} complete", flush=True)

            print("External incremental collection started", flush=True)
            news = BatchNewsPipeline(temp_data, config, providers, progress_callback=show_news_progress).run(
                companies, now=datetime.now(timezone.utc), backfill=args.force_full_refresh,
            )
            print("Telegram stage started", flush=True)
            telegram = asyncio.run(run_telegram(
                data_root=temp_data,
                force_full_refresh=args.force_full_refresh,
                raise_on_error=False,
            ))
            print("Telegram stage complete", flush=True)
            checks = public_json_checks(temp_data)
            changed = changed_allowed_files(temp_data, ROOT / "data")
            disallowed = [path for path in changed if not is_allowed_repository_path(path)]
            external_ok = not news.get("severe_failure") and not telegram.get("errors")
            report.update({
                "news": sanitized_news_report(news),
                "telegram": sanitized_telegram_report(telegram),
                "generated_public_json": checks,
                "changed_files": changed,
                "data_changed": bool(changed),
                "disallowed_changes": disallowed,
                "commit_eligible": external_ok and not checks["findings"] and not disallowed,
            })
            print(f"Generated data validation complete: {checks['files_checked']} files", flush=True)
            print(f"Changed allowlisted files: {len(changed)}", flush=True)
            print(f"Commit eligible: {str(report['commit_eligible']).lower()}", flush=True)
            if args.apply_changes and report["commit_eligible"] and changed:
                report["applied_files"] = apply_files_atomically(workspace, ROOT, changed)
                report["repository_writes"] = True
            elif args.apply_changes and not report["commit_eligible"]:
                report["errors"].append({"type": "UpdateNotEligible"})
    except Exception as error:
        report["errors"].append({"type": type(error).__name__})
        report["commit_eligible"] = False
    report["duration_seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 3)
    write_report(args.output_dir, report)
    if report["errors"] or (args.apply_changes and not report["commit_eligible"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
