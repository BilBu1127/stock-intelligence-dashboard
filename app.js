const FALLBACK_EARNINGS = {
  generatedAt: "2026-07-17T11:06:36+09:00",
  currencyUnit: "억원",
  watchlist: [
    { name: "SK하이닉스", code: "000660", market: "KOSPI" },
    { name: "삼성전자", code: "005930", market: "KOSPI" },
    { name: "동원금속", code: "018500", market: "KOSPI" }
  ],
  companies: [
    {
      name: "SK하이닉스",
      code: "000660",
      market: "KOSPI",
      earnings: [],
      news: []
    },
    {
      name: "삼성전자",
      code: "005930",
      market: "KOSPI",
      earnings: [],
      news: []
    },
    {
      name: "동원금속",
      code: "018500",
      market: "KOSPI",
      earnings: [
        { period: "2025 Q1", revenue: 1632, operatingIncome: 154, netIncome: 132, estimateRevenue: null, estimateOperatingIncome: null, estimateNetIncome: null },
        { period: "2025 Q2", revenue: 1680, operatingIncome: 131, netIncome: 55, estimateRevenue: null, estimateOperatingIncome: null, estimateNetIncome: null },
        { period: "2025 Q3", revenue: 1556, operatingIncome: 85, netIncome: 99, estimateRevenue: null, estimateOperatingIncome: null, estimateNetIncome: null },
        { period: "2025 Q4", revenue: 1571, operatingIncome: 74, netIncome: 106, estimateRevenue: null, estimateOperatingIncome: null, estimateNetIncome: null },
        { period: "2026 Q1", revenue: 1788, operatingIncome: 60, netIncome: 130, estimateRevenue: null, estimateOperatingIncome: null, estimateNetIncome: null }
      ],
      news: []
    }
  ]
};

const FALLBACK_DISCLOSURES = {
  generatedAt: "2026-07-17T11:06:36+09:00",
  categories: ["실적", "시설투자", "공급계약", "자사주·배당", "증자·사채", "지분", "기타"],
  disclosures: [
    {
      disclosedAt: "2026-06-24T07:30:03+09:00",
      companyName: "동원금속",
      code: "018500",
      reportName: "주식등의대량보유상황보고서(일반)",
      category: "지분",
      provisionalEarnings: false,
      summary: "주식등의대량보유상황보고서(일반) 관련 공시.",
      dartUrl: "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260623000428",
      dartReceiptNumber: "20260623000428",
      telegramMessageId: 145480
    },
    {
      disclosedAt: "2026-06-19T17:55:54+09:00",
      companyName: "동원금속",
      code: "018500",
      reportName: "사업보고서 (2026.03)",
      category: "실적",
      provisionalEarnings: false,
      summary: "2026.03 사업보고서 제출. 연결 기준 2026 Q1 매출 1,788억원, 영업이익 60억원, 순이익 130억원 확인.",
      dartUrl: "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260619000676"
    },
    {
      disclosedAt: "2026-06-12T15:34:58+09:00",
      companyName: "동원금속",
      code: "018500",
      reportName: "현금ㆍ현물배당결정",
      category: "자사주·배당",
      provisionalEarnings: false,
      summary: "현금ㆍ현물배당결정 관련 공시.",
      dartUrl: "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260612800660",
      dartReceiptNumber: "20260612800660",
      telegramMessageId: 144869
    }
  ]
};

const FALLBACK_NEWS = {
  generated_at: null,
  news: []
};

const state = {
  earningsData: FALLBACK_EARNINGS,
  disclosureData: FALLBACK_DISCLOSURES,
  newsData: FALLBACK_NEWS,
  selectedCompanyCode: "018500",
  activeTab: "watchlist",
  companyFilter: "all",
  typeFilter: "all",
  newsCompanyFilter: "all",
  newsRegionFilter: "all",
  newsProviderFilter: "all",
  newsImportanceFilter: "all",
  newsSortFilter: "latest",
  newsPeriodFilter: "7",
  newsVisibleLimit: 40,
  watchlistSearch: "",
  watchlistCategoryFilter: "all",
  watchlistTierFilter: "all",
  watchlistSortMode: "default",
  watchlistVisibleLimit: 50,
  loadedCompanyDetails: new Set()
};

const els = {
  lastUpdated: document.querySelector("#lastUpdated"),
  tabButtons: document.querySelectorAll(".tab-button"),
  panels: document.querySelectorAll(".tab-panel"),
  watchlistSummary: document.querySelector("#watchlistSummary"),
  watchlistSearch: document.querySelector("#watchlistSearch"),
  watchlistCategoryFilter: document.querySelector("#watchlistCategoryFilter"),
  watchlistTierFilter: document.querySelector("#watchlistTierFilter"),
  watchlistSortButtons: document.querySelectorAll("[data-sort-mode]"),
  watchlistLoadMore: document.querySelector("#watchlistLoadMore"),
  selectedCompanyName: document.querySelector("#selectedCompanyName"),
  selectedCompanyMeta: document.querySelector("#selectedCompanyMeta"),
  selectedStatus: document.querySelector("#selectedStatus"),
  metricRow: document.querySelector("#metricRow"),
  mainChart: document.querySelector("#mainChart"),
  quarterTable: document.querySelector("#quarterTable"),
  recentDisclosures: document.querySelector("#recentDisclosures"),
  recentNews: document.querySelector("#recentNews"),
  disclosureCount: document.querySelector("#disclosureCount"),
  estimateNotice: document.querySelector("#estimateNotice"),
  companyFilter: document.querySelector("#companyFilter"),
  typeFilter: document.querySelector("#typeFilter"),
  disclosureList: document.querySelector("#disclosureList"),
  newsCompanyFilter: document.querySelector("#newsCompanyFilter"),
  newsRegionFilter: document.querySelector("#newsRegionFilter"),
  newsProviderFilter: document.querySelector("#newsProviderFilter"),
  newsImportanceFilter: document.querySelector("#newsImportanceFilter"),
  newsSortFilter: document.querySelector("#newsSortFilter"),
  newsPeriodFilter: document.querySelector("#newsPeriodFilter"),
  coreNewsList: document.querySelector("#coreNewsList"),
  allNewsList: document.querySelector("#allNewsList"),
  coreNewsCount: document.querySelector("#coreNewsCount"),
  allNewsCount: document.querySelector("#allNewsCount"),
  newsLoadMore: document.querySelector("#newsLoadMore")
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  const [earningsData, disclosureData, newsData] = await Promise.all([
    loadJsonCandidates(["./data/earnings/index.json", "./data/earnings.json"], FALLBACK_EARNINGS),
    loadJsonCandidates(["./data/disclosures/index.json", "./data/disclosures.json"], FALLBACK_DISCLOSURES),
    loadJsonCandidates(["./data/news/index.json", "./data/news.json"], FALLBACK_NEWS)
  ]);

  state.earningsData = normalizeEarningsData(earningsData);
  state.disclosureData = normalizeDisclosureData(disclosureData);
  state.newsData = normalizeNewsData(newsData);
  state.watchlistSortMode = window.WatchlistSort.restoreSortMode(window.localStorage);
  state.selectedCompanyCode = pickInitialCompany();

  bindEvents();
  renderAll();
}

async function loadJsonCandidates(paths, fallback) {
  if (window.location.protocol === "file:") {
    if (fallback === FALLBACK_EARNINGS && Array.isArray(window.PORTFOLIO_INDEX)) {
      const examples = new Map(FALLBACK_EARNINGS.companies.map((company) => [company.code, company]));
      return {
        ...FALLBACK_EARNINGS,
        watchlist: window.PORTFOLIO_INDEX,
        companies: window.PORTFOLIO_INDEX.map((item) => ({
          ...item,
          ...(examples.get(item.code) || {}),
          name: item.name,
          code: item.code,
          market: item.market,
          category: item.category,
          monitoringTier: item.monitoringTier,
          earnings: examples.get(item.code)?.earnings || []
        }))
      };
    }
    if (fallback === FALLBACK_DISCLOSURES && Array.isArray(window.DISCLOSURE_COMPANY_INDEX)) {
      return {
        ...FALLBACK_DISCLOSURES,
        companies: window.DISCLOSURE_COMPANY_INDEX
      };
    }
    return fallback;
  }
  for (const path of paths) {
    try {
      const response = await fetch(path, { cache: "no-store" });
      if (response.ok) return await response.json();
    } catch (error) {
      console.warn(`${path} 파일을 불러오지 못했습니다.`, error);
    }
  }
  return fallback;
}

async function loadOptionalJson(path) {
  if (window.location.protocol === "file:") return null;
  try {
    const response = await fetch(path, { cache: "no-store" });
    return response.ok ? await response.json() : null;
  } catch (error) {
    console.warn(`${path} 상세 파일을 불러오지 못했습니다.`, error);
    return null;
  }
}

async function loadJson(path, fallback) {
  if (window.location.protocol === "file:") {
    return fallback;
  }

  try {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } catch (error) {
    console.warn(`${path} 파일을 불러오지 못해 기본 예시 데이터를 표시합니다.`, error);
    return fallback;
  }
}

function normalizeEarningsData(data) {
  return {
    generatedAt: data.generatedAt || FALLBACK_EARNINGS.generatedAt,
    currencyUnit: data.currencyUnit || "억원",
    watchlist: Array.isArray(data.watchlist) ? data.watchlist : FALLBACK_EARNINGS.watchlist,
    companies: Array.isArray(data.companies) ? data.companies : []
  };
}

function normalizeDisclosureData(data) {
  return {
    generatedAt: data.generatedAt || FALLBACK_DISCLOSURES.generatedAt,
    categories: Array.isArray(data.categories) ? data.categories : FALLBACK_DISCLOSURES.categories,
    companies: Array.isArray(data.companies) ? data.companies : [],
    disclosures: Array.isArray(data.disclosures) ? data.disclosures : []
  };
}

function normalizeNewsData(data) {
  return {
    generatedAt: data.generated_at || data.generatedAt || null,
    news: Array.isArray(data.news) ? data.news : []
  };
}

function bindEvents() {
  els.tabButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.activeTab = button.dataset.tab;
      renderTabs();
    });
  });

  els.companyFilter.addEventListener("change", async (event) => {
    state.companyFilter = event.target.value;
    if (state.companyFilter !== "all") await loadCompanyDetails(state.companyFilter);
    renderDisclosureList();
  });

  els.typeFilter.addEventListener("change", (event) => {
    state.typeFilter = event.target.value;
    renderDisclosureList();
  });

  [
    [els.newsCompanyFilter, "newsCompanyFilter"],
    [els.newsRegionFilter, "newsRegionFilter"],
    [els.newsProviderFilter, "newsProviderFilter"],
    [els.newsImportanceFilter, "newsImportanceFilter"],
    [els.newsSortFilter, "newsSortFilter"],
    [els.newsPeriodFilter, "newsPeriodFilter"]
  ].forEach(([element, stateKey]) => {
    element.addEventListener("change", async (event) => {
      state[stateKey] = event.target.value;
      state.newsVisibleLimit = 40;
      if (stateKey === "newsCompanyFilter" && event.target.value !== "all") {
        await loadCompanyDetails(event.target.value);
      }
      renderNews();
    });
  });

  els.newsLoadMore.addEventListener("click", () => {
    state.newsVisibleLimit += 40;
    renderNews();
  });

  els.watchlistSearch.addEventListener("input", (event) => {
    state.watchlistSearch = event.target.value.trim().toLocaleLowerCase("ko-KR");
    state.watchlistVisibleLimit = 50;
    renderWatchlist();
  });

  els.watchlistCategoryFilter.addEventListener("change", (event) => {
    state.watchlistCategoryFilter = event.target.value;
    state.watchlistVisibleLimit = 50;
    renderWatchlist();
  });

  els.watchlistTierFilter.addEventListener("change", (event) => {
    state.watchlistTierFilter = event.target.value;
    state.watchlistVisibleLimit = 50;
    renderWatchlist();
  });

  els.watchlistSortButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.watchlistSortMode = window.WatchlistSort.saveSortMode(window.localStorage, button.dataset.sortMode);
      state.watchlistVisibleLimit = 50;
      renderWatchlist();
    });
  });

  els.watchlistLoadMore.addEventListener("click", () => {
    state.watchlistVisibleLimit += 50;
    renderWatchlist();
  });

  window.addEventListener("resize", debounce(() => {
    renderWatchlist();
    renderSelectedCompany();
  }, 120));
}

function renderAll() {
  renderTabs();
  renderLastUpdated();
  renderWatchlistFilters();
  renderWatchlist();
  renderSelectedCompany();
  renderFilters();
  renderDisclosureList();
  renderNewsFilters();
  renderNews();
}

function renderWatchlistFilters() {
  const categories = [...new Set(state.earningsData.watchlist.map((item) => item.category).filter(Boolean))];
  els.watchlistCategoryFilter.innerHTML = [
    `<option value="all">전체 카테고리</option>`,
    ...categories.map((category) => `<option value="${escapeAttribute(category)}">${escapeHtml(category)}</option>`)
  ].join("");
  els.watchlistCategoryFilter.value = state.watchlistCategoryFilter;
}

function renderTabs() {
  els.tabButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === state.activeTab);
  });

  els.panels.forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${state.activeTab}`);
  });
}

function renderLastUpdated() {
  const dates = [state.earningsData.generatedAt, state.disclosureData.generatedAt, state.newsData.generatedAt]
    .filter(Boolean)
    .map((value) => new Date(value))
    .filter((date) => !Number.isNaN(date.getTime()));

  if (!dates.length) {
    els.lastUpdated.textContent = "N/A";
    return;
  }

  const latest = new Date(Math.max(...dates.map((date) => date.getTime())));
  els.lastUpdated.textContent = `${formatDateTime(latest)} KST`;
}

function renderWatchlist() {
  const filteredCompanies = getCompaniesWithWatchlist().filter((company) => {
    const searchMatch = !state.watchlistSearch
      || `${company.name} ${company.code}`.toLocaleLowerCase("ko-KR").includes(state.watchlistSearch);
    const categoryMatch = state.watchlistCategoryFilter === "all" || company.category === state.watchlistCategoryFilter;
    const tierMatch = state.watchlistTierFilter === "all" || company.monitoringTier === state.watchlistTierFilter;
    return searchMatch && categoryMatch && tierMatch;
  });
  const latestDisclosureByCode = Object.fromEntries(
    state.disclosureData.companies.map((company) => [company.stockCode, company.latestDisclosureAt])
  );
  const companies = window.WatchlistSort.sortCompanies(
    filteredCompanies,
    state.watchlistSortMode,
    latestDisclosureByCode
  );
  els.watchlistSortButtons.forEach((button) => {
    const isSelected = button.dataset.sortMode === state.watchlistSortMode;
    button.setAttribute("aria-pressed", String(isSelected));
    button.classList.toggle("active", isSelected);
  });
  const visibleCompanies = companies.slice(0, state.watchlistVisibleLimit);
  els.watchlistSummary.innerHTML = visibleCompanies.map((company) => {
    const latest = getLatestQuarter(company);
    const isActive = company.code === state.selectedCompanyCode;
    const quarters = getEightQuarters(company);
    const disclosureSummary = getDisclosureSummary(company.code);
    const disclosureCount = disclosureSummary?.disclosureCount ?? getDisclosuresForCompany(company.code).length;
    const latestDisclosureDate = window.WatchlistSort.formatDisclosureDate(disclosureSummary?.latestDisclosureAt);
    const status = getWatchlistStatus(company, disclosureCount);
    const revenueQoq = getQoQText(quarters, "revenue").replace("QoQ ", "");
    const operatingQoq = getQoQText(quarters, "operatingIncome").replace("QoQ ", "");

    return `
      <button class="watchlist-item${isActive ? " active" : ""}" type="button" data-code="${company.code}">
        <span class="watchlist-company">
          <span class="chip ${status.tone}">${status.label}</span>
          <strong>${escapeHtml(company.name)}</strong>
          <span>${escapeHtml(company.code)} · ${escapeHtml(company.category || "N/A")} · ${escapeHtml(tierLabel(company.monitoringTier))}</span>
          <span class="watchlist-disclosure-date">최근 공시 ${latestDisclosureDate || "없음"}</span>
        </span>
        <span class="watchlist-metrics">
          <span class="watchlist-metric">
            <span>매출액</span>
            <strong>${formatMoney(latest?.revenue)}</strong>
            <small>${latest?.period || "N/A"} · ${revenueQoq}</small>
          </span>
          <span class="watchlist-metric">
            <span>영업이익</span>
            <strong>${formatMoney(latest?.operatingIncome)}</strong>
            <small>${latest?.period || "N/A"} · ${operatingQoq}</small>
          </span>
        </span>
        <span class="watchlist-chart">${createWatchlistChart(company)}</span>
        <span class="watchlist-action">상세 보기</span>
      </button>
    `;
  }).join("");
  if (!visibleCompanies.length) {
    els.watchlistSummary.innerHTML = `<div class="empty-state">검색 결과가 없습니다.</div>`;
  }
  els.watchlistLoadMore.hidden = visibleCompanies.length >= companies.length;
  els.watchlistLoadMore.textContent = `관심 기업 더 보기 (${visibleCompanies.length}/${companies.length})`;

  els.watchlistSummary.querySelectorAll(".watchlist-item").forEach((card) => {
    card.addEventListener("click", () => {
      openCompanyDetail(card.dataset.code);
    });
  });
}

function tierLabel(tier) {
  return { core: "Core", watch: "Watch", background: "Background" }[tier] || "N/A";
}

async function openCompanyDetail(code) {
  state.selectedCompanyCode = code;
  state.activeTab = "earnings";
  renderTabs();
  renderWatchlist();
  await loadCompanyDetails(code);
  renderSelectedCompany();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function loadCompanyDetails(code) {
  if (!code || state.loadedCompanyDetails.has(code) || window.location.protocol === "file:") return;
  const [earnings, disclosures, news] = await Promise.all([
    loadOptionalJson(`./data/earnings/by-company/${encodeURIComponent(code)}.json`),
    loadOptionalJson(`./data/disclosures/by-company/${encodeURIComponent(code)}.json`),
    loadOptionalJson(`./data/news/by-company/${encodeURIComponent(code)}.json`)
  ]);

  if (earnings?.company) {
    state.earningsData.companies = state.earningsData.companies
      .filter((item) => item.code !== code)
      .concat(earnings.company);
  }
  if (Array.isArray(disclosures?.disclosures)) {
    state.disclosureData.disclosures = state.disclosureData.disclosures
      .filter((item) => item.code !== code)
      .concat(disclosures.disclosures);
  }
  if (Array.isArray(news?.news)) {
    state.newsData.news = state.newsData.news
      .filter((item) => item.stock_code !== code)
      .concat(news.news);
  }
  state.loadedCompanyDetails.add(code);
}

function renderSelectedCompany() {
  const company = getCompanyByCode(state.selectedCompanyCode);
  if (!company) return;

  const quarters = getEightQuarters(company);
  const latest = getLatestQuarter(company);
  const recentDisclosures = getDisclosuresForCompany(company.code).slice(0, 10);
  const status = getCompanyStatus(company, recentDisclosures);

  els.selectedCompanyName.textContent = company.name;
  const completion = completionLabel(company.completionStatus);
  const missing = Array.isArray(company.missingQuarters) && company.missingQuarters.length
    ? ` · 누락 ${company.missingQuarters.join(", ")}`
    : "";
  els.selectedCompanyMeta.textContent = `${company.code} · ${company.category || company.market || "N/A"} · ${completion} · 기준 ${company.currentBasis || "N/A"}${missing}`;
  els.selectedStatus.textContent = status.label;
  els.selectedStatus.className = `status-pill ${status.tone}`;

  els.metricRow.innerHTML = [
    metricBox("매출액", latest?.revenue, latest?.period, getQoQText(quarters, "revenue")),
    metricBox("영업이익", latest?.operatingIncome, latest?.period, getQoQText(quarters, "operatingIncome")),
    metricBox("순이익", latest?.netIncome, latest?.period, getQoQText(quarters, "netIncome"))
  ].join("");

  const hasEstimate = quarters.some((quarter) => {
    return isNumber(quarter.estimateRevenue) || isNumber(quarter.estimateOperatingIncome) || isNumber(quarter.estimateNetIncome);
  });
  els.estimateNotice.textContent = hasEstimate ? "예상치 선 표시" : "예상치 N/A";

  els.mainChart.innerHTML = createMainChart(quarters);
  els.quarterTable.innerHTML = quarters.map((quarter) => quarterRow(quarter, quarters)).join("");
  renderRecentDisclosures(recentDisclosures);
  renderRecentNews(company);
}

function renderRecentDisclosures(items) {
  els.disclosureCount.textContent = `${items.length}건`;

  if (!items.length) {
    els.recentDisclosures.innerHTML = `<div class="empty-state">최근 공시 N/A</div>`;
    return;
  }

  els.recentDisclosures.innerHTML = items.map((item) => `
    <article class="compact-item">
      <strong>${escapeHtml(item.reportName)}</strong>
      <span class="compact-meta">
        <span>${formatDateTime(new Date(item.disclosedAt))}</span>
        <span>${escapeHtml(item.category)}</span>
        <span>잠정실적 ${item.provisionalEarnings ? "Y" : "N"}</span>
      </span>
      <p>${escapeHtml(item.summary || "요약 N/A")}</p>
      <p><a href="${escapeAttribute(item.dartUrl)}" target="_blank" rel="noopener">DART 원문</a></p>
    </article>
  `).join("");
}

function renderRecentNews(company) {
  const news = state.newsData.news
    .filter((item) => item.stock_code === company.code)
    .sort((a, b) => newsTimestamp(b) - newsTimestamp(a))
    .slice(0, 5);
  if (!news.length) {
    els.recentNews.innerHTML = `<div class="empty-state">최근 뉴스 N/A</div>`;
    return;
  }

  els.recentNews.innerHTML = news.map((item) => `
    <article class="compact-item">
      <strong>${escapeHtml(item.representative_title || "제목 N/A")}</strong>
      <span class="compact-meta">
        <span>${escapeHtml(item.representative_source || "출처 N/A")}</span>
        <span>${item.last_published_at || item.published_at ? formatDateTime(new Date(item.last_published_at || item.published_at)) : "시각 N/A"}</span>
        <span>${escapeHtml(importanceLabel(item.importance_level))}</span>
      </span>
      ${item.representative_url ? `<p><a href="${escapeAttribute(item.representative_url)}" target="_blank" rel="noopener">뉴스 원문</a></p>` : ""}
    </article>
  `).join("");
}

function renderFilters() {
  const companies = getCompaniesWithWatchlist();
  els.companyFilter.innerHTML = [
    `<option value="all">전체 기업</option>`,
    ...companies.map((company) => `<option value="${escapeAttribute(company.code)}">${escapeHtml(company.name)} ${escapeHtml(company.code)}</option>`)
  ].join("");

  els.typeFilter.innerHTML = [
    `<option value="all">전체 유형</option>`,
    ...state.disclosureData.categories.map((category) => `<option value="${escapeAttribute(category)}">${escapeHtml(category)}</option>`)
  ].join("");
}

function renderDisclosureList() {
  const items = state.disclosureData.disclosures
    .filter((item) => state.companyFilter === "all" || item.code === state.companyFilter)
    .filter((item) => state.typeFilter === "all" || item.category === state.typeFilter)
    .sort((a, b) => new Date(b.disclosedAt) - new Date(a.disclosedAt));

  if (!items.length) {
    els.disclosureList.innerHTML = `<div class="empty-state">조건에 맞는 공시가 없습니다.</div>`;
    return;
  }

  els.disclosureList.innerHTML = items.map((item) => `
    <article class="disclosure-row">
      <div class="disclosure-time">${formatDateTime(new Date(item.disclosedAt))}</div>
      <div class="disclosure-company">
        <strong>${escapeHtml(item.companyName)}</strong>
        <span>${escapeHtml(item.code)}</span>
      </div>
      <div class="disclosure-report">
        <strong>${escapeHtml(item.reportName)}</strong>
        <span class="chip">${escapeHtml(item.category)}</span>
        <span class="chip neutral">잠정실적 ${item.provisionalEarnings ? "Y" : "N"}</span>
      </div>
      <div class="disclosure-summary">${escapeHtml(item.summary || "요약 N/A")}</div>
      <div class="disclosure-link"><a href="${escapeAttribute(item.dartUrl)}" target="_blank" rel="noopener">DART 원문</a></div>
    </article>
  `).join("");
}

function renderNewsFilters() {
  const companies = getCompaniesWithWatchlist();
  els.newsCompanyFilter.innerHTML = [
    `<option value="all">전체 기업</option>`,
    ...companies.map((company) => `<option value="${escapeAttribute(company.code)}">${escapeHtml(company.name)} ${escapeHtml(company.code)}</option>`)
  ].join("");
  els.newsCompanyFilter.value = state.newsCompanyFilter;
}

function renderNews() {
  const items = getFilteredNews();
  const coreItems = items.filter((item) => item.importance_score >= 40);
  const visibleItems = items.slice(0, state.newsVisibleLimit);
  els.coreNewsCount.textContent = `${coreItems.length}건`;
  els.allNewsCount.textContent = `${items.length}건`;
  els.coreNewsList.innerHTML = coreItems.length
    ? coreItems.map(newsCard).join("")
    : `<div class="empty-state">조건에 맞는 핵심 뉴스가 없습니다.</div>`;
  els.allNewsList.innerHTML = visibleItems.length
    ? visibleItems.map(newsCard).join("")
    : `<div class="empty-state">조건에 맞는 뉴스가 없습니다.</div>`;
  els.newsLoadMore.hidden = visibleItems.length >= items.length;
  els.newsLoadMore.textContent = `뉴스 더 보기 (${visibleItems.length}/${items.length})`;
}

function getFilteredNews() {
  const periodDays = Number(state.newsPeriodFilter) || 7;
  const cutoff = Date.now() - periodDays * 24 * 60 * 60 * 1000;
  const items = state.newsData.news
    .filter((item) => state.newsCompanyFilter === "all" || item.stock_code === state.newsCompanyFilter)
    .filter((item) => state.newsRegionFilter === "all" || newsRegions(item).includes(state.newsRegionFilter))
    .filter((item) => state.newsProviderFilter === "all" || newsProviders(item).includes(state.newsProviderFilter))
    .filter((item) => state.newsImportanceFilter === "all" || item.importance_level === state.newsImportanceFilter)
    .filter((item) => {
      const timestamp = newsTimestamp(item);
      return Number.isFinite(timestamp) && timestamp >= cutoff;
    });

  return items.sort((a, b) => {
    if (state.newsSortFilter === "importance") {
      return b.importance_score - a.importance_score || newsTimestamp(b) - newsTimestamp(a);
    }
    return newsTimestamp(b) - newsTimestamp(a) || b.importance_score - a.importance_score;
  });
}

function newsTimestamp(item) {
  return new Date(item.last_published_at || item.published_at).getTime();
}

function newsRegions(item) {
  const domestic = Number(item.domestic_article_count) || 0;
  const international = Number(item.international_article_count) || 0;
  if (domestic && international) return ["domestic", "international", "both"];
  if (domestic) return ["domestic"];
  if (international) return ["international"];
  const language = String(item.language || item.representative_language || "").toLowerCase();
  return language.includes("korean") ? ["domestic"] : ["international"];
}

function newsProviders(item) {
  const providers = Array.isArray(item.providers)
    ? item.providers.map((value) => String(value).toLowerCase())
    : ["gdelt"];
  return providers.includes("gdelt") && providers.includes("naver") ? [...providers, "both"] : providers;
}

function newsCard(item) {
  const categories = Array.isArray(item.categories) && item.categories.length ? item.categories : ["기타"];
  const level = item.importance_level || "low";
  const providers = newsProviders(item).filter((provider) => provider !== "both");
  const providerLabel = providers.includes("gdelt") && providers.includes("naver") ? "BOTH" : (providers[0] || "gdelt").toUpperCase();
  const articles = Array.isArray(item.articles) ? item.articles : [];
  const relatedArticles = articles.map((article) => `
    <li>
      <a href="${escapeAttribute(article.url)}" target="_blank" rel="noopener">${escapeHtml(article.title || "제목 N/A")}</a>
      <span>${escapeHtml(article.source || "출처 N/A")} · ${formatDateTime(new Date(article.published_at))} · ${escapeHtml(article.provider || "")}</span>
    </li>
  `).join("");
  return `
    <article class="news-card ${escapeAttribute(level)}">
      <div class="news-card-head">
        <span class="importance-badge ${escapeAttribute(level)}">${escapeHtml(importanceLabel(level))} ${Number(item.importance_score) || 0}</span>
        <span class="provider-badge">${escapeHtml(providerLabel)}</span>
        <span>${escapeHtml(item.company_name || "기업 N/A")} · ${escapeHtml(item.stock_code || "N/A")}</span>
      </div>
      <h3>${escapeHtml(item.representative_title || "제목 N/A")}</h3>
      <div class="news-meta">
        <span>${escapeHtml(item.representative_source || "출처 N/A")}</span>
        <span>최초 ${formatDateTime(new Date(item.first_published_at || item.published_at))}</span>
        <span>최신 ${formatDateTime(new Date(item.last_published_at || item.published_at))}</span>
        <span>국내 ${Number(item.domestic_article_count) || 0} · 해외 ${Number(item.international_article_count) || 0} · 총 ${Number(item.article_count || item.source_count) || 0}</span>
      </div>
      <div class="news-categories">
        ${categories.map((category) => `<span class="chip neutral">${escapeHtml(category)}</span>`).join("")}
      </div>
      <a class="news-link" href="${escapeAttribute(item.representative_url)}" target="_blank" rel="noopener">원문 보기</a>
      ${relatedArticles ? `<details class="related-news"><summary>관련 기사 ${articles.length}건</summary><ul>${relatedArticles}</ul></details>` : ""}
    </article>
  `;
}

function importanceLabel(level) {
  return {
    critical: "Critical",
    important: "Important",
    watch: "Watch",
    low: "Low"
  }[level] || "Low";
}

function getCompaniesWithWatchlist() {
  return state.earningsData.watchlist.map((watch) => {
    const company = getCompanyByCode(watch.code);
    return {
      ...watch,
      ...(company || {}),
      name: company?.name || watch.name,
      code: watch.code,
      market: company?.market || watch.market
    };
  });
}

function getCompanyByCode(code) {
  return state.earningsData.companies.find((company) => company.code === code);
}

function pickInitialCompany() {
  const withData = state.earningsData.companies.find((company) => getLatestQuarter(company));
  return withData?.code || state.earningsData.watchlist[0]?.code || "";
}

function getEightQuarters(company) {
  const earnings = Array.isArray(company.earnings) ? company.earnings : [];
  return earnings.slice(-8);
}

function getLatestQuarter(company) {
  const quarters = getEightQuarters(company);
  return [...quarters].reverse().find((quarter) => {
    return isNumber(quarter.revenue) || isNumber(quarter.operatingIncome) || isNumber(quarter.netIncome);
  });
}

function getDisclosuresForCompany(code) {
  return state.disclosureData.disclosures
    .filter((item) => item.code === code)
    .sort((a, b) => new Date(b.disclosedAt) - new Date(a.disclosedAt));
}

function getDisclosureSummary(code) {
  return state.disclosureData.companies.find((company) => company.stockCode === code);
}

function getCompanyStatus(company, disclosures) {
  if (company.completionStatus === "complete_8q" && disclosures.length) return { label: "8분기·공시", tone: "" };
  if (company.completionStatus === "complete_8q") return { label: "8분기 확보", tone: "" };
  if (company.completionStatus === "needs_review" || company.completionStatus === "conflicting_data") return { label: "검토 필요", tone: "warn" };
  const latest = getLatestQuarter(company);
  if (!latest && !disclosures.length) return { label: "N/A", tone: "neutral" };
  if (disclosures.length) return { label: "공시 확인", tone: "" };
  return { label: "실적 확인", tone: "" };
}

function getWatchlistStatus(company, disclosureCount) {
  if (company.completionStatus === "complete_8q" && disclosureCount > 0) return { label: "8분기·공시", tone: "" };
  if (company.completionStatus === "complete_8q") return { label: "8분기", tone: "" };
  if (company.completionStatus === "needs_review" || company.completionStatus === "conflicting_data") return { label: "검토 필요", tone: "warn" };
  const hasEarnings = Boolean(getLatestQuarter(company));
  if (hasEarnings && disclosureCount > 0) return { label: "실적·공시", tone: "" };
  if (hasEarnings) return { label: "실적", tone: "" };
  if (disclosureCount > 0) return { label: "공시", tone: "warn" };
  return { label: "N/A", tone: "neutral" };
}

function completionLabel(status) {
  return {
    complete_8q: "최근 8개 분기",
    partial_5_to_7q: "5~7개 분기",
    partial_1_to_4q: "1~4개 분기",
    no_valid_quarter: "실적 N/A",
    needs_review: "검토 필요",
    conflicting_data: "충돌 검토"
  }[status] || "분기 상태 N/A";
}

function metricBox(label, value, period, changeText) {
  const changeClass = getTextTone(changeText);
  return `
    <div class="metric-box">
      <span>${label}</span>
      <strong>${formatMoney(value)}</strong>
      <small>${period || "N/A"} · <span class="${changeClass}">${changeText}</span></small>
    </div>
  `;
}

function getQoQText(quarters, key) {
  const latestIndex = findLatestIndex(quarters, key);
  if (latestIndex < 0) return "QoQ N/A";
  const current = quarters[latestIndex];
  const previous = findQuarter(quarters, shiftQuarter(current.period, -1));
  return `QoQ ${formatChange(current[key], previous?.[key])}`;
}

function findLatestIndex(quarters, key) {
  for (let index = quarters.length - 1; index >= 0; index -= 1) {
    if (isNumber(quarters[index][key])) return index;
  }
  return -1;
}

function quarterRow(quarter, quarters) {
  const badges = [
    quarter.provisional === true ? "잠정" : "",
    quarter.corrected ? "정정" : ""
  ].filter(Boolean);
  return `
    <tr>
      <td>${escapeHtml(quarter.period)} ${badges.map((badge) => `<span class="quarter-badge">${badge}</span>`).join(" ")}</td>
      <td>${formatMoney(quarter.revenue)}</td>
      <td class="${getTextTone(getYoY(quarter, quarters, "revenue"))}">${getYoY(quarter, quarters, "revenue")}</td>
      <td class="${getTextTone(getQoQ(quarter, quarters, "revenue"))}">${getQoQ(quarter, quarters, "revenue")}</td>
      <td>${formatMoney(quarter.operatingIncome)}</td>
      <td class="${getTextTone(getYoY(quarter, quarters, "operatingIncome"))}">${getYoY(quarter, quarters, "operatingIncome")}</td>
      <td class="${getTextTone(getQoQ(quarter, quarters, "operatingIncome"))}">${getQoQ(quarter, quarters, "operatingIncome")}</td>
      <td>${formatMoney(quarter.netIncome)}</td>
      <td class="${getTextTone(getYoY(quarter, quarters, "netIncome"))}">${getYoY(quarter, quarters, "netIncome")}</td>
      <td class="${getTextTone(getQoQ(quarter, quarters, "netIncome"))}">${getQoQ(quarter, quarters, "netIncome")}</td>
      <td>${formatEstimateGap(quarter)}</td>
    </tr>
  `;
}

function getYoY(quarter, quarters, key) {
  const previous = findQuarter(quarters, shiftQuarter(quarter.period, -4));
  return formatChange(quarter[key], previous?.[key]);
}

function getQoQ(quarter, quarters, key) {
  const previous = findQuarter(quarters, shiftQuarter(quarter.period, -1));
  return formatChange(quarter[key], previous?.[key]);
}

function findQuarter(quarters, period) {
  if (!period) return null;
  return quarters.find((item) => item.period === period) || null;
}

function shiftQuarter(period, offset) {
  const match = /^(\d{4}) Q([1-4])$/.exec(period || "");
  if (!match) return null;
  const absoluteQuarter = Number(match[1]) * 4 + Number(match[2]) - 1 + offset;
  const year = Math.floor(absoluteQuarter / 4);
  const quarter = (absoluteQuarter % 4) + 1;
  return `${year} Q${quarter}`;
}

function formatChange(current, previous) {
  if (!isNumber(current) || !isNumber(previous)) return "N/A";
  if (previous < 0 && current > 0) return "흑자전환";
  if (previous > 0 && current < 0) return "적자전환";
  if (previous < 0 && current < 0) {
    if (current > previous) return "적자축소";
    if (current < previous) return "적자확대";
    return "적자지속";
  }
  if (previous === 0) {
    if (current > 0) return "흑자전환";
    if (current < 0) return "적자전환";
    return "변동 없음";
  }

  const percentage = ((current - previous) / Math.abs(previous)) * 100;
  const sign = percentage > 0 ? "+" : "";
  return `${sign}${percentage.toFixed(1)}%`;
}

function formatEstimateGap(quarter) {
  const pairs = [
    ["revenue", "estimateRevenue"],
    ["operatingIncome", "estimateOperatingIncome"],
    ["netIncome", "estimateNetIncome"]
  ];

  const available = pairs
    .map(([actualKey, estimateKey]) => {
      if (!isNumber(quarter[actualKey]) || !isNumber(quarter[estimateKey])) return null;
      return formatChange(quarter[actualKey], quarter[estimateKey]);
    })
    .filter(Boolean);

  return available.length ? available.join(" / ") : "N/A";
}

function createWatchlistChart(company) {
  const quarters = getEightQuarters(company);
  const revenueValues = quarters.map((quarter) => quarter.revenue).filter(isNumber);
  const operatingValues = quarters.map((quarter) => quarter.operatingIncome).filter(isNumber);

  if (!revenueValues.length && !operatingValues.length) {
    return `<svg viewBox="0 0 430 118" role="img" aria-label="실적 데이터 없음">
      <rect x="1" y="1" width="428" height="116" rx="8" fill="#f8f8f5" stroke="#dfe3df"></rect>
      <text x="215" y="64" text-anchor="middle" class="axis-label">N/A</text>
    </svg>`;
  }

  const lanes = [
    { label: "매출", key: "revenue", values: revenueValues, className: "bar-revenue", baseline: 50 },
    { label: "영업익", key: "operatingIncome", values: operatingValues, className: "bar-operating", baseline: 98 }
  ];
  const startX = 78;
  const barWidth = 24;
  const gap = 12;
  const maxHeight = 34;

  const rows = lanes.map((lane) => {
    const max = lane.values.length ? Math.max(...lane.values, 1) : 1;
    const bars = quarters.map((quarter, index) => {
      const x = startX + index * (barWidth + gap);
      if (!isNumber(quarter[lane.key])) {
        return `<path class="na-slot" d="M${x},${lane.baseline} L${x + barWidth},${lane.baseline} L${x + barWidth},${lane.baseline - maxHeight} L${x},${lane.baseline - maxHeight} Z"></path>`;
      }
      const height = Math.max((quarter[lane.key] / max) * maxHeight, 3);
      const y = lane.baseline - height;
      return `<rect x="${x}" y="${y}" width="${barWidth}" height="${height}" rx="3" class="${lane.className}"></rect>`;
    }).join("");

    return `
      <g>
        <text x="16" y="${lane.baseline - 10}" class="axis-label">${lane.label}</text>
        <line x1="${startX - 6}" y1="${lane.baseline}" x2="392" y2="${lane.baseline}" class="axis-line"></line>
        ${bars}
      </g>
    `;
  }).join("");

  const firstPeriod = quarters[0]?.period || "N/A";
  const lastPeriod = quarters[quarters.length - 1]?.period || "N/A";

  return `<svg viewBox="0 0 430 118" role="img" aria-label="${escapeAttribute(company.name)} 최근 8개 분기 매출 및 영업이익 미니 차트">
    <rect x="1" y="1" width="428" height="116" rx="8" fill="#fcfcfa" stroke="#dfe3df"></rect>
    ${rows}
    <text x="${startX}" y="112" class="axis-label">${escapeHtml(firstPeriod)}</text>
    <text x="392" y="112" text-anchor="end" class="axis-label">${escapeHtml(lastPeriod)}</text>
  </svg>`;
}

function createMainChart(quarters) {
  if (!quarters.length) {
    return `<div class="empty-state">최근 8개 분기 실적 N/A</div>`;
  }

  const metrics = [
    { key: "revenue", estimateKey: "estimateRevenue", className: "bar-revenue" },
    { key: "operatingIncome", estimateKey: "estimateOperatingIncome", className: "bar-operating" },
    { key: "netIncome", estimateKey: "estimateNetIncome", className: "bar-net" }
  ];

  const allValues = quarters.flatMap((quarter) => metrics.flatMap((metric) => [quarter[metric.key], quarter[metric.estimateKey]])).filter(isNumber);
  const max = allValues.length ? Math.max(...allValues, 1) : 1;
  const width = 980;
  const height = 340;
  const padding = { top: 30, right: 26, bottom: 58, left: 58 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const groupWidth = chartWidth / quarters.length;
  const barWidth = Math.min(22, groupWidth / 5);
  const baseline = padding.top + chartHeight;

  const y = (value) => baseline - (value / max) * chartHeight;
  const gridLines = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const lineY = baseline - ratio * chartHeight;
    const label = Math.round(max * ratio).toLocaleString("ko-KR");
    return `
      <line x1="${padding.left}" y1="${lineY}" x2="${width - padding.right}" y2="${lineY}" class="axis-line"></line>
      <text x="${padding.left - 10}" y="${lineY + 4}" text-anchor="end" class="axis-label">${label}</text>
    `;
  }).join("");

  const bars = quarters.map((quarter, quarterIndex) => {
    const groupX = padding.left + quarterIndex * groupWidth;
    const center = groupX + groupWidth / 2;
    const barStart = center - (barWidth * metrics.length + 5 * 2) / 2;
    const slotTop = padding.top + 18;

    const metricBars = metrics.map((metric, metricIndex) => {
      const x = barStart + metricIndex * (barWidth + 5);
      const value = quarter[metric.key];
      if (!isNumber(value)) {
        return `<path class="na-slot" d="M${x},${baseline} L${x + barWidth},${baseline} L${x + barWidth},${slotTop} L${x},${slotTop} Z"></path>`;
      }
      const barY = y(value);
      const barHeight = Math.max(baseline - barY, 3);
      return `<rect x="${x}" y="${barY}" width="${barWidth}" height="${barHeight}" rx="3" class="${metric.className}"></rect>`;
    }).join("");

    return `
      <g>
        ${metricBars}
        <text x="${center}" y="${height - 25}" text-anchor="middle" class="axis-label">${escapeHtml(quarter.period.replace(" ", "\u00a0"))}</text>
      </g>
    `;
  }).join("");

  const estimateLines = metrics.map((metric) => {
    const points = quarters.map((quarter, index) => {
      if (!isNumber(quarter[metric.estimateKey])) return null;
      const center = padding.left + index * groupWidth + groupWidth / 2;
      return `${center},${y(quarter[metric.estimateKey])}`;
    }).filter(Boolean);

    if (points.length < 2) return "";
    return `<polyline points="${points.join(" ")}" class="estimate-line"></polyline>`;
  }).join("");

  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="최근 8개 분기 매출액 영업이익 순이익 막대그래프">
      <rect x="0" y="0" width="${width}" height="${height}" fill="#fcfcfa"></rect>
      ${gridLines}
      <line x1="${padding.left}" y1="${baseline}" x2="${width - padding.right}" y2="${baseline}" class="axis-line"></line>
      ${bars}
      ${estimateLines}
    </svg>
  `;
}

function formatMoney(value) {
  if (!isNumber(value)) return "N/A";
  return `${value.toLocaleString("ko-KR")}억`;
}

function formatDateTime(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "N/A";

  const parts = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).formatToParts(date).reduce((acc, part) => {
    acc[part.type] = part.value;
    return acc;
  }, {});

  return `${parts.year}.${parts.month}.${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

function getTextTone(text) {
  if (!text || text === "N/A" || text.includes("변동 없음")) return "";
  if (text.includes("적자전환") || text.includes("적자확대") || text.startsWith("-")) return "negative";
  if (text.includes("흑자전환") || text.includes("적자축소") || text.startsWith("+")) return "positive";
  return "";
}

function isNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function debounce(fn, delay) {
  let timer = null;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
