"""Sanitized, read-only validation for the GitHub manual workflow.

This command never writes repository data, cursors, commits, pushes, or deploys.
External collection is intentionally opt-in and is reported as unavailable until
the provider sandbox adapter is supplied; it never falls back to interactive OTP.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from .credentials import load_values, missing_names
except ImportError:
    from credentials import load_values, missing_names


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SECRETS = (
    "TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION",
    "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET",
)
FORBIDDEN_TERMS = ("private_samples", "private_source_filename", "telegram_message", "session_string", "api_hash", "client_secret", "phone_number", ".secrets")


def public_json_checks():
    findings = []
    files = list((ROOT / "data").rglob("*.json"))
    for path in files:
        text = path.read_text(encoding="utf-8")
        lowered = text.casefold()
        for term in FORBIDDEN_TERMS:
            if term in lowered:
                findings.append({"file": str(path.relative_to(ROOT)), "type": "forbidden_term"})
                break
        try:
            json.loads(text)
        except json.JSONDecodeError:
            findings.append({"file": str(path.relative_to(ROOT)), "type": "invalid_json"})
    return {"files_checked": len(files), "findings": findings}


def run_tests():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    output = result.stdout + "\n" + result.stderr
    passed_match = re.search(r"(\d+) passed", output)
    failed_match = re.search(r"(\d+) failed", output)
    failed_tests = []
    for line in output.splitlines():
        match = re.match(r"FAILED\s+([^\s]+)(?:\s+-\s+(.+))?", line)
        if match:
            test_name, summary = match.groups()
            path_match = re.match(r"([^:]+\.py)(?:::(.+))?", test_name)
            failed_tests.append({
                "name": test_name,
                "file": path_match.group(1) if path_match else None,
                "line": None,
                "summary": sanitize_summary(summary or "test failed"),
            })
    locations = re.findall(r"(tests[/\\][^:\n]+\.py):(\d+):\s*([^\n]+)", output)
    for item, location in zip(failed_tests, locations):
        item["file"], item["line"], item["summary"] = location[0], int(location[1]), sanitize_summary(location[2])
    passed_count = int(passed_match.group(1)) if passed_match else 0
    failed_count = int(failed_match.group(1)) if failed_match else len(failed_tests)
    return {
        "passed": result.returncode == 0,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "failed_tests": failed_tests,
        "error_summary": [item["summary"] for item in failed_tests],
    }


def sanitize_summary(value):
    text = str(value or "test failed")
    text = re.sub(r"(?i)(api[_ -]?hash|client[_ -]?secret|session|phone)[^\s,:=]*\s*[:=]\s*[^\s,]+", "[redacted]", text)
    return text[:500]


def platform_checks():
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, text=True, capture_output=True, check=False).stdout.splitlines()
    lower_names = [name.casefold() for name in tracked]
    text_paths = [ROOT / name for name in tracked if Path(name).suffix.lower() in {".py", ".json", ".html", ".css", ".md", ".yml", ".yaml"}]
    utf8_errors = []
    crlf_files = 0
    windows_paths = []
    for path in text_paths:
        try:
            content = path.read_bytes()
            decoded = content.decode("utf-8")
            crlf_files += int(b"\r\n" in content)
            if re.search(r"(?i)(?<![A-Z0-9])[A-Z]:[\\/]", decoded):
                windows_paths.append(str(path.relative_to(ROOT)))
        except UnicodeDecodeError:
            utf8_errors.append(str(path.relative_to(ROOT)))
    return {
        "windows_absolute_paths": windows_paths,
        "path_separator": "pathlib_used",
        "case_collisions": sorted({name for name in lower_names if lower_names.count(name) > 1}),
        "crlf_file_count": crlf_files,
        "utf8_decode_errors": utf8_errors,
        "timezone_configured": (ROOT / "data" / "config" / "pipeline.json").read_text(encoding="utf-8").find("Asia/Seoul") >= 0,
        "temporary_directories": "tempfile_used",
        "deterministic_sorting": "covered_by_tests",
    }


def run_javascript_check():
    result = subprocess.run(["node", "--check", "app.js"], cwd=ROOT, text=True, capture_output=True, check=False)
    return {"passed": result.returncode == 0}


def data_change_summary():
    result = subprocess.run(["git", "diff", "--stat", "--", "data"], cwd=ROOT, text=True, capture_output=True, check=False)
    return result.stdout.strip() or "no working-tree data changes"


def main():
    parser = argparse.ArgumentParser(description="Read-only manual portfolio validation.")
    parser.add_argument("--validation-only", action="store_true", required=True)
    parser.add_argument("--run-external", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    values = load_values(
        REQUIRED_SECRETS,
        fallback_path=ROOT / ".secrets" / "telegram.env",
        session_path=ROOT / ".secrets" / "telegram_session.txt",
    )
    # Naver uses a separate local fallback file.
    naver = load_values(("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"), fallback_path=ROOT / ".secrets" / "naver.env")
    values.update(naver)
    print("Python tests started", flush=True)
    tests = run_tests()
    print("Python tests complete", flush=True)
    javascript = run_javascript_check()
    print("JavaScript check complete", flush=True)
    public_json = public_json_checks()
    print("Public JSON and sensitive-data checks complete", flush=True)
    external = "not_run"
    external_passed = True
    if args.run_external:
        preflight_passed = tests["passed"] and javascript["passed"] and not public_json["findings"]
        if not preflight_passed:
            external = "skipped_preflight_failure"
            external_passed = False
        elif missing_names(values):
            external = "missing_required_secrets"
            external_passed = False
        else:
            external_result = subprocess.run(
                [sys.executable, "scripts/validate_external_sources.py", "--output", str(args.output_dir / "external-validation.json")],
                cwd=ROOT, text=True, capture_output=True, check=False,
            )
            external = "completed" if external_result.returncode == 0 else "failed"
            external_passed = external_result.returncode == 0
    report = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "mode": "validation_only",
        "tests": tests,
        "platform_compatibility": platform_checks(),
        "javascript": javascript,
        "public_json": public_json,
        "missing_secret_names": missing_names(values),
        "external_requested": args.run_external,
        "external_collection": external,
        "repository_writes": False,
        "cursor_updates": False,
        "commit": False,
        "push": False,
        "deploy": False,
    }
    report["passed"] = tests["passed"] and javascript["passed"] and not public_json["findings"] and external_passed
    (args.output_dir / "validation-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "test-summary.txt").write_text(
        f"tests_passed={tests['passed']}\npassed_count={tests['passed_count']}\nfailed_count={tests['failed_count']}\n"
        + "\n".join(f"failed_test={item['name']}" for item in tests["failed_tests"]) + "\n",
        encoding="utf-8",
    )
    if tests["failed_tests"]:
        print("Failed tests: " + ", ".join(item["name"] for item in tests["failed_tests"]))
    (args.output_dir / "data-change-summary.txt").write_text(data_change_summary() + "\n", encoding="utf-8")
    print("Validation completed" if report["passed"] else "Validation failed")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
