(function exposeWatchlistSort(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.WatchlistSort = api;
}(typeof window !== "undefined" ? window : globalThis, function createWatchlistSort() {
  const DEFAULT_MODE = "default";
  const LATEST_DISCLOSURE_MODE = "latest-disclosure";
  const STORAGE_KEY = "portfolioSortMode";
  const VALID_MODES = new Set([DEFAULT_MODE, LATEST_DISCLOSURE_MODE]);

  function normalizeSortMode(value) {
    return VALID_MODES.has(value) ? value : DEFAULT_MODE;
  }

  function parseDisclosureDate(value) {
    if (typeof value !== "string") return null;
    const match = value.trim().match(/^(\d{4})[-.](\d{2})[-.](\d{2})(?:[T\s]|$)/);
    if (!match) return null;

    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const date = new Date(Date.UTC(year, month - 1, day));
    if (
      date.getUTCFullYear() !== year
      || date.getUTCMonth() !== month - 1
      || date.getUTCDate() !== day
    ) return null;

    return {
      sortValue: (year * 10000) + (month * 100) + day,
      formatted: `${match[1]}.${match[2]}.${match[3]}`
    };
  }

  function formatDisclosureDate(value) {
    return parseDisclosureDate(value)?.formatted || null;
  }

  function sortCompanies(companies, mode, latestDisclosureByCode = {}) {
    const normalizedMode = normalizeSortMode(mode);
    const indexed = companies.map((company, defaultIndex) => ({ company, defaultIndex }));
    if (normalizedMode === DEFAULT_MODE) return indexed.map(({ company }) => company);

    return indexed.sort((left, right) => {
      const leftDate = parseDisclosureDate(latestDisclosureByCode[left.company.code])?.sortValue ?? -1;
      const rightDate = parseDisclosureDate(latestDisclosureByCode[right.company.code])?.sortValue ?? -1;
      return rightDate - leftDate || left.defaultIndex - right.defaultIndex;
    }).map(({ company }) => company);
  }

  function restoreSortMode(storage) {
    try {
      return normalizeSortMode(storage?.getItem(STORAGE_KEY));
    } catch (error) {
      return DEFAULT_MODE;
    }
  }

  function saveSortMode(storage, mode) {
    const normalizedMode = normalizeSortMode(mode);
    try {
      storage?.setItem(STORAGE_KEY, normalizedMode);
    } catch (error) {
      // The selected mode still works for this page when storage is unavailable.
    }
    return normalizedMode;
  }

  return {
    DEFAULT_MODE,
    LATEST_DISCLOSURE_MODE,
    STORAGE_KEY,
    normalizeSortMode,
    parseDisclosureDate,
    formatDisclosureDate,
    sortCompanies,
    restoreSortMode,
    saveSortMode
  };
}));
