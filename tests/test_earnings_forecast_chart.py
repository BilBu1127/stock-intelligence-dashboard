import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_chart_utility(payload):
    result = subprocess.run(
        [
            "node",
            "-e",
            """
            const fs = require('fs');
            const chart = require('./earnings-chart.js');
            const input = JSON.parse(fs.readFileSync(0, 'utf8'));
            const metric = chart.METRICS.find((item) => item.key === input.metric);
            const points = chart.forecastPoints(input.quarters, metric);
            const segments = chart.contiguousSegments(points);
            const comparison = chart.forecastComparison(input.actual, input.estimate);
            process.stdout.write(JSON.stringify({points, segments, comparison}));
            """,
        ],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class EarningsForecastChartTests(unittest.TestCase):
    def test_actual_and_forecast_are_kept_as_separate_series(self):
        result = run_chart_utility({
            "metric": "revenue",
            "quarters": [{"period": "2026 Q1", "revenue": 100, "estimateRevenue": 120}],
            "actual": 100,
            "estimate": 120,
        })
        self.assertEqual(result["points"][0]["actual"], 100)
        self.assertEqual(result["points"][0]["estimate"], 120)

    def test_missing_forecast_is_not_inferred_from_actual(self):
        result = run_chart_utility({
            "metric": "revenue",
            "quarters": [{"period": "2026 Q1", "revenue": 100, "estimateRevenue": None}],
            "actual": 100,
            "estimate": None,
        })
        self.assertEqual(result["points"], [None])
        self.assertEqual(result["segments"], [])

    def test_forecast_lines_do_not_bridge_missing_quarters(self):
        result = run_chart_utility({
            "metric": "operatingIncome",
            "quarters": [
                {"period": "2025 Q4", "operatingIncome": 10, "estimateOperatingIncome": 11},
                {"period": "2026 Q1", "operatingIncome": 12, "estimateOperatingIncome": None},
                {"period": "2026 Q2", "operatingIncome": 13, "estimateOperatingIncome": 14},
                {"period": "2026 Q3", "operatingIncome": 15, "estimateOperatingIncome": 16},
            ],
            "actual": 15,
            "estimate": 16,
        })
        self.assertEqual([[point["index"] for point in segment] for segment in result["segments"]], [[0], [2, 3]])

    def test_single_forecast_point_is_retained_for_a_marker(self):
        result = run_chart_utility({
            "metric": "netIncome",
            "quarters": [{"period": "2026 Q1", "netIncome": 9, "estimateNetIncome": 8}],
            "actual": 9,
            "estimate": 8,
        })
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual(len(result["segments"][0]), 1)

    def test_zero_forecast_has_no_percentage_comparison(self):
        result = run_chart_utility({
            "metric": "netIncome",
            "quarters": [],
            "actual": 10,
            "estimate": 0,
        })
        self.assertEqual(result["comparison"]["difference"], 10)
        self.assertIsNone(result["comparison"]["percentage"])


class EarningsForecastChartIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html_source = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.app_source = (ROOT / "app.js").read_text(encoding="utf-8")

    def test_quarter_table_excludes_forecast_columns(self):
        self.assertNotIn("예상치 대비", self.html_source)
        quarter_row = self.app_source.split("function quarterRow", 1)[1].split("function getYoY", 1)[0]
        self.assertNotIn("estimate", quarter_row)

    def test_chart_renders_markers_and_accessible_tooltips(self):
        self.assertIn("estimate-marker", self.app_source)
        self.assertIn("data-chart-tooltip", self.app_source)
        self.assertIn("bindChartTooltips", self.app_source)

    def test_chart_uses_only_forecast_fields_for_forecast_points(self):
        self.assertIn("window.EarningsChart.forecastPoints(quarters, metric)", self.app_source)
        self.assertIn("window.EarningsChart.contiguousSegments(points)", self.app_source)

    def test_last_updated_label_matches_generated_timestamp_semantics(self):
        self.assertIn("마지막 데이터 생성", self.html_source)
        self.assertIn("자동 업데이트: 매일 08:15 · 20:15 KST", self.html_source)


if __name__ == "__main__":
    unittest.main()
