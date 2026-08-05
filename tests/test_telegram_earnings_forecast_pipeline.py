import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.backfill_company import public_quarter
from scripts.backfill_portfolio_telegram import process_company
from scripts.parse_awake_message import merge_quarter_records, parse_awake_message
from scripts.telegram_incremental import route_message


ROOT = Path(__file__).resolve().parents[1]


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


def channel_format_message(company_name, stock_code, metric_lines, report_period=None, recent_rows=None):
    lines = [
        f"기업명: {company_name}(시가총액: 4,879억) A{stock_code}",
        "보고서명: 연결재무제표기준영업(잠정)실적(공정공시)",
    ]
    if report_period:
        lines.append(f"보고기간: {report_period}")
    lines.extend(("", *metric_lines, "", "**최근 실적 추이**"))
    lines.extend(recent_rows or ("2026.2Q 1,154억/ 54억/ 49억", "2026.1Q 1,748억/ 168억/ 253억"))
    return "\n".join(lines)


def marker_model(quarters):
    result = subprocess.run(
        [
            "node",
            "-e",
            """
            const fs = require('fs');
            const chart = require('./earnings-chart.js');
            const quarters = JSON.parse(fs.readFileSync(0, 'utf8'));
            process.stdout.write(JSON.stringify(chart.buildChartSeries(quarters)));
            """,
        ],
        cwd=ROOT,
        input=json.dumps(quarters),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


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

    def test_real_channel_format_regression_preserves_all_forecasts(self):
        # Sanitized to parser-relevant fields; links and message timestamp are not stored.
        text = channel_format_message("하나투어", "039130", (
            "매출액 : 1,154억(예상치 : 1,224억/ -6%)",
            "영업익 : 54억(예상치 : 58억/ -7%)",
            "순이익 : 49억(예상치 : 95억/ -48%)",
        ))
        parsed = parse_awake_message(text, telegram_message_id=9002)
        record, public = self.canonical_and_public(parsed)

        self.assertEqual(parsed["company_name"], "하나투어")
        self.assertEqual(parsed["stock_code"], "039130")
        self.assertEqual(record["fiscal_quarter"], "2026 Q2")
        self.assertEqual(
            (public["revenue"], public["estimateRevenue"], public["operatingIncome"], public["estimateOperatingIncome"], public["netIncome"], public["estimateNetIncome"]),
            (1154, 1224, 54, 58, 49, 95),
        )
        self.assertEqual(len(record["source_history"]), 1)
        self.assertEqual(record["source_history"][0]["revenue"]["value_won"], 115_400_000_000)

        model = marker_model([public])
        self.assertEqual(
            {item["key"]: item["data"] for item in model["forecastMarkers"]},
            {"revenue": [1224], "operatingIncome": [58], "netIncome": [95]},
        )

    def test_generic_channel_shapes_apply_without_company_specific_rules(self):
        cases = (
            ("임의기업A", "123451", ("매출액 : 100억(예상치 : 90억/ -10%)", "영업익 : 10억(예상치 : 9억/ -10%)", "순이익 : 8억(예상치 : 7억/ -12%)"), "2026.2Q 100억/ 10억/ 8억", (90, 9, 7)),
            ("임의기업B", "123452", ("매출 : 100억(예상치 : 90억/ -10%)", "영업이익 : 10억(예상치 : 9억/ -10%)", "당기순이익 : 8억(예상치 : 7억/ -12%)"), "2026.2Q 100억/ 10억/ 8억", (90, 9, 7)),
            ("임의기업C", "123453", ("매출액 : 100억(예상치 : 90억/ -10%)", "영업이익 : 10억", "순이익 : 8억"), "2026.2Q 100억/ 10억/ 8억", (90, None, None)),
            ("임의기업D", "123454", ("매출액 : 100억", "영업이익 : 10억", "순이익 : 8억"), "2026.2Q 100억/ 10억/ 8억", (None, None, None)),
            ("임의기업E", "123455", ("매출액 : 100억(예상치 : 90억/ -10%)", "영업이익 : -10억(예상치 : -12억/ 적자확대)", "순이익 : -8억(예상치 : -9억/ 적자확대)"), "2026.2Q 100억/ -10억/ -8억", (90, -12, -9)),
            ("임의기업F", "123456", ("매출액 : 1,200억원(예상치 : 1,100억/ -8%)", "영업익 : 60 억원(예상치 : 58억/ -3%)", "순이익 : 49억(예상치 : 50억원/ -2%)"), "2026.2Q 1,200억/ 60억/ 49억", (1100, 58, 50)),
        )
        for company_name, stock_code, metric_lines, latest_row, estimates in cases:
            with self.subTest(company_name=company_name):
                parsed = parse_awake_message(channel_format_message(company_name, stock_code, metric_lines, recent_rows=(latest_row,)))
                _, public = self.canonical_and_public(parsed)
                self.assertEqual(parsed["company_name"], company_name)
                self.assertEqual(parsed["stock_code"], stock_code)
                self.assertEqual(
                    (public["estimateRevenue"], public["estimateOperatingIncome"], public["estimateNetIncome"]),
                    estimates,
                )

    def test_non_portfolio_fixture_is_routed_away_from_public_data(self):
        companies = json.loads((ROOT / "data" / "companies.json").read_text(encoding="utf-8"))["companies"]
        text = channel_format_message("하나투어", "039130", (
            "매출액 : 1,154억(예상치 : 1,224억/ -6%)",
            "영업익 : 54억(예상치 : 58억/ -7%)",
            "순이익 : 49억(예상치 : 95억/ -48%)",
        ))
        self.assertNotIn("039130", {item["stock_code"] for item in companies})
        assignments, quarantine = route_message({"id": 9002, "text": text}, companies)
        self.assertEqual(assignments, [])
        self.assertEqual(quarantine[0]["reason"], "code_not_in_portfolio")

    def test_dynamic_portfolio_company_reaches_public_model_and_markers(self):
        companies = json.loads((ROOT / "data" / "companies.json").read_text(encoding="utf-8"))["companies"]
        company = next(item for item in companies if item.get("status") == "active")
        text = channel_format_message(company["company_name"], company["stock_code"], (
            "매출액 : 1,154억(예상치 : 1,224억/ -6%)",
            "영업익 : 54억(예상치 : 58억/ -7%)",
            "순이익 : 49억(예상치 : 95억/ -48%)",
        ))
        assignments, quarantine = route_message({"id": 9003, "text": text}, companies)
        self.assertEqual(assignments, [company["stock_code"]])
        self.assertEqual(quarantine, [])

        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory) / "data"
            result = process_company(
                company,
                [{"id": 9003, "date": "2026-08-05T16:40:56+09:00", "text": text}],
                "2026-08-05T16:40:56+09:00",
                data_root=data_root,
            )
            payload = json.loads((data_root / "earnings" / "by-company" / f"{company['stock_code']}.json").read_text(encoding="utf-8"))
            public = next(item for item in payload["company"]["earnings"] if item["period"] == "2026 Q2")
            self.assertEqual(result["new_quarters"], len(payload["company"]["earnings"]))
            self.assertEqual(
                (public["estimateRevenue"], public["estimateOperatingIncome"], public["estimateNetIncome"]),
                (1224, 58, 95),
            )
            model = marker_model([public])
            self.assertEqual(len(model["forecastMarkers"]), 3)
            self.assertEqual([item["key"] for item in model["actualBars"]], ["revenue", "operatingIncome", "netIncome"])


if __name__ == "__main__":
    unittest.main()
