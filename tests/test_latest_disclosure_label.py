import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def classify_title(title):
    result = subprocess.run(
        [
            "node",
            "-e",
            """
            const category = require('./disclosure-category.js');
            const fs = require('fs');
            const input = JSON.parse(fs.readFileSync(0, 'utf8'));
            process.stdout.write(JSON.stringify(input.map((title) => category.latestType(title))));
            """,
        ],
        cwd=ROOT,
        input=json.dumps(title),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class LatestDisclosureLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.css_source = (ROOT / "styles.css").read_text(encoding="utf-8")
        cls.index = json.loads((ROOT / "data" / "disclosures" / "index.json").read_text(encoding="utf-8"))

    def test_major_disclosure_titles_have_short_labels(self):
        titles = [
            "연결재무제표기준영업(잠정)실적(공정공시)",
            "단일판매ㆍ공급계약체결",
            "신규시설투자등",
            "자기주식취득결정",
            "교환사채권발행결정",
            "현금ㆍ현물배당결정",
            "유상증자결정",
            "무상증자결정",
            "전환사채권발행결정",
            "신주인수권부사채권발행결정",
            "타법인주식및출자증권취득결정",
            "타법인주식및출자증권처분결정",
            "최대주주변경",
            "소송 등의 제기",
        ]
        self.assertEqual(
            classify_title(titles),
            ["실적", "공급계약", "시설투자", "자사주매입", "EB발행", "배당", "유상증자", "무상증자", "CB발행", "BW발행", "지분투자", "지분매각", "최대주주변경", "소송"],
        )

    def test_unclassified_title_has_safe_fallback_and_null_stays_hidden(self):
        self.assertEqual(classify_title(["정기주주총회결과", None]), ["기타", None])

    def test_classifier_uses_report_title_only_without_company_specific_rules(self):
        source = (ROOT / "disclosure-category.js").read_text(encoding="utf-8")
        self.assertIn("function latestType(reportName)", source)
        self.assertNotIn("stockCode", source)
        self.assertNotIn("companyName", source)

    def test_current_disclosure_index_uses_report_name_field(self):
        latest = self.index["disclosures"][0]
        self.assertIn("reportName", latest)
        self.assertIsInstance(latest["reportName"], str)

    def test_card_uses_the_same_latest_disclosure_record_and_title(self):
        self.assertIn("getDisclosuresForCompany(company.code)[0]", self.app_source)
        self.assertIn("latestType(latestDisclosure?.reportName)", self.app_source)
        self.assertIn("watchlist-disclosure-type", self.app_source)

    def test_latest_disclosure_title_matches_the_summary_date_for_each_company(self):
        disclosures_by_code = {}
        for disclosure in self.index["disclosures"]:
            disclosures_by_code.setdefault(disclosure.get("code"), []).append(disclosure)

        for company in self.index["companies"]:
            disclosures = disclosures_by_code.get(company.get("stockCode"), [])
            latest_at = company.get("latestDisclosureAt")
            if not disclosures:
                self.assertIsNone(latest_at)
                continue

            latest = max(disclosures, key=lambda disclosure: disclosure.get("disclosedAt") or "")
            self.assertEqual(latest.get("disclosedAt"), latest_at)
            self.assertIsInstance(latest.get("reportName"), str)

    def test_null_title_keeps_existing_date_only_rendering(self):
        self.assertIn('latestDisclosureType ? `<span class="watchlist-disclosure-type">', self.app_source)
        self.assertIn(': ""}', self.app_source)

    def test_mobile_label_wraps_without_changing_card_action(self):
        self.assertIn(".watchlist-disclosure-date {\n  display: flex;", self.css_source)
        self.assertIn("flex-wrap: wrap;", self.css_source)
        self.assertIn(".watchlist-disclosure-type", self.css_source)
        self.assertIn('openCompanyDetail(card.dataset.code)', self.app_source)


if __name__ == "__main__":
    unittest.main()
