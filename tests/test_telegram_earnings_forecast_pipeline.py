import unittest

from scripts.backfill_company import public_quarter
from scripts.parse_awake_message import merge_quarter_records, parse_awake_message


def earnings_message(*lines, company_name="가상테스트", stock_code="000001"):
    return "\n".join((
        f"기업명: {company_name}",
        f"종목코드: {stock_code}",
        "보고서명: 연결재무제표기준영업(잠정)실적 (2026.06)",
        "보고기간: 2026.06",
        *lines,
    ))


def amount_value(parsed, field):
    amount = parsed.get(field)
    return amount.get("value_won") if amount else None


class TelegramEarningsForecastPipelineTests(unittest.TestCase):
    def parse(self, *lines, **kwargs):
        return parse_awake_message(earnings_message(*lines, **kwargs), telegram_message_id=9001)

    def canonical_and_public(self, parsed):
        records, warnings = merge_quarter_records([parsed])
        self.assertEqual(warnings, [])
        record = next(item for item in records if item["fiscal_quarter"] == "2026 Q2")
        return record, public_quarter(record)

    def assert_estimates(self, parsed, revenue=None, operating=None, net_income=None):
        self.assertEqual(amount_value(parsed, "revenue_consensus"), revenue)
        self.assertEqual(amount_value(parsed, "operating_profit_consensus"), operating)
        self.assertEqual(amount_value(parsed, "net_income_consensus"), net_income)

    def test_case_a_all_actual_and_forecast_values_are_preserved(self):
        parsed = self.parse(
            "매출액: 1,200억원 (예상 1,100억원)",
            "영업이익: 150억원 (컨센서스 140억원)",
            "순이익: 90억원 (시장 예상 80억원)",
        )
        self.assertEqual(amount_value(parsed, "revenue_actual"), 120_000_000_000)
        self.assertEqual(amount_value(parsed, "operating_profit_actual"), 15_000_000_000)
        self.assertEqual(amount_value(parsed, "net_income_actual"), 9_000_000_000)
        self.assert_estimates(parsed, 110_000_000_000, 14_000_000_000, 8_000_000_000)

    def test_case_b_revenue_only_forecast_on_a_separate_line(self):
        parsed = self.parse(
            "매출액: 1,200억원",
            "매출액 예상: 1,100억원",
            "영업이익: 150억원",
            "순이익: 90억원",
        )
        self.assert_estimates(parsed, 110_000_000_000)

    def test_case_c_operating_forecast_with_prefix_label(self):
        parsed = self.parse(
            "매출액: 1,200억원",
            "영업이익: -20억원",
            "예상 영업이익: -25억원",
            "순이익: 90억원",
        )
        self.assert_estimates(parsed, operating=-2_500_000_000)

    def test_case_d_net_income_forecast_with_parenthesized_label(self):
        parsed = self.parse(
            "매출액: 1,200억원",
            "영업이익: 150억원",
            "순익(예상치): 80억원",
            "순익: 90억원",
        )
        self.assert_estimates(parsed, net_income=8_000_000_000)

    def test_case_e_missing_forecasts_stay_null(self):
        parsed = self.parse("매출액: 1,200억원", "영업이익: 150억원", "순이익: 90억원")
        self.assert_estimates(parsed)
        _, public = self.canonical_and_public(parsed)
        self.assertIsNone(public["estimateRevenue"])
        self.assertIsNone(public["estimateOperatingIncome"])
        self.assertIsNone(public["estimateNetIncome"])

    def test_case_f_negative_forecasts_preserve_their_sign(self):
        parsed = self.parse(
            "매출액: 1,200억원",
            "영업이익: -20억원 (예상 -25억원)",
            "순이익: -30억원 (컨센서스 -40억원)",
        )
        self.assert_estimates(parsed, operating=-2_500_000_000, net_income=-4_000_000_000)

    def test_case_g_and_h_commas_and_mixed_units_are_normalized(self):
        parsed = self.parse(
            "매출액: 1.25조원 (예상 12,400억원)",
            "영업이익: 850백만원 (예상 900백만원)",
            "순이익: -3천원 (예상 -4천원)",
        )
        self.assertEqual(amount_value(parsed, "revenue_actual"), 1_250_000_000_000)
        self.assert_estimates(parsed, 1_240_000_000_000, 900_000_000, -4_000)

    def test_case_i_cumulative_rows_do_not_replace_single_quarter_values(self):
        parsed = self.parse(
            "누적 매출액: 2조원",
            "매출액(누적): 2조원",
            "매출액: 1,200억원 (예상 1,100억원)",
            "영업이익: 150억원 (예상 140억원)",
            "순이익: 90억원 (예상 80억원)",
            "2026 2Q 1,200억원 150억원 90억원",
        )
        self.assertEqual(amount_value(parsed, "revenue_actual"), 120_000_000_000)
        self.assert_estimates(parsed, 110_000_000_000, 14_000_000_000, 8_000_000_000)

    def test_case_j_actual_and_forecast_order_can_be_reversed(self):
        parsed = self.parse(
            "매출액: 예상 900억원, 실제 1,000억원",
            "영업이익: 예상 90억원, 실제 100억원",
            "순이익: 예상 70억원, 실제 80억원",
        )
        self.assertEqual(amount_value(parsed, "revenue_actual"), 100_000_000_000)
        self.assert_estimates(parsed, 90_000_000_000, 9_000_000_000, 7_000_000_000)

    def test_case_k_compact_parenthesized_forecasts_are_positive(self):
        parsed = self.parse(
            "매출액: 1,000억원 (900억원)",
            "영업이익: 100억원 (90억원)",
            "순이익: 80억원 (70억원)",
        )
        self.assert_estimates(parsed, 90_000_000_000, 9_000_000_000, 7_000_000_000)

    def test_case_l_consensus_comparison_without_a_number_does_not_infer_forecast(self):
        parsed = self.parse(
            "매출액: 1,000억원 (컨센서스 대비 +10%)",
            "영업이익: 100억원",
            "순이익: 80억원",
        )
        self.assert_estimates(parsed)

    def test_parser_to_canonical_to_public_json_preserves_estimate_fields(self):
        parsed = self.parse(
            "매출액: 1,200억원 (예상 1,100억원)",
            "영업이익: 150억원 (예상 140억원)",
            "순이익: 90억원 (예상 80억원)",
        )
        record, public = self.canonical_and_public(parsed)
        self.assertEqual(record["revenue_consensus"]["value_won"], 110_000_000_000)
        self.assertEqual(public["period"], "2026 Q2")
        self.assertEqual(public["estimateRevenue"], 1100)
        self.assertEqual(public["estimateOperatingIncome"], 140)
        self.assertEqual(public["estimateNetIncome"], 80)
        self.assertEqual(public["sourceAmounts"]["estimateRevenue"]["valueWon"], 110_000_000_000)

    def test_forecast_pipeline_has_no_company_hardcoding(self):
        parsed = self.parse(
            "매출액: 100억원 (예상 90억원)",
            "영업이익: 10억원 (예상 9억원)",
            "순이익: 8억원 (예상 7억원)",
            company_name="임의기업",
            stock_code="123456",
        )
        record, public = self.canonical_and_public(parsed)
        self.assertEqual(parsed["stock_code"], "123456")
        self.assertEqual(record["fiscal_quarter"], "2026 Q2")
        self.assertEqual(public["estimateRevenue"], 90)


if __name__ == "__main__":
    unittest.main()
