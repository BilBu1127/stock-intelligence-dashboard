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
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    match = re.search(r"Ran (\d+) tests", result.stdout + result.stderr)
    return {"passed": result.returncode == 0, "count": int(match.group(1)) if match else None}


def run_javascript_check():
    result = subprocess.run(["node", "--check", "app.js"], cwd=ROOT, text=True, capture_output=True, check=False)
    return {"passed": result.returncode == 0}


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
    tests = run_tests()
    javascript = run_javascript_check()
    public_json = public_json_checks()
    external = "not_run"
    external_passed = True
    if args.run_external:
        if missing_names(values):
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
    (args.output_dir / "test-summary.txt").write_text(f"tests_passed={tests['passed']}\ntests_count={tests['count']}\n", encoding="utf-8")
    print("Validation completed" if report["passed"] else "Validation failed")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
