(function exposeDisclosureCategory(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.DisclosureCategory = api;
}(typeof window !== "undefined" ? window : globalThis, function createDisclosureCategory() {
  const EARNINGS = "earnings";

  function normalize(value) {
    return value === "실적" || value === "performance" ? EARNINGS : value || "기타";
  }

  function label(value) {
    return normalize(value) === EARNINGS ? "실적" : normalize(value);
  }

  function matches(item, selectedCategory) {
    return selectedCategory === "all" || normalize(item?.category) === selectedCategory;
  }

  return { EARNINGS, normalize, label, matches };
}));
