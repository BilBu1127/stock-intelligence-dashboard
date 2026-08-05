import json
import re
import subprocess
import unittest
from pathlib import Path

from scripts.onboard_portfolio import disclosure_summary

ROOT = Path(__file__).resolve().parents[1]


def run_sort_utility(script, payload=None):
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        input=json.dumps(payload) if payload is not None else "",
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class WatchlistSortUtilityTests(unittest.TestCase):
    def sort(self, companies, mode, dates):
        return run_sort_utility(
            """
            const fs = require('fs');
            const utils = require('./watchlist-sort.js');
            const input = JSON.parse(fs.readFileSync(0, 'utf8'));
            process.stdout.write(JSON.stringify(utils.sortCompanies(input.companies, input.mode, input.dates)));
            """,
            {"companies": companies, "mode": mode, "dates": dates},
        )

    def test_default_sort_preserves_configured_order_without_mutation(self):
        companies = [{"code": "B"}, {"code": "A"}, {"code": "C"}]
        original = json.loads(json.dumps(companies))
        result = self.sort(companies, "default", {"A": "2026-07-19", "B": "2026-07-18"})
        self.assertEqual([item["code"] for item in result], ["B", "A", "C"])
        self.assertEqual(companies, original)

    def test_latest_disclosure_sort_is_descending(self):
        companies = [{"code": "A"}, {"code": "B"}, {"code": "C"}]
        result = self.sort(companies, "latest-disclosure", {
            "A": "2026-07-17T23:00:00+09:00",
            "B": "2026-07-19T01:00:00+09:00",
            "C": "2026-07-18T10:00:00+09:00",
        })
        self.assertEqual([item["code"] for item in result], ["B", "C", "A"])

    def test_equal_dates_preserve_default_order(self):
        companies = [{"code": "B"}, {"code": "A"}, {"code": "C"}]
        dates = {item["code"]: "2026-07-18T12:00:00+09:00" for item in companies}
        result = self.sort(companies, "latest-disclosure", dates)
        self.assertEqual([item["code"] for item in result], ["B", "A", "C"])

    def test_companies_without_disclosures_are_last_and_stable(self):
        companies = [{"code": "A"}, {"code": "B"}, {"code": "C"}, {"code": "D"}]
        result = self.sort(companies, "latest-disclosure", {"B": "2026-07-18", "D": "2026-07-19"})
        self.assertEqual([item["code"] for item in result], ["D", "B", "A", "C"])

    def test_invalid_dates_are_treated_as_missing(self):
        companies = [{"code": "A"}, {"code": "B"}, {"code": "C"}]
        result = self.sort(companies, "latest-disclosure", {
            "A": "Invalid Date", "B": "2026-02-30", "C": "2026-02-28"
        })
        self.assertEqual([item["code"] for item in result], ["C", "A", "B"])

    def test_date_format_uses_source_calendar_date(self):
        result = run_sort_utility(
            "const u=require('./watchlist-sort.js'); process.stdout.write(JSON.stringify(u.formatDisclosureDate('2026-07-18T00:05:00-10:00')));"
        )
        self.assertEqual(result, "2026.07.18")

    def test_local_storage_selection_is_restored(self):
        result = run_sort_utility(
            "const u=require('./watchlist-sort.js'); const s={getItem:()=> 'latest-disclosure'}; process.stdout.write(JSON.stringify(u.restoreSortMode(s)));"
        )
        self.assertEqual(result, "latest-disclosure")

    def test_invalid_local_storage_value_falls_back_to_default(self):
        result = run_sort_utility(
            "const u=require('./watchlist-sort.js'); const s={getItem:()=> 'alphabetical'}; process.stdout.write(JSON.stringify(u.restoreSortMode(s)));"
        )
        self.assertEqual(result, "default")


class WatchlistSortIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.html_source = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.css_source = (ROOT / "styles.css").read_text(encoding="utf-8")
        cls.earnings_index = json.loads((ROOT / "data" / "earnings" / "index.json").read_text(encoding="utf-8"))
        cls.disclosure_index = json.loads((ROOT / "data" / "disclosures" / "index.json").read_text(encoding="utf-8"))

    def test_company_card_click_still_opens_earnings_detail(self):
        self.assertIn('card.addEventListener("click"', self.app_source)
        self.assertIn("openCompanyDetail(card.dataset.code)", self.app_source)
        self.assertIn('state.activeTab = "earnings"', self.app_source)

    def test_mobile_layout_contains_sort_control_and_date_footer(self):
        self.assertIn("watchlist-sort", self.html_source)
        self.assertIn("watchlist-disclosure-date", self.app_source)
        mobile_rules = re.search(r"@media \(max-width: 720px\)(.*)", self.css_source, re.DOTALL)
        self.assertIsNotNone(mobile_rules)
        self.assertIn(".segmented-control", mobile_rules.group(1))
        self.assertIn("grid-template-columns: 1fr", mobile_rules.group(1))

    def test_all_61_watchlist_companies_have_disclosure_summaries(self):
        watchlist_codes = [item["code"] for item in self.earnings_index["watchlist"]]
        summary_codes = [item["stockCode"] for item in self.disclosure_index["companies"]]
        self.assertEqual(len(watchlist_codes), 61)
        self.assertEqual(summary_codes, watchlist_codes)

    def test_disclosure_index_latest_dates_match_company_details(self):
        for summary in self.disclosure_index["companies"]:
            code = summary["stockCode"]
            detail = json.loads((ROOT / "data" / "disclosures" / "by-company" / f"{code}.json").read_text(encoding="utf-8"))
            expected = disclosure_summary(code, detail.get("disclosures", []))
            self.assertEqual(summary["latestDisclosureAt"], expected["latestDisclosureAt"], code)
            self.assertEqual(summary["disclosureCount"], expected["disclosureCount"], code)

    def test_naver_summary_counts_only_unique_valid_fixture_disclosures(self):
        disclosures = [
            {"code": "035420", "category": "earnings", "telegramMessageId": 501, "disclosedAt": "2026-07-16T11:33:29+09:00"},
            {"code": "035420", "category": "earnings", "telegramMessageId": 501, "disclosedAt": "2026-07-16T11:33:29+09:00"},
            {"code": "035420", "category": "\uae30\ud0c0", "dartReceiptNumber": "R-502", "disclosedAt": "2026-07-17T11:33:29+09:00"},
            {"code": "005930", "category": "earnings", "telegramMessageId": 503, "disclosedAt": "2026-07-18T11:33:29+09:00"},
            {"code": "035420", "category": "legacy", "telegramMessageId": 504, "disclosedAt": "2026-07-19T11:33:29+09:00"},
        ]
        summary = disclosure_summary("035420", disclosures)
        self.assertEqual(summary["disclosureCount"], 2)
        self.assertEqual(summary["latestDisclosureAt"], "2026-07-17T11:33:29+09:00")
        self.assertEqual([item["code"] for item in summary["disclosures"]], ["035420", "035420"])
        self.assertTrue(all(item["category"] in {"earnings", "\uae30\ud0c0"} for item in summary["disclosures"]))


if __name__ == "__main__":
    unittest.main()
