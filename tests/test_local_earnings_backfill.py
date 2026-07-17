import json
import tempfile
import unittest
from pathlib import Path

from scripts.backfill_local_earnings import (
    build_candidates,
    company_match_status,
    completion_status,
    detect_basis,
    legacy_quarter,
    message_record,
    metric_basis,
    missing_quarters,
    process,
    public_quarter,
    select_quarters,
    split_messages,
    with_comparisons,
)
from scripts.parse_awake_message import comparison_result, normalize_quarter, parse_amount


ROOT = Path(__file__).resolve().parents[1]
COMPANIES = {item["stock_code"]: item for item in json.loads((ROOT / "data" / "companies.json").read_text(encoding="utf-8"))["companies"]}


def synthetic_message(code="005930", company="삼성전자", provisional="N", corrected=False, quarter="2026 Q1"):
    correction = "정정공시\n" if corrected else ""
    return f"""Telegram message ID: 1001
기업명: {company}
종목코드: {code}
{correction}보고서명: 분기보고서 ({quarter})
실적기간: {quarter}
잠정실적: {provisional}
매출: 800억 / 790억
영업이익: 80억 / 75억
순이익: 40억 / 38억
최근 실적 추이
2024 Q2 100억 10억 5억
2024 Q3 200억 20억 10억
2024 Q4 300억 30억 15억
2025 Q1 400억 40억 20억
2025 Q2 500억 50억 25억
2025 Q3 600억 60억 30억
2025 Q4 700억 70억 35억
2026 Q1 800억 80억 40억
https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260718000001
"""


class LocalEarningsBackfillTests(unittest.TestCase):
    def test_folder_stock_code_matches_company(self):
        status, mismatches = company_match_status("005930", synthetic_message(), COMPANIES)
        self.assertEqual(status, "exact_match")
        self.assertEqual(mismatches, [])

    def test_leading_zero_is_preserved(self):
        record = message_record(synthetic_message(), COMPANIES["005930"], "sample.txt", "hash", 0)
        self.assertEqual(record["stock_code"], "005930")

    def test_multiple_messages_are_split_by_explicit_message_ids(self):
        combined = synthetic_message() + "\n---\n" + synthetic_message(provisional="Y", quarter="2026 Q2")
        messages, uncertain = split_messages(combined)
        self.assertEqual(len(messages), 2)
        self.assertFalse(uncertain)

    def test_duplicate_file_hash_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "005930"
            folder.mkdir()
            content = synthetic_message()
            (folder / "a.txt").write_text(content, encoding="utf-8")
            (folder / "b.txt").write_text(content, encoding="utf-8")
            report = process(root, apply=False)
        self.assertEqual(report["inventory"]["duplicate_file_count"], 1)
        self.assertEqual(report["summary"]["parsed_file_count"], 1)

    def test_money_units_are_normalized(self):
        self.assertEqual(parse_amount("1,788억")["value_won"], 178_800_000_000)
        self.assertEqual(parse_amount("2.3조")["value_won"], 2_300_000_000_000)
        self.assertEqual(parse_amount("125백만원")["value_won"], 125_000_000)
        self.assertEqual(parse_amount("300천원")["value_won"], 300_000)

    def test_parenthesized_amount_is_negative(self):
        self.assertEqual(parse_amount("(60억)")["value_won"], -6_000_000_000)

    def test_short_quarter_notation_is_supported(self):
        self.assertEqual(normalize_quarter("2025.1Q"), "2025 Q1")
        self.assertEqual(normalize_quarter("1Q25"), "2025 Q1")

    def test_cumulative_only_message_requires_review(self):
        text = synthetic_message().replace("최근 실적 추이", "누적 실적 추이")
        record = message_record(text, COMPANIES["005930"], "sample.txt", "hash", 0)
        self.assertTrue(record["cumulative_suspected"])

    def test_consolidated_and_separate_are_distinct(self):
        self.assertEqual(detect_basis("연결 재무제표"), ("consolidated", False))
        self.assertEqual(detect_basis("별도 재무제표"), ("separate", False))
        self.assertEqual(detect_basis("연결 및 별도"), ("mixed", True))

    def test_controlling_net_income_has_separate_basis(self):
        self.assertEqual(metric_basis("지배주주순이익 10억"), "controlling_net_income")
        self.assertEqual(metric_basis("당기순이익 10억"), "net_income")

    def test_final_result_beats_provisional(self):
        provisional = message_record(synthetic_message(provisional="Y"), COMPANIES["005930"], "p.txt", "p", 0)
        final = message_record(synthetic_message(provisional="N"), COMPANIES["005930"], "f.txt", "f", 1)
        selected, _, history = select_quarters([provisional, final])
        current = next(item for item in selected if item["fiscal_quarter"] == "2026 Q1")
        self.assertFalse(current["provisional"])
        self.assertGreaterEqual(next(item for item in history if item["fiscal_quarter"] == "2026 Q1")["candidate_count"], 2)

    def test_correction_beats_non_correction(self):
        normal = message_record(synthetic_message(), COMPANIES["005930"], "normal.txt", "a", 0)
        corrected = message_record(synthetic_message(corrected=True), COMPANIES["005930"], "corrected.txt", "b", 1)
        selected, _, _ = select_quarters([normal, corrected])
        current = next(item for item in selected if item["fiscal_quarter"] == "2026 Q1")
        self.assertTrue(current["corrected"])

    def test_conflicting_values_create_warning(self):
        first = message_record(synthetic_message(), COMPANIES["005930"], "a.txt", "a", 0)
        second_text = synthetic_message().replace("2026 Q1 800억 80억 40억", "2026 Q1 900억 90억 45억")
        second = message_record(second_text, COMPANIES["005930"], "b.txt", "b", 1)
        _, conflicts, _ = select_quarters([first, second])
        self.assertTrue(any(item["fiscal_quarter"] == "2026 Q1" for item in conflicts))

    def test_recent_eight_quarters_are_sorted(self):
        record = message_record(synthetic_message(), COMPANIES["005930"], "a.txt", "a", 0)
        selected, _, _ = select_quarters([record])
        self.assertEqual(len(selected), 8)
        self.assertEqual(selected[0]["fiscal_quarter"], "2024 Q2")
        self.assertEqual(selected[-1]["fiscal_quarter"], "2026 Q1")

    def test_missing_middle_quarter_is_detected(self):
        quarters = [{"fiscal_quarter": quarter} for quarter in ("2024 Q2", "2024 Q3", "2024 Q4", "2025 Q1", "2025 Q3", "2025 Q4", "2026 Q1")]
        self.assertIn("2025 Q2", missing_quarters(quarters))

    def test_partial_data_does_not_create_fake_quarters(self):
        quarters = [{"fiscal_quarter": "2026 Q1"}]
        status = completion_status(quarters, missing_quarters(quarters), [], False)
        self.assertEqual(status, "partial_1_to_4q")
        self.assertEqual(len(quarters), 1)

    def test_private_source_fields_are_not_public(self):
        record = message_record(synthetic_message(), COMPANIES["005930"], "secret.txt", "privatehash", 0)
        candidate = build_candidates(record)[0]
        public = public_quarter(candidate)
        serialized = json.dumps(public, ensure_ascii=False)
        self.assertNotIn("secret.txt", serialized)
        self.assertNotIn("privatehash", serialized)
        self.assertNotIn("Telegram message ID", serialized)

    def test_yoy_qoq_and_profit_transitions(self):
        quarters = []
        values = [100, 110, 120, 130, 150]
        for index, value in enumerate(values):
            quarters.append({
                "fiscal_quarter": f"{2024 + (index + 1) // 4} Q{(index + 1) % 4 + 1}",
                "revenue": value * 100_000_000,
                "operating_profit": value * 10_000_000,
                "net_income": value * 5_000_000,
            })
        enriched = with_comparisons(quarters)
        self.assertIsNotNone(enriched[-1]["comparisons"]["revenue"]["qoq"]["percentage"])
        self.assertIsNotNone(enriched[-1]["comparisons"]["revenue"]["yoy"]["percentage"])
        self.assertEqual(comparison_result(10, -10)["status"], "흑자전환")
        self.assertEqual(comparison_result(-10, 10)["status"], "적자전환")
        self.assertEqual(comparison_result(-5, -10)["status"], "적자축소")


if __name__ == "__main__":
    unittest.main()
