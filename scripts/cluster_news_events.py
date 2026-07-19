import hashlib
from datetime import datetime, timezone
from difflib import SequenceMatcher

try:
    from .normalize_news import assert_public_article
    from .score_news import domain_matches, normalize_title, normalize_url, parse_datetime
except ImportError:
    from normalize_news import assert_public_article
    from score_news import domain_matches, normalize_title, normalize_url, parse_datetime


PIPELINE_VERSION = "2.0.0"
STOCK_NOISE = ("주가", "목표주가", "종목 추천", "급등", "shares up", "shares down", "price target", "stock picks", "etf")
MATERIAL_SIGNALS = {"investment", "production", "supply", "regulation", "earnings", "personnel", "m_and_a"}


def _merge_article(existing, incoming):
    providers = sorted(set(existing.get("providers", [existing.get("provider")])) | set(incoming.get("providers", [incoming.get("provider")])))
    existing["providers"] = [item for item in providers if item]
    existing["provider"] = "both" if len(existing["providers"]) > 1 else existing["providers"][0]
    existing["event_keywords"] = sorted(set(existing.get("event_keywords", [])) | set(incoming.get("event_keywords", [])))
    existing["categories"] = sorted(set(existing.get("categories", [])) | set(incoming.get("categories", [])))
    if incoming.get("source_tier") in {"official", "tier1"} and existing.get("source_tier") == "other":
        for key in ("url", "canonical_url", "source_domain", "source_name", "source_tier", "official_source"):
            existing[key] = incoming.get(key)
    return existing


def deduplicate_standard_articles(articles):
    unique = []
    by_url = {}
    by_title = {}
    cross_provider_url_duplicates = 0
    for incoming in sorted(articles, key=lambda item: item.get("published_at") or ""):
        url_key = normalize_url(incoming.get("canonical_url") or incoming.get("url"))
        title_key = incoming.get("normalized_title") or normalize_title(incoming.get("title"))
        index = by_url.get(url_key) if url_key else None
        if index is None and title_key:
            index = by_title.get(title_key)
        if index is not None:
            before = set(unique[index].get("providers", []))
            after = set(incoming.get("providers", [incoming.get("provider")]))
            if url_key and before != after and before.isdisjoint(after):
                cross_provider_url_duplicates += 1
            _merge_article(unique[index], incoming)
            continue
        index = len(unique)
        unique.append(dict(incoming))
        if url_key:
            by_url[url_key] = index
        if title_key:
            by_title[title_key] = index
    return unique, {"removed_count": len(articles) - len(unique), "cross_provider_url_duplicates": cross_provider_url_duplicates}


def _same_event(first, second):
    if first.get("stock_code") != second.get("stock_code"):
        return False
    first_time = parse_datetime(first.get("published_at"))
    second_time = parse_datetime(second.get("published_at"))
    if first_time and second_time and abs((first_time - second_time).total_seconds()) > 72 * 3600:
        return False
    common = set(first.get("event_keywords", [])) & set(second.get("event_keywords", []))
    ratio = SequenceMatcher(None, first.get("normalized_title", ""), second.get("normalized_title", "")).ratio()
    if ratio >= 0.82:
        return True
    return len(common) >= 2


def cluster_event_articles(articles):
    ordered = sorted(articles, key=lambda item: item.get("published_at") or "")
    parents = list(range(len(ordered)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(ordered)):
        for right in range(left + 1, len(ordered)):
            if _same_event(ordered[left], ordered[right]):
                union(left, right)
    components = {}
    for index, article in enumerate(ordered):
        components.setdefault(find(index), []).append(article)
    return [{"articles": members} for members in components.values()]


def _representative_rank(article, company):
    tier = {"official": 4, "tier1": 3, "other": 1}.get(article.get("source_tier"), 1)
    korean_major = 1 if article.get("region") == "domestic" and article.get("source_tier") == "tier1" else 0
    direct = 1 if article.get("matched_alias") else 0
    timestamp = parse_datetime(article.get("published_at")) or datetime.max.replace(tzinfo=timezone.utc)
    return (-tier, -korean_major, -direct, timestamp)


def score_event(cluster, company, now=None):
    now = now or datetime.now(timezone.utc)
    articles = cluster["articles"]
    representative = cluster["representative_article"]
    score, reasons = 0, []
    domains = set(cluster["source_domains"])
    if any(article.get("official_source") for article in articles):
        score += 35; reasons.append("공식 기업·규제기관 출처 +35")
    if any(article.get("source_tier") == "tier1" for article in articles):
        score += 20; reasons.append("Tier 1 출처 +20")
    if representative.get("matched_alias"):
        score += 10; reasons.append("회사명이 제목에 정확히 등장 +10")
    important = {normalize_title(item) for item in company.get("important_keywords", [])}
    combined = normalize_title(" ".join(article.get("title", "") for article in articles))
    keyword_score = min(20, sum(item in combined for item in important if item) * 5)
    if keyword_score:
        score += keyword_score; reasons.append(f"핵심 키워드 +{keyword_score}")
    if cluster["domestic_article_count"] and cluster["international_article_count"]:
        score += 10; reasons.append("국내·해외 교차 보도 +10")
    trusted_domains = {article.get("source_domain") for article in articles if article.get("source_tier") in {"official", "tier1"}}
    if len(trusted_domains) >= 3:
        score += 10; reasons.append("서로 다른 신뢰 매체 3곳 이상 +10")
    latest = parse_datetime(cluster.get("last_published_at"))
    if latest and 0 <= (now - latest).total_seconds() <= 24 * 3600:
        score += 5; reasons.append("최근 24시간 +5")
    if set(cluster.get("event_keywords", [])) & MATERIAL_SIGNALS:
        score += 15; reasons.append("중요 사건 신호 +15")
    title = normalize_title(representative.get("title"))
    if any(normalize_title(term) in title for term in STOCK_NOISE):
        score -= 25; reasons.append("단순 주가·종목 추천 -25")
    score = max(0, min(100, score))
    level = "critical" if score >= 80 else "important" if score >= 60 else "watch" if score >= 40 else "low"
    return score, level, reasons


def build_public_event(cluster, company, now=None):
    articles = cluster["articles"]
    representative = sorted(articles, key=lambda item: _representative_rank(item, company))[0]
    times = [parse_datetime(item.get("published_at")) for item in articles]
    times = [item for item in times if item]
    domains = sorted({item.get("source_domain") for item in articles if item.get("source_domain")})
    providers = sorted({provider for item in articles for provider in item.get("providers", [item.get("provider")]) if provider})
    cluster.update({
        "representative_article": representative,
        "source_domains": domains,
        "domestic_article_count": sum(item.get("region") == "domestic" for item in articles),
        "international_article_count": sum(item.get("region") == "international" for item in articles),
        "event_keywords": sorted({keyword for item in articles for keyword in item.get("event_keywords", [])}),
        "first_published_at": min(times).isoformat().replace("+00:00", "Z") if times else None,
        "last_published_at": max(times).isoformat().replace("+00:00", "Z") if times else None,
    })
    score, level, reasons = score_event(cluster, company, now=now)
    anchor = f"{company['stock_code']}|{representative.get('canonical_url')}|{cluster['first_published_at']}"
    public_articles = []
    for item in sorted(articles, key=lambda value: value.get("published_at") or "", reverse=True):
        public = {
            "title": item.get("title"), "url": item.get("url"), "source": item.get("source_name"),
            "source_domain": item.get("source_domain"), "published_at": item.get("published_at"),
            "language": item.get("language"), "region": item.get("region"),
            "provider": "BOTH" if len(item.get("providers", [])) > 1 else item.get("provider", "").upper(),
        }
        assert_public_article(public)
        public_articles.append(public)
    return {
        "cluster_id": hashlib.sha256(anchor.encode("utf-8")).hexdigest()[:16],
        "company_name": company["company_name"], "stock_code": company["stock_code"],
        "representative_title": representative.get("title"), "representative_url": representative.get("url"),
        "representative_source": representative.get("source_name"), "representative_language": representative.get("language"),
        "first_published_at": cluster["first_published_at"], "last_published_at": cluster["last_published_at"],
        "article_count": len(articles), "domestic_article_count": cluster["domestic_article_count"],
        "international_article_count": cluster["international_article_count"], "providers": providers,
        "source_domains": domains, "categories": sorted({category for item in articles for category in item.get("categories", [])}),
        "event_keywords": cluster["event_keywords"], "importance_score": score, "importance_level": level,
        "scoring_reasons": reasons, "needs_review": len(articles) > 1 and len(cluster["event_keywords"]) < 2,
        "articles": public_articles,
    }
