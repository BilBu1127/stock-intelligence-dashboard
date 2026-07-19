import json
import tempfile
import unittest
from pathlib import Path

from scripts.backfill_portfolio_telegram import process_company
from scripts.parse_awake_message import parse_awake_message
from scripts.telegram_incremental import distribute_messages_with_quarantine, route_message


COMPANIES = [
    {"company_name": "NAVER", "stock_code": "035420", "aliases": ["NAVER", "네이버"], "telegram_match_requires_code": True},
    {"company_name": "삼성전자", "stock_code": "005930", "aliases": ["삼성전자"]},
    {"company_name": "현대차", "stock_code": "005380", "aliases": ["현대차", "현대자동차"]},
    {"company_name": "한국항공우주", "stock_code": "047810", "aliases": ["한국항공우주", "KAI"]},
    {"company_name": "신성이엔지", "stock_code": "011930", "aliases": ["신성이엔지"]},
    {"company_name": "기가레인", "stock_code": "049080", "aliases": ["기가레인"]},
]


def message(text, message_id=1):
    return {"id": message_id, "date": "2026-07-18T10:00:00+09:00", "text": text}


class TelegramRoutingSafetyTests(unittest.TestCase):
    def test_finance_naver_url_does_not_route_to_naver(self):
        assignments, _ = route_message(message(
            "회사명: 삼성전자\n종목코드: 005930\n회사정보: https://finance.naver.com/item/main.nhn?code=005930"
        ), COMPANIES)
        self.assertEqual(assignments, ["005930"])

    def test_real_naver_company_field_with_code_routes_normally(self):
        assignments, quarantine = route_message(message(
            "회사명: NAVER\n종목코드: 035420\n회사정보: https://finance.naver.com/item/main.nhn?code=035420"
        ), COMPANIES)
        self.assertEqual(assignments, ["035420"])
        self.assertEqual(quarantine, [])

    def test_main_nhn_path_is_not_a_naver_match(self):
        assignments, _ = route_message(message("회사정보: https://example.com/main.nhn?page=NAVER"), COMPANIES)
        self.assertNotIn("035420", assignments)

    def test_hyundai_securities_is_not_partial_hyundai_match(self):
        assignments, _ = route_message(message("회사명: LS증권\n원고명: 현대차증권"), COMPANIES)
        self.assertNotIn("005380", assignments)

    def test_contract_counterparty_does_not_override_explicit_code(self):
        assignments, _ = route_message(message(
            "회사명: 신성이엔지\n종목코드: 011930\n계약상대방: 삼성전자"
        ), COMPANIES)
        self.assertEqual(assignments, ["011930"])

    def test_research_institute_is_not_partial_kai_match(self):
        assignments, _ = route_message(message("회사명: 기가레인\n연구원: 한국항공우주연구원"), COMPANIES)
        self.assertEqual(assignments, ["049080"])

    def test_explicit_code_routes_to_only_one_company(self):
        assignments, _ = route_message(message(
            "회사명: 신성이엔지\n종목코드: 011930\n삼성전자와 NAVER가 본문에 등장"
        ), COMPANIES)
        self.assertEqual(assignments, ["011930"])

    def test_parser_accepts_0009k0(self):
        parsed = parse_awake_message("회사명: 에임드바이오\n종목코드: 0009K0")
        self.assertEqual(parsed["stock_code"], "0009K0")
        self.assertTrue(parsed["explicitCodeFound"])

    def test_parser_accepts_0008z0(self):
        parsed = parse_awake_message("회사명: 에스엔시스\n종목코드: 0008Z0")
        self.assertEqual(parsed["stock_code"], "0008Z0")

    def test_mismatched_code_blocks_earnings_merge(self):
        self._assert_process_preserves_files(
            "회사명: 프로티아\n종목코드: 303360\n보고서명: 영업(잠정)실적\n2026.2Q 53억 17억 16억",
            expected_reason="parsed_code_target_mismatch",
        )

    def test_mismatched_code_blocks_disclosure_merge(self):
        self._assert_process_preserves_files(
            "회사명: 프로티아\n종목코드: 303360\n보고서명: 공급계약\n공시 시각: 2026-07-18 10:00:00",
            expected_reason="parsed_code_target_mismatch",
        )

    def test_mismatch_is_recorded_in_quarantine(self):
        distribution, quarantine = distribute_messages_with_quarantine(
            [message("회사명: 에임드바이오\n종목코드: 0009K0", 146943)], COMPANIES,
        )
        self.assertFalse(any(distribution.values()))
        self.assertEqual(quarantine[0]["parsedCompanyCode"], "0009K0")
        self.assertEqual(quarantine[0]["reason"], "code_not_in_portfolio")

    def test_missing_code_preserves_existing_data(self):
        self._assert_process_preserves_files(
            "회사명: NAVER\n보고서명: 영업(잠정)실적\n2026.2Q 53억 17억 16억",
            expected_reason="parsed_code_missing",
        )

    def test_naver_requires_explicit_code(self):
        assignments, quarantine = route_message(message("회사명: NAVER\n보고서명: 주요사항보고서"), COMPANIES)
        self.assertEqual(assignments, [])
        self.assertEqual(quarantine[0]["reason"], "target_requires_explicit_code")

    def test_ambiguous_code_less_message_is_quarantined(self):
        assignments, quarantine = route_message(message("삼성전자와 현대차 관련 공시"), COMPANIES)
        self.assertEqual(assignments, [])
        self.assertEqual(quarantine[0]["reason"], "ambiguous_alias_match")

    def test_numeric_code_routing_remains_compatible(self):
        assignments, quarantine = route_message(message("종목코드: 005930\n회사명: 삼성전자"), COMPANIES)
        self.assertEqual(assignments, ["005930"])
        self.assertEqual(quarantine, [])

    def _assert_process_preserves_files(self, text, expected_reason):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory) / "data"
            earnings_path = data_root / "earnings" / "by-company" / "035420.json"
            disclosure_path = data_root / "disclosures" / "by-company" / "035420.json"
            earnings_path.parent.mkdir(parents=True)
            disclosure_path.parent.mkdir(parents=True)
            earnings_path.write_text(json.dumps({
                "company": {"name": "NAVER", "code": "035420", "earnings": [{"period": "2026 Q1", "revenue": 1}]}
            }), encoding="utf-8")
            disclosure_path.write_text(json.dumps({
                "stockCode": "035420", "disclosures": [{"telegramMessageId": 146984, "code": "035420"}]
            }), encoding="utf-8")
            before_earnings = earnings_path.read_bytes()
            before_disclosures = disclosure_path.read_bytes()
            result = process_company(
                COMPANIES[0], [message(text, 146893)], "2026-07-18T10:00:00+09:00", data_root=data_root,
            )
            self.assertEqual(earnings_path.read_bytes(), before_earnings)
            self.assertEqual(disclosure_path.read_bytes(), before_disclosures)
            self.assertEqual(result["quarantine"][0]["reason"], expected_reason)


if __name__ == "__main__":
    unittest.main()
