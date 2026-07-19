import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.backfill_company import disclosure_category
from scripts.reclassify_disclosure_categories import reclassify_disclosures


ROOT = Path(__file__).resolve().parents[1]


def node_category(script):
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class EarningsDisclosureClassificationTests(unittest.TestCase):
    def test_consolidated_provisional_earnings_is_earnings(self):
        self.assertEqual(disclosure_category("연결재무제표기준영업(잠정)실적(공정공시)"), "earnings")

    def test_provisional_earnings_is_earnings(self):
        self.assertEqual(disclosure_category("영업(잠정)실적(공정공시)"), "earnings")

    def test_profit_structure_change_is_earnings(self):
        self.assertEqual(disclosure_category("매출액또는손익구조30%이상변경"), "earnings")

    def test_contract_is_not_earnings(self):
        self.assertEqual(disclosure_category("단일판매ㆍ공급계약체결"), "공급계약")

    def test_clinical_trial_is_not_earnings(self):
        self.assertEqual(disclosure_category("임상시험계획승인신청"), "기타")

    def test_financial_report_needs_structured_earnings_support(self):
        self.assertEqual(disclosure_category("분기보고서 (2026.03)", True), "earnings")
        self.assertEqual(disclosure_category("분기보고서 (2026.03)", False), "기타")


class EarningsDisclosureReclassificationTests(unittest.TestCase):
    def test_reclassification_changes_only_categories_and_not_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            disclosure_path = root / "disclosures" / "by-company" / "000001.json"
            cursor_path = root / "state" / "telegram-cursor.json"
            disclosure_path.parent.mkdir(parents=True)
            cursor_path.parent.mkdir(parents=True)
            original = {
                "stockCode": "000001",
                "disclosures": [{
                    "reportName": "연결재무제표기준영업(잠정)실적(공정공시)", "category": "기타",
                    "telegramMessageId": 1, "disclosedAt": "2026-07-01T09:00:00+09:00",
                    "dartUrl": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260701000001",
                }],
            }
            disclosure_path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
            cursor_path.write_text('{"last_processed_message_id": 147069}', encoding="utf-8")
            cursor_before = cursor_path.read_bytes()

            result = reclassify_disclosures(root)
            updated = json.loads(disclosure_path.read_text(encoding="utf-8"))

            self.assertEqual(result["changed_records"], 1)
            self.assertEqual(updated["disclosures"][0]["category"], "earnings")
            self.assertEqual(updated["disclosures"][0]["telegramMessageId"], 1)
            self.assertEqual(updated["disclosures"][0]["dartUrl"], original["disclosures"][0]["dartUrl"])
            self.assertEqual(cursor_path.read_bytes(), cursor_before)

    def test_public_index_uses_canonical_earnings_and_ui_filter_value(self):
        index = json.loads((ROOT / "data" / "disclosures" / "index.json").read_text(encoding="utf-8"))
        earnings = [item for item in index["disclosures"] if item["category"] == "earnings"]
        self.assertIn("earnings", index["categories"])
        self.assertNotIn("실적", index["categories"])
        self.assertEqual(len(earnings), 2)
        self.assertTrue(all(item["category"] == "earnings" for item in earnings))
        legacy = json.loads((ROOT / "data" / "disclosures" / "by-company" / "018500.json").read_text(encoding="utf-8"))
        self.assertEqual(
            next(item for item in legacy["disclosures"] if item["reportName"].startswith("사업보고서"))["category"],
            "earnings",
        )
        self.assertEqual(
            node_category("const u=require('./disclosure-category.js'); process.stdout.write(String(u.matches({category:'earnings'}, 'earnings')));"),
            "true",
        )
        self.assertEqual(
            node_category("const u=require('./disclosure-category.js'); process.stdout.write(String(u.matches({category:'공급계약'}, 'earnings')));"),
            "false",
        )

    def test_all_filter_keeps_all_existing_disclosures(self):
        index = json.loads((ROOT / "data" / "disclosures" / "index.json").read_text(encoding="utf-8"))
        all_records = index["disclosures"]
        self.assertEqual(len(all_records), sum(1 for item in all_records if item.get("category")))

if __name__ == "__main__":
    unittest.main()
