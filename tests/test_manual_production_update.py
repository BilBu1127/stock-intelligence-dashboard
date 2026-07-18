import json
import tempfile
import unittest
from pathlib import Path

from scripts.manual_production_update import (
    apply_files_atomically,
    changed_allowed_files,
    is_allowed_repository_path,
    portfolio_integrity_checks,
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

    def test_integrity_rejects_cross_company_message_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = self._integrity_fixture(Path(directory))
            for code in ("005930", "035420"):
                path = data_root / "disclosures" / "by-company" / f"{code}.json"
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["disclosures"] = [{"code": code, "telegramMessageId": 99}]
                path.write_text(json.dumps(payload), encoding="utf-8")
            findings = portfolio_integrity_checks(data_root)["findings"]
            self.assertTrue(any(item["type"] == "cross_company_telegram_message_duplicate" for item in findings))

    def test_integrity_rejects_record_code_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = self._integrity_fixture(Path(directory))
            path = data_root / "disclosures" / "by-company" / "035420.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["disclosures"] = [{"code": "005930", "telegramMessageId": 100}]
            path.write_text(json.dumps(payload), encoding="utf-8")
            findings = portfolio_integrity_checks(data_root)["findings"]
            self.assertTrue(any(item["type"] == "record_company_code_mismatch" for item in findings))

    def test_integrity_rejects_unexpected_company_file(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = self._integrity_fixture(Path(directory))
            path = data_root / "news" / "by-company" / "999999.json"
            path.write_text(json.dumps({"stock_code": "999999", "news": []}), encoding="utf-8")
            findings = portfolio_integrity_checks(data_root)["findings"]
            self.assertTrue(any(item["type"] == "unexpected_company_detail" for item in findings))

    @staticmethod
    def _integrity_fixture(root):
        data_root = root / "data"
        codes = ("005930", "035420")
        companies = [{"stock_code": code, "status": "active"} for code in codes]
        data_root.mkdir()
        (data_root / "companies.json").write_text(json.dumps({"companies": companies}), encoding="utf-8")
        for group in ("news", "earnings", "disclosures"):
            detail_dir = data_root / group / "by-company"
            detail_dir.mkdir(parents=True)
            for code in codes:
                if group == "news":
                    payload = {"stock_code": code, "news": []}
                elif group == "earnings":
                    payload = {"company": {"code": code, "earnings": []}}
                else:
                    payload = {"stockCode": code, "disclosures": []}
                (detail_dir / f"{code}.json").write_text(json.dumps(payload), encoding="utf-8")
            if group == "news":
                index = {"companies": [{"stock_code": code} for code in codes]}
            elif group == "earnings":
                index = {
                    "companies": [{"code": code} for code in codes],
                    "watchlist": [{"code": code} for code in codes],
                }
            else:
                index = {"companies": [{"stockCode": code} for code in codes]}
            (data_root / group / "index.json").write_text(json.dumps(index), encoding="utf-8")
        return data_root


if __name__ == "__main__":
    unittest.main()
