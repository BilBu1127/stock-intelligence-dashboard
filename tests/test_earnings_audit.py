import unittest

from scripts.audit_earnings_data import continuity_result, growth_audit, merge_rehearsal, normalize_latest_status


def quarter(label, revenue=100):
    return {
        "fiscal_quarter": label, "revenue": revenue, "operating_profit": revenue,
        "net_income": revenue, "comparisons": {
            metric: {"qoq": {"percentage": None, "status": None}, "yoy": {"percentage": None, "status": None}}
            for metric in ("revenue", "operating_profit", "net_income")
        },
    }


class EarningsAuditTests(unittest.TestCase):
    def test_continuous_eight_quarters_are_not_just_counted(self):
        rows = [quarter(label) for label in ("2024 Q2", "2024 Q3", "2024 Q4", "2025 Q1", "2025 Q2", "2025 Q3", "2025 Q4", "2026 Q1")]
        self.assertEqual(continuity_result(rows)["status"], "complete_8q_continuous")

    def test_gap_is_detected_even_with_eight_rows(self):
        rows = [quarter(label) for label in ("2024 Q1", "2024 Q2", "2024 Q3", "2024 Q4", "2025 Q1", "2025 Q3", "2025 Q4", "2026 Q1")]
        result = continuity_result(rows)
        self.assertEqual(result["status"], "complete_8q_with_gap")
        self.assertIn("2025 Q2", result["missing_quarters"])

    def test_duplicate_and_order_are_distinguished(self):
        rows = [quarter("2025 Q1"), quarter("2025 Q1")]
        self.assertEqual(continuity_result(rows)["status"], "duplicate_quarter")
        rows = [quarter("2025 Q2"), quarter("2025 Q1")]
        self.assertEqual(continuity_result(rows)["status"], "quarter_order_issue")

    def test_historical_status_is_explicit(self):
        self.assertEqual(normalize_latest_status("historical_reference"), "historical")
        self.assertEqual(normalize_latest_status("latest_unverified"), "unknown")

    def test_growth_audit_requires_actual_previous_quarter(self):
        rows = [quarter("2025 Q1", 100), quarter("2025 Q3", 120)]
        checks = growth_audit(rows)
        qoq = next(item for item in checks if item["quarter"] == "2025 Q3" and item["metric"] == "revenue" and item["period"] == "qoq")
        self.assertTrue(qoq["match"])

    def test_synthetic_merge_rehearsal_keeps_eight_and_precedence(self):
        result = merge_rehearsal()
        self.assertEqual(result["rollover_quarters"], 8)
        self.assertTrue(result["existing_seven_preserved"])
        self.assertTrue(result["final_replaces_provisional"])
        self.assertTrue(result["corrected_precedes_final"])


if __name__ == "__main__":
    unittest.main()
