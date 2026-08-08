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

  function latestType(reportName) {
    if (typeof reportName !== "string" || !reportName.trim()) return null;
    const title = reportName.replace(/[^0-9A-Za-z가-힣]/g, "").toLowerCase();
    const rules = [
      ["실적", ["연결재무제표기준영업잠정실적", "영업잠정실적", "연결재무제표기준영업실적", "잠정실적", "실적공시", "분기실적", "연간실적"]],
      ["공급계약", ["단일판매공급계약체결", "공급계약체결"]],
      ["수주", ["수주계약", "수주"]],
      ["시설투자", ["신규시설투자", "시설투자"]],
      ["자사주매입", ["자기주식취득", "자기주식취득신탁계약"]],
      ["자사주처분", ["자기주식처분"]],
      ["배당", ["배당"]],
      ["유상증자", ["유상증자결정"]],
      ["무상증자", ["무상증자결정"]],
      ["CB발행", ["전환사채권발행결정"]],
      ["BW발행", ["신주인수권부사채권발행결정"]],
      ["EB발행", ["교환사채권발행결정"]],
      ["지분매각", ["타법인주식및출자증권처분결정"]],
      ["지분투자", ["타법인주식및출자증권취득결정"]],
      ["영업양수도", ["영업양수", "영업양도"]],
      ["M&A", ["합병", "분할"]],
      ["최대주주변경", ["최대주주변경"]],
      ["소송", ["소송등의제기", "소송"]]
    ];
    const match = rules.find(([, patterns]) => patterns.some((pattern) => title.includes(pattern)));
    return match ? match[0] : "기타";
  }

  return { EARNINGS, normalize, label, matches, latestType };
}));
