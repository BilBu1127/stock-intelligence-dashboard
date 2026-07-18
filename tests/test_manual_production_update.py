import json
import tempfile
import unittest
from pathlib import Path

from scripts.manual_production_update import (
    apply_files_atomically,
    changed_allowed_files,
    is_allowed_repository_path,
    public_json_checks,
)


class ManualProductionUpdateTests(unittest.TestCase):
    def test_repository_allowlist_accepts_only_public_data_and_cursors(self):
        self.assertTrue(is_allowed_repository_path("data/news/index.json"))
        self.assertTrue(is_allowed_repository_path("data/earnings/by-company/000660.json"))
        self.assertTrue(is_allowed_repository_path("data/state/news-cursors.json"))
        self.assertFalse(is_allowed_repository_path("data/companies.json"))
        self.assertFalse(is_allowed_repository_path(".secrets/naver.env"))

    def test_atomic_apply_rejects_disallowed_path(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            with self.assertRaises(ValueError):
                apply_files_atomically(source, target, ["data/companies.json"])

    def test_changed_files_are_limited_to_allowlisted_outputs(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            source_data = Path(source) / "data"
            target_data = Path(target) / "data"
            for root in (source_data, target_data):
                path = root / "news" / "index.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"news": []}), encoding="utf-8")
            (source_data / "news" / "index.json").write_text(json.dumps({"news": [{"id": 1}]}), encoding="utf-8")
            self.assertEqual(changed_allowed_files(source_data, target_data), ["data/news/index.json"])

    def test_public_json_check_rejects_private_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory) / "data"
            for group in ("news", "earnings", "disclosures"):
                (data_root / group / "by-company").mkdir(parents=True)
                (data_root / group / "index.json").write_text("{}", encoding="utf-8")
            (data_root / "news" / "by-company" / "000660.json").write_text(
                json.dumps({"description": "not public"}), encoding="utf-8",
            )
            findings = public_json_checks(data_root)["findings"]
            self.assertTrue(any(item["type"] == "forbidden_key" for item in findings))


if __name__ == "__main__":
    unittest.main()
