(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.EarningsChart = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  const METRICS = [
    { key: "revenue", estimateKey: "estimateRevenue", label: "매출액", className: "bar-revenue" },
    { key: "operatingIncome", estimateKey: "estimateOperatingIncome", label: "영업이익", className: "bar-operating" },
    { key: "netIncome", estimateKey: "estimateNetIncome", label: "순이익", className: "bar-net" }
  ];

  function isNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function forecastPoints(quarters, metric) {
    return quarters.map((quarter, index) => {
      const estimate = quarter[metric.estimateKey];
      if (!isNumber(estimate)) return null;
      return {
        index,
        period: quarter.period || "N/A",
        actual: isNumber(quarter[metric.key]) ? quarter[metric.key] : null,
        estimate
      };
    });
  }

  function contiguousSegments(points) {
    const segments = [];
    let current = [];

    points.forEach((point) => {
      if (point) {
        current.push(point);
        return;
      }
      if (current.length) segments.push(current);
      current = [];
    });
    if (current.length) segments.push(current);
    return segments;
  }

  function forecastComparison(actual, estimate) {
    if (!isNumber(actual) || !isNumber(estimate)) return null;
    const difference = actual - estimate;
    return {
      difference,
      percentage: estimate === 0 ? null : (difference / Math.abs(estimate)) * 100
    };
  }

  function buildChartSeries(quarters) {
    const actualBars = METRICS.map((metric) => ({
      ...metric,
      type: "bar",
      data: quarters.map((quarter) => isNumber(quarter[metric.key]) ? quarter[metric.key] : null)
    }));
    const forecastLines = METRICS.map((metric) => {
      const points = forecastPoints(quarters, metric);
      if (!points.some(Boolean)) return null;
      return {
        ...metric,
        type: "line",
        data: points.map((point) => point ? point.estimate : null),
        points,
        segments: contiguousSegments(points)
      };
    }).filter(Boolean);

    return { actualBars, forecastLines };
  }

  function tooltipData(period, metric, actual, estimate) {
    const comparison = forecastComparison(actual, estimate);
    return {
      period: period || "N/A",
      label: metric.label,
      actual: isNumber(actual) ? actual : null,
      estimate: isNumber(estimate) ? estimate : null,
      difference: comparison ? comparison.difference : null,
      percentage: comparison ? comparison.percentage : null
    };
  }

  return {
    METRICS,
    isNumber,
    forecastPoints,
    contiguousSegments,
    forecastComparison,
    buildChartSeries,
    tooltipData
  };
});
