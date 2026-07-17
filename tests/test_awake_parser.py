import unittest

from scripts.parse_awake_message import (
    classify_message,
    comparison_result,
    merge_quarter_records,
    parse_amount,
    parse_awake_message,
)


BASE_MESSAGE = """[동원금속] 사업보고서 (2026.03)
기업명: 동원금속
종목코드: 018500
공시 시각: 2026-06-19 17:55:54
보고서명: 사업보고서 (2026.03)
잠정실적: N
매출액: 1,788억
영업이익: 60억
순이익: 130억
최근 실적 추이
2026.1Q 1,788억 60억 130억
2025.4Q 1,571억 74억 106억
https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260619000676
"""


class AwakeParserTests(unittest.TestCase):
    def test_parses_synthetic_dongwon_message(self):
        parsed = parse_awake_message(BASE_MESSAGE, telegram_message_id=101)
        self.assertEqual(parsed["company_name"], "동원금속")
        self.assertEqual(parsed["stock_code"], "018500")
        self.assertEqual(parsed["report_period"], "2026.03")
        self.assertFalse(parsed["provisional"])
        self.assertEqual(parsed["revenue_actual"]["value_won"], 178_800_000_000)
        self.assertEqual(parsed["dart_receipt_number"], "20260619000676")

    def test_normalizes_company_name_with_metadata(self):
        parsed = parse_awake_message(
            "기업명: 동원금속(시가총액: 634억) A018500\n보고서명: 배당결정",
            default_company_name="동원금속",
            default_stock_code="018500",
        )
        self.assertEqual(parsed["company_name"], "동원금속")

    def test_converts_eok(self):
        self.assertEqual(parse_amount("1,788억")["value_won"], 178_800_000_000)

    def test_converts_jo(self):
        self.assertEqual(parse_amount("2.3조")["value_won"], 2_300_000_000_000)

    def test_converts_negative_amount(self):
        self.assertEqual(parse_amount("-60억")["value_won"], -6_000_000_000)

    def test_handles_missing_estimate(self):
        parsed = parse_awake_message("매출액: 1,000억 (-)\n영업이익: 10억\n순이익: N/A")
        self.assertIsNone(parsed["revenue_consensus"]["value_won"])
        self.assertIsNone(parsed["operating_profit_consensus"])
        self.assertIsNone(parsed["net_income_actual"]["value_won"])

    def test_handles_spacing_and_windows_newlines(self):
        text = "매출액 : 60 억\r\n영업익: -  \r\n순익 : -60억"
        parsed = parse_awake_message(text)
        self.assertEqual(parsed["revenue_actual"]["value_won"], 6_000_000_000)
        self.assertIsNone(parsed["operating_profit_actual"]["value_won"])
        self.assertEqual(parsed["net_income_actual"]["value_won"], -6_000_000_000)

    def test_parses_multiple_recent_quarters(self):
        parsed = parse_awake_message(BASE_MESSAGE)
        self.assertEqual(
            [item["fiscal_quarter"] for item in parsed["recent_earnings"]],
            ["2026 Q1", "2025 Q4"],
        )

    def test_deduplicates_same_quarter_values(self):
        first = parse_awake_message(BASE_MESSAGE, telegram_message_id=101, message_datetime="2026-06-19T17:55:54+09:00")
        second = parse_awake_message(BASE_MESSAGE, telegram_message_id=102, message_datetime="2026-06-20T17:55:54+09:00")
        quarters, warnings = merge_quarter_records([first, second])
        q1 = next(item for item in quarters if item["fiscal_quarter"] == "2026 Q1")
        self.assertEqual(len(q1["source_history"]), 1)
        self.assertEqual(q1["source_history"][0]["telegram_message_ids"], [102, 101])
        self.assertEqual(warnings, [])

    def test_final_earnings_override_newer_provisional(self):
        final_text = BASE_MESSAGE.replace("잠정실적: N", "잠정실적: N").replace("1,788억", "1,700억")
        provisional_text = BASE_MESSAGE.replace("잠정실적: N", "잠정실적: Y")
        final = parse_awake_message(final_text, telegram_message_id=201, message_datetime="2026-06-19T10:00:00+09:00")
        provisional = parse_awake_message(provisional_text, telegram_message_id=202, message_datetime="2026-06-20T10:00:00+09:00")
        quarters, warnings = merge_quarter_records([final, provisional])
        q1 = next(item for item in quarters if item["fiscal_quarter"] == "2026 Q1")
        self.assertEqual(q1["status"], "final")
        self.assertEqual(q1["telegram_message_id"], 201)
        self.assertEqual(len(warnings), 1)

    def test_preserves_correction_in_history(self):
        correction_text = "정정공시\n" + BASE_MESSAGE
        parsed = parse_awake_message(correction_text, telegram_message_id=301)
        quarters, _ = merge_quarter_records([parsed])
        self.assertEqual(classify_message(correction_text), "correction")
        self.assertTrue(quarters[-1]["source_history"][0]["correction"])

    def test_loss_to_profit_status(self):
        result = comparison_result(6_000_000_000, -2_000_000_000)
        self.assertEqual(result["status"], "흑자전환")
        self.assertIsNone(result["percentage"])

    def test_parse_failure_returns_null(self):
        parsed = parse_awake_message("매출액: 확인 중\n영업이익: 확인 중\n순이익: 확인 중")
        self.assertIsNone(parsed["revenue_actual"])
        self.assertIsNone(parsed["operating_profit_actual"])
        self.assertIsNone(parsed["net_income_actual"])
        self.assertFalse(parsed["has_earnings_data"])


if __name__ == "__main__":
    unittest.main()
