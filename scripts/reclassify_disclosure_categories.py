"""Safely normalize existing public disclosure categories without external collection."""

import argparse
from pathlib import Path

try:
    from .backfill_company import EARNINGS_CATEGORY, disclosure_category
    from .news_batch_pipeline import read_json, write_json_atomic
    from .onboard_portfolio import build_public_indexes
except ImportError:
    from backfill_company import EARNINGS_CATEGORY, disclosure_category
    from news_batch_pipeline import read_json, write_json_atomic
    from onboard_portfolio import build_public_indexes


ROOT = Path(__file__).resolve().parents[1]
LEGACY_EARNINGS_CATEGORIES = {"earnings", "performance", "실적"}


def canonical_category(record):
    current = record.get("category")
    has_earnings_data = current in LEGACY_EARNINGS_CATEGORIES
    return disclosure_category(record.get("reportName"), has_earnings_data)


def reclassify_disclosures(data_root):
    data_root = Path(data_root)
    changed_records = 0
    changed_files = []
    for path in sorted((data_root / "disclosures" / "by-company").glob("*.json")):
        payload = read_json(path, {}) or {}
        records = payload.get("disclosures", [])
        file_changed = False
        for record in records:
            category = canonical_category(record)
            if record.get("category") != category:
                record["category"] = category
                changed_records += 1
                file_changed = True
        if file_changed:
            write_json_atomic(path, payload)
            changed_files.append(path.name)
    return {"changed_records": changed_records, "changed_files": changed_files}


def rebuild_index(data_root):
    data_root = Path(data_root)
    companies = read_json(data_root / "companies.json", {"companies": []}).get("companies", [])
    active = [company for company in companies if company.get("status") == "active"]
    generated_at = (read_json(data_root / "disclosures" / "index.json", {}) or {}).get("generatedAt")
    build_public_indexes(active, generated_at, data_root=data_root)


def main():
    parser = argparse.ArgumentParser(description="Normalize public disclosure categories without external requests.")
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    result = reclassify_disclosures(args.data_root)
    rebuild_index(args.data_root)
    print(f"Reclassified disclosure records: {result['changed_records']}")
    print(f"Updated disclosure files: {len(result['changed_files'])}")


if __name__ == "__main__":
    main()
