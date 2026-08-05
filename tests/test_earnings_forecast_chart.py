import json
import re
import subprocess
import unittest
from pathlib import Path

from scripts.backfill_company import public_quarter
from scripts.parse_awake_message import merge_quarter_records, parse_awake_message

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
            const comparison = chart.forecastComparison(input.actual, input.estimate);
            const series = chart.buildChartSeries(input.quarters);
            const tooltip = chart.tooltipData('2026 Q3', metric, input.actual, input.estimate);
            process.stdout.write(JSON.stringify({points, comparison, series, tooltip}));
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


def render_chart(function_name, quarters):
    result = subprocess.run(
        [
            "node",
            "-e",
            """
            const fs = require('fs');
            const vm = require('vm');
            const source = fs.readFileSync('app.js', 'utf8');
            const name = process.argv[1];
            const start = source.indexOf(`function ${name}`);
            const end = source.indexOf(name === 'createWatchlistChart' ? 'function createMainChart' : 'function chartTooltip', start);
            const input = JSON.parse(fs.readFileSync(0, 'utf8'));
            const context = {
              window: { EarningsChart: require('./earnings-chart.js') },
              getEightQuarters: () => input,
              isNumber: (value) => typeof value === 'number' && Number.isFinite(value),
              escapeHtml: String,
              escapeAttribute: String,
              formatMoney: (value) => String(value),
              chartTooltip: () => 'tooltip',
            };
            vm.runInNewContext(source.slice(start, end), context);
            process.stdout.write(context[name](name === 'createWatchlistChart' ? { name: 'Fixture' } : input));
            """,
            function_name,
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
    return result.stdout


def svg_elements(svg, tag, class_name):
    return [
        dict(re.findall(r'([a-zA-Z][\w-]*)="([^"]*)"', match.group(1)))
        for match in re.finditer(rf"<{tag}\s+([^>]*\bclass=\"[^\"]*\b{re.escape(class_name)}\b[^\"]*\"[^>]*)>", svg)
    ]


def marker_bounds_are_safe(svg, grouped=False):
    bars = svg_elements(svg, "rect", "bar-")
    markers = svg_elements(svg, "line", "estimate-marker")
    assert bars and markers

    marker_intervals = {}
    for marker in markers:
        marker_class = next(item for item in marker["class"].split() if item.startswith("bar-"))
        x1, x2 = float(marker["x1"]), float(marker["x2"])
        matching_bars = [
            bar for bar in bars
            if marker_class in bar.get("class", "").split()
            and float(bar["x"]) <= (x1 + x2) / 2 <= float(bar["x"]) + float(bar["width"])
        ]
        assert len(matching_bars) == 1
        bar = matching_bars[0]
        bar_x, bar_width = float(bar["x"]), float(bar["width"])
        assert bar_x <= x1 < x2 <= bar_x + bar_width
        assert (x2 - x1) < bar_width
        assert abs((x2 - x1) / bar_width - 0.6) < 0.0001

        if grouped:
            for other_bar in bars:
                if other_bar is bar or marker_class in other_bar.get("class", "").split():
                    continue
                other_x, other_width = float(other_bar["x"]), float(other_bar["width"])
                assert x2 <= other_x or x1 >= other_x + other_width
        marker_intervals.setdefault(marker_class, []).append((x1, x2))

    for intervals in marker_intervals.values():
        for previous, current in zip(sorted(intervals), sorted(intervals)[1:]):
            assert previous[1] < current[0]


class EarningsForecastChartTests(unittest.TestCase):
    def test_canonical_public_forecasts_create_marker_model(self):
        parsed = parse_awake_message(
            "\n".join((
                "기업명: 가상테스트",
                "종목코드: 000001",
                "보고서명: 연결재무제표기준영업(잠정)실적 (2026.06)",
                "보고기간: 2026.06",
                "매출액: 1,200억원 (예상 1,100억원)",
                "영업이익: 150억원 (예상 140억원)",
                "순이익: 90억원 (예상 80억원)",
            )),
            telegram_message_id=9001,
        )
        records, warnings = merge_quarter_records([parsed])
        self.assertEqual(warnings, [])
        public = public_quarter(records[0])
        result = run_chart_utility({
            "metric": "revenue",
            "quarters": [public],
            "actual": public["revenue"],
            "estimate": public["estimateRevenue"],
        })
        marker_series = result["series"]["forecastMarkers"]
        self.assertEqual([item["key"] for item in marker_series], ["revenue", "operatingIncome", "netIncome"])
        self.assertEqual(marker_series[0]["data"], [1100])
        self.assertEqual(marker_series[1]["data"], [140])
        self.assertEqual(marker_series[2]["data"], [80])

    def test_actual_and_forecast_are_kept_as_separate_series(self):
        result = run_chart_utility({
            "metric": "revenue",
            "quarters": [{"period": "2026 Q1", "revenue": 100, "estimateRevenue": 120}],
            "actual": 100,
            "estimate": 120,
        })
        self.assertEqual(result["points"][0]["actual"], 100)
        self.assertEqual(result["points"][0]["estimate"], 120)

    def test_case_a_three_quarters_use_independent_markers_and_correct_tooltip_values(self):
        quarters = [
            {"period": "2026 Q1", "revenue": 100, "operatingIncome": -10, "netIncome": -8,
             "estimateRevenue": 90, "estimateOperatingIncome": -12, "estimateNetIncome": -10},
            {"period": "2026 Q2", "revenue": 120, "operatingIncome": 15, "netIncome": 9,
             "estimateRevenue": 110, "estimateOperatingIncome": 10, "estimateNetIncome": 8},
            {"period": "2026 Q3", "revenue": 140, "operatingIncome": 18, "netIncome": 12,
             "estimateRevenue": 130, "estimateOperatingIncome": 16, "estimateNetIncome": 10},
        ]
        result = run_chart_utility({"metric": "revenue", "quarters": quarters, "actual": 140, "estimate": 130})
        actual = {item["key"]: item["data"] for item in result["series"]["actualBars"]}
        forecast = {item["key"]: item for item in result["series"]["forecastMarkers"]}
        self.assertEqual(actual["revenue"], [100, 120, 140])
        self.assertEqual(actual["operatingIncome"], [-10, 15, 18])
        self.assertEqual(actual["netIncome"], [-8, 9, 12])
        self.assertEqual(forecast["revenue"]["data"], [90, 110, 130])
        self.assertEqual(forecast["operatingIncome"]["data"], [-12, 10, 16])
        self.assertEqual(forecast["netIncome"]["data"], [-10, 8, 10])
        self.assertEqual(forecast["revenue"]["type"], "marker")
        self.assertEqual([point["index"] for point in forecast["revenue"]["points"] if point], [0, 1, 2])
        self.assertEqual(result["tooltip"], {
            "period": "2026 Q3", "label": "매출액", "actual": 140, "estimate": 130,
            "difference": 10, "percentage": 100 / 13,
        })

    def test_missing_forecast_is_not_inferred_from_actual(self):
        result = run_chart_utility({
            "metric": "revenue",
            "quarters": [{"period": "2026 Q1", "revenue": 100, "estimateRevenue": None}],
            "actual": 100,
            "estimate": None,
        })
        self.assertEqual(result["points"], [None])

    def test_case_b_partial_forecasts_keep_nulls_and_only_valid_markers(self):
        quarters = [
            {"period": "2026 Q1", "revenue": 100, "estimateRevenue": 90},
            {"period": "2026 Q2", "revenue": 110, "estimateRevenue": None},
            {"period": "2026 Q3", "revenue": 120, "estimateRevenue": 115},
        ]
        result = run_chart_utility({"metric": "revenue", "quarters": quarters, "actual": 110, "estimate": None})
        revenue = next(item for item in result["series"]["forecastMarkers"] if item["key"] == "revenue")
        self.assertEqual(revenue["data"], [90, None, 115])
        self.assertEqual([point["index"] for point in revenue["points"] if point], [0, 2])
        self.assertEqual(result["tooltip"]["estimate"], None)
        self.assertEqual(result["tooltip"]["difference"], None)
        self.assertEqual(result["tooltip"]["percentage"], None)

    def test_case_c_single_forecast_point_creates_one_marker_without_a_line(self):
        result = run_chart_utility({
            "metric": "netIncome",
            "quarters": [{"period": "2026 Q1", "netIncome": 9, "estimateNetIncome": 8}],
            "actual": 9,
            "estimate": 8,
        })
        markers = result["series"]["forecastMarkers"]
        self.assertEqual(len(markers), 1)
        self.assertEqual([point["index"] for point in markers[0]["points"] if point], [0])

    def test_zero_forecast_has_no_percentage_comparison(self):
        result = run_chart_utility({
            "metric": "netIncome",
            "quarters": [],
            "actual": 10,
            "estimate": 0,
        })
        self.assertEqual(result["comparison"]["difference"], 10)
        self.assertIsNone(result["comparison"]["percentage"])

    def test_case_d_no_forecast_creates_no_marker_series(self):
        quarters = [
            {"period": "2026 Q1", "revenue": 100, "operatingIncome": 10, "netIncome": 8},
            {"period": "2026 Q2", "revenue": 110, "operatingIncome": 12, "netIncome": 9},
        ]
        result = run_chart_utility({"metric": "revenue", "quarters": quarters, "actual": 100, "estimate": None})
        self.assertEqual(len(result["series"]["actualBars"]), 3)
        self.assertEqual(result["series"]["forecastMarkers"], [])

    def test_case_e_negative_forecast_keeps_value_and_comparison(self):
        result = run_chart_utility({
            "metric": "operatingIncome",
            "quarters": [{"period": "2026 Q3", "operatingIncome": -20, "estimateOperatingIncome": -25}],
            "actual": -20,
            "estimate": -25,
        })
        marker = result["series"]["forecastMarkers"][0]
        self.assertEqual(marker["data"], [-25])
        self.assertEqual(result["tooltip"]["difference"], 5)
        self.assertEqual(result["tooltip"]["percentage"], 20)

    def test_rendered_main_chart_uses_markers_not_connected_lines(self):
        svg = render_chart("createMainChart", [
            {"period": "2026 Q1", "revenue": 100, "operatingIncome": -10, "netIncome": 8,
             "estimateRevenue": 90, "estimateOperatingIncome": -12, "estimateNetIncome": 7},
            {"period": "2026 Q2", "revenue": 120, "operatingIncome": 12, "netIncome": 9,
             "estimateRevenue": None, "estimateOperatingIncome": None, "estimateNetIncome": None},
        ])
        self.assertEqual(svg.count('class="estimate-marker'), 3)
        self.assertNotIn("polyline", svg)
        self.assertNotIn("type=\"bar\"", svg)
        self.assertIn('class="bar-revenue"', svg)

    def test_main_chart_markers_stay_inside_their_grouped_bars(self):
        svg = render_chart("createMainChart", [
            {"period": "2026 Q1", "revenue": 100, "operatingIncome": -10, "netIncome": 8,
             "estimateRevenue": 90, "estimateOperatingIncome": -12, "estimateNetIncome": 7},
            {"period": "2026 Q2", "revenue": 120, "operatingIncome": 12, "netIncome": 9,
             "estimateRevenue": 110, "estimateOperatingIncome": 10, "estimateNetIncome": 8},
        ])
        marker_bounds_are_safe(svg, grouped=True)
        self.assertNotIn("polyline", svg)
        self.assertNotIn("<path class=\"estimate-marker", svg)

    def test_rendered_watchlist_chart_marks_only_forecast_quarters(self):
        svg = render_chart("createWatchlistChart", [
            {"period": "2026 Q1", "revenue": 100, "operatingIncome": -10,
             "estimateRevenue": 90, "estimateOperatingIncome": -12},
            {"period": "2026 Q2", "revenue": 120, "operatingIncome": 12,
             "estimateRevenue": None, "estimateOperatingIncome": None},
        ])
        self.assertEqual(svg.count('class="estimate-marker'), 2)
        self.assertIn('<rect x="78"', svg)
        self.assertNotIn("polyline", svg)

    def test_watchlist_markers_stay_inside_their_bars_and_do_not_touch(self):
        svg = render_chart("createWatchlistChart", [
            {"period": "2026 Q1", "revenue": 100, "operatingIncome": -10,
             "estimateRevenue": 90, "estimateOperatingIncome": -12},
            {"period": "2026 Q2", "revenue": 120, "operatingIncome": 12,
             "estimateRevenue": 110, "estimateOperatingIncome": 10},
        ])
        marker_bounds_are_safe(svg)
        self.assertNotIn("<path class=\"estimate-marker", svg)

    def test_rendered_charts_without_forecasts_keep_existing_bar_only_view(self):
        quarters = [{"period": "2026 Q1", "revenue": 100, "operatingIncome": 10, "netIncome": 8}]
        self.assertNotIn("estimate-marker", render_chart("createMainChart", quarters))
        self.assertNotIn("estimate-marker", render_chart("createWatchlistChart", quarters))


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

    def test_watchlist_chart_uses_same_quarter_marker_fields(self):
        source = self.app_source.split("function createWatchlistChart", 1)[1].split("function createMainChart", 1)[0]
        self.assertIn("estimateRevenue", source)
        self.assertIn("estimateOperatingIncome", source)
        self.assertIn("estimate-marker", source)
        self.assertNotIn("polyline", source)

    def test_chart_uses_only_forecast_fields_for_forecast_points(self):
        self.assertIn("window.EarningsChart.buildChartSeries(quarters)", self.app_source)
        self.assertIn("chartSeries.forecastMarkers", self.app_source)
        self.assertNotIn("forecastLines", self.app_source)
        self.assertNotIn("<polyline", self.app_source)

    def test_empty_forecast_hides_the_forecast_legend(self):
        self.assertIn('id="estimateLegend"', self.html_source)
        self.assertIn("els.estimateLegend.hidden = !hasEstimate", self.app_source)
        self.assertIn("예상치 가로선 표시", self.app_source)

    def test_tooltip_labels_missing_forecasts_without_treating_them_as_zero(self):
        self.assertIn('lines.push("예상치: N/A")', self.app_source)
        self.assertIn("tooltipData", self.app_source)

    def test_refresh_labels_keep_confirmation_and_content_times_distinct(self):
        self.assertIn("마지막 확인 완료", self.html_source)
        self.assertIn("마지막 신규 데이터 반영", self.html_source)
        self.assertIn("lastSuccessfulRefresh", self.app_source)
        self.assertIn("lastContentChanged", self.app_source)
        self.assertIn("자동 업데이트: 매일 08:15 · 20:15 KST", self.html_source)


if __name__ == "__main__":
    unittest.main()
