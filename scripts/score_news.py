import hashlib
import html
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


PARSER_VERSION = "1.0.0"
AMBIGUOUS_ALIASES = {"sk", "hynix"}
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
    "campaign",
}
MARKET_ROUNDUP_TERMS = {
    "증시",
    "코스피",
    "코스닥",
    "마감",
    "장중",
    "종목 추천",
    "급등주",
    "top stocks",
    "stocks to watch",
    "stock picks",
    "market roundup",
    "price target",
    "목표주가",
}
STOCK_NOISE_TERMS = {
    "주가",
    "주식",
    "급등락",
    "변동성",
    "목표주가",
    "투자자",
    "보유",
    "팔지 말고",
    "shares down",
    "shares up",
    "plunges",
    "bullish signal",
    "stock market",
    "price target",
    "stock picks",
    "stocks to buy",
    "would be worth",
    "investors",
    "prediction",
    "leveraged etf",
    "bull 2x etf",
    "adr volatility",
}
OTHER_COMPANY_MARKERS = {
    "samsung",
    "tsmc",
    "nvidia",
    "apple",
    "meta",
    "alphabet",
    "spacex",
}
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "amid",
    "says",
    "will",
    "sk",
    "hynix",
    "하이닉스",
    "대한",
    "관련",
    "통해",
}


def canonical_domain(value):
    domain = (value or "").strip().lower().split(":", 1)[0]
    return domain[4:] if domain.startswith("www.") else domain


def domain_matches(domain, candidates):
    normalized = canonical_domain(domain)
    return any(
        normalized == canonical_domain(candidate)
        or normalized.endswith(f".{canonical_domain(candidate)}")
        for candidate in candidates
    )


def normalize_url(value):
    try:
        parts = urlsplit((value or "").strip())
    except ValueError:
        return ""
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""
    host = canonical_domain(parts.netloc)
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = []
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        lower_key = key.lower()
        if lower_key.startswith(TRACKING_QUERY_PREFIXES) or lower_key in TRACKING_QUERY_KEYS:
            continue
        query.append((key, val))
    query.sort()
    return urlunsplit(("https", host, path, urlencode(query), ""))


def normalize_title(value):
    title = unicodedata.normalize("NFKC", html.unescape(value or "")).lower().strip()
    title = re.sub(r"\s+[|\-–—]\s+[^|\-–—]{2,40}$", "", title)
    title = re.sub(r"[^0-9a-z가-힣]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def valid_aliases(company):
    aliases = company.get("aliases", []) + company.get("english_aliases", [])
    return [
        alias.strip()
        for alias in aliases
        if alias.strip() and alias.strip().lower() not in AMBIGUOUS_ALIASES
    ]


def alias_in_title(title, alias):
    if not title or not alias:
        return False
    if re.search(r"[가-힣]", alias):
        return alias in title
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])",
            title,
            re.IGNORECASE,
        )
    )


def match_company_alias(title, company):
    matches = [alias for alias in valid_aliases(company) if alias_in_title(title, alias)]
    return max(matches, key=len) if matches else None


def is_market_roundup(title):
    normalized = normalize_title(title)
    return any(term in normalized for term in MARKET_ROUNDUP_TERMS)


def assess_relevance(article, company):
    title = (article.get("title") or "").strip()
    if not title:
        return False, "missing_title", None
    if not normalize_url(article.get("url")):
        return False, "invalid_url", None
    alias = match_company_alias(title, company)
    if not alias:
        return False, "company_alias_not_in_title", None
    if is_market_roundup(title):
        return False, "market_roundup_or_stock_list", alias
    normalized = normalize_title(title)
    other_company_count = sum(marker in normalized for marker in OTHER_COMPANY_MARKERS)
    if "in the news" in normalized or (
        other_company_count >= 2 and any(term in normalized for term in STOCK_NOISE_TERMS)
    ):
        return False, "multi_company_market_article", alias
    if other_company_count >= 1 and re.search(r"\bblames?\b.*\bfor\b", normalized):
        return False, "other_company_is_main_topic", alias
    return True, None, alias


def parse_datetime(value):
    if isinstance(value, datetime):
        result = value
    else:
        text = (value or "").strip()
        result = None
        for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                result = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        if result is None:
            try:
                result = datetime.fromisoformat(text)
            except ValueError:
                return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def source_type(domain, company):
    if domain_matches(domain, company.get("official_sources", [])):
        return "official"
    if domain_matches(domain, company.get("major_source_domains", [])):
        return "major"
    return "other"


def deduplicate_articles(articles):
    unique = []
    by_url = {}
    by_title = {}
    duplicate_count = 0
    for article in articles:
        normalized_url = normalize_url(article.get("url"))
        normalized_title = normalize_title(article.get("title"))
        existing_index = by_url.get(normalized_url) if normalized_url else None
        if existing_index is None and normalized_title:
            existing_index = by_title.get(normalized_title)
        if existing_index is not None:
            duplicate_count += 1
            existing = unique[existing_index]
            if len(article.get("title") or "") > len(existing.get("title") or ""):
                unique[existing_index] = article
            continue
        index = len(unique)
        unique.append(article)
        if normalized_url:
            by_url[normalized_url] = index
        if normalized_title:
            by_title[normalized_title] = index
    return unique, duplicate_count


def title_tokens(title):
    return {
        token
        for token in re.findall(r"[a-z0-9]{2,}|[가-힣]{2,}", normalize_title(title))
        if token not in STOPWORDS
    }


def titles_same_event(first, second):
    first_title = normalize_title(first.get("title"))
    second_title = normalize_title(second.get("title"))
    if not first_title or not second_title:
        return False
    first_time = parse_datetime(first.get("published_at"))
    second_time = parse_datetime(second.get("published_at"))
    if first_time and second_time and abs((first_time - second_time).total_seconds()) > 72 * 3600:
        return False
    ratio = SequenceMatcher(None, first_title, second_title).ratio()
    first_tokens = title_tokens(first_title)
    second_tokens = title_tokens(second_title)
    union = first_tokens | second_tokens
    intersection = first_tokens & second_tokens
    jaccard = len(intersection) / len(union) if union else 0
    return ratio >= 0.72 or jaccard >= 0.5 or (len(intersection) >= 3 and jaccard >= 0.25)


def source_rank(article, company):
    article_source_type = article.get("source_type") or source_type(article.get("source_domain"), company)
    return {"official": 2, "major": 1, "other": 0}.get(article_source_type, 0)


def cluster_articles(articles, company):
    ordered = sorted(
        articles,
        key=lambda item: parse_datetime(item.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    parents = list(range(len(ordered)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first, second):
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    for first_index, first in enumerate(ordered):
        for second_index in range(first_index + 1, len(ordered)):
            if titles_same_event(first, ordered[second_index]):
                union(first_index, second_index)

    components = {}
    for index, article in enumerate(ordered):
        components.setdefault(find(index), []).append(article)
    clusters = [{"articles": members} for members in components.values()]

    for cluster in clusters:
        members = cluster["articles"]
        members.sort(
            key=lambda item: (
                source_rank(item, company),
                parse_datetime(item.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        representative = members[0]
        domains = sorted({canonical_domain(item.get("source_domain")) for item in members if item.get("source_domain")})
        published = [parse_datetime(item.get("published_at")) for item in members]
        published = [value for value in published if value]
        anchor = min(normalize_title(item.get("title")) for item in members)
        cluster["cluster_id"] = hashlib.sha256(
            f"{company['stock_code']}|{anchor}".encode("utf-8")
        ).hexdigest()[:16]
        cluster["representative_article"] = representative
        cluster["article_count"] = len(members)
        cluster["source_domains"] = domains
        cluster["first_published_at"] = min(published).isoformat().replace("+00:00", "Z") if published else None
        cluster["last_published_at"] = max(published).isoformat().replace("+00:00", "Z") if published else None
    return clusters


def categories_for_title(title):
    normalized = normalize_title(title)
    rules = [
        ("실적", ("실적", "earnings", "profit", "revenue")),
        ("투자·생산", ("투자", "fab", "공장", "생산", "capacity")),
        ("기술·제품", ("hbm", "dram", "nand", "memory", "메모리", "제품")),
        ("공급망·규제", ("수출", "규제", "export", "supply", "공급")),
        ("인사·M&A", ("인수", "합병", "ceo", "appoint", "acquisition")),
        ("주가·투자판단", ("주가", "목표주가", "stock", "shares", "price target")),
    ]
    categories = [label for label, keywords in rules if any(keyword in normalized for keyword in keywords)]
    return categories or ["기타"]


def score_cluster(cluster, company, now=None):
    now = now or datetime.now(timezone.utc)
    representative = cluster["representative_article"]
    title = representative.get("title") or ""
    domain = canonical_domain(representative.get("source_domain"))
    score = 0
    reasons = []

    if domain_matches(domain, company.get("official_sources", [])):
        score += 40
        reasons.append("공식 기업·기관 출처 +40")
    elif domain_matches(domain, company.get("major_source_domains", [])):
        score += 25
        reasons.append("주요 언론 출처 +25")

    matched = match_company_alias(title, company)
    if matched:
        score += 15
        reasons.append("회사명이 제목에 정확히 등장 +15")

    normalized_title = normalize_title(title)
    keyword_hits = [
        keyword
        for keyword in company.get("important_keywords", [])
        if normalize_title(keyword) in normalized_title
    ]
    keyword_score = min(20, len(keyword_hits) * 5)
    if keyword_score:
        score += keyword_score
        reasons.append(f"핵심 키워드 {len(keyword_hits)}개 +{keyword_score}")

    if len(cluster.get("source_domains", [])) >= 3:
        score += 15
        reasons.append("서로 다른 3개 이상 매체 보도 +15")

    published_at = parse_datetime(representative.get("published_at"))
    if published_at and 0 <= (now - published_at).total_seconds() <= 24 * 3600:
        score += 10
        reasons.append("최근 24시간 기사 +10")

    excluded_hits = [
        keyword
        for keyword in company.get("excluded_keywords", [])
        if normalize_title(keyword) in normalized_title
    ]
    if excluded_hits or any(term in normalized_title for term in STOCK_NOISE_TERMS):
        score -= 25
        reasons.append("단순 주가·종목 추천 성격 -25")

    if is_market_roundup(title):
        score -= 20
        reasons.append("시장 종합 기사 단순 언급 -20")

    score = max(0, min(100, score))
    if score >= 80:
        level = "critical"
    elif score >= 60:
        level = "important"
    elif score >= 40:
        level = "watch"
    else:
        level = "low"
    return score, level, reasons


def public_cluster(cluster, company, now=None):
    representative = cluster["representative_article"]
    score, level, reasons = score_cluster(cluster, company, now=now)
    return {
        "cluster_id": cluster["cluster_id"],
        "company_name": company["company_name"],
        "stock_code": company["stock_code"],
        "representative_title": representative.get("title"),
        "representative_url": normalize_url(representative.get("url")),
        "representative_source": canonical_domain(representative.get("source_domain")),
        "published_at": representative.get("published_at"),
        "source_count": len(cluster.get("source_domains", [])),
        "sources": cluster.get("source_domains", []),
        "language": representative.get("language") or "Unknown",
        "importance_score": score,
        "importance_level": level,
        "categories": categories_for_title(representative.get("title")),
        "scoring_reasons": reasons,
    }
