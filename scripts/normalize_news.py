import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

try:
    from .score_news import canonical_domain, match_company_alias, normalize_title, normalize_url, source_type
except ImportError:
    from score_news import canonical_domain, match_company_alias, normalize_title, normalize_url, source_type


SEOUL_TZ = timezone(timedelta(hours=9), "Asia/Seoul")
FORBIDDEN_PUBLIC_FIELDS = {"body", "content", "html", "summary", "description", "image", "thumbnail"}


def clean_markup(value):
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_naver_pubdate(value):
    parsed = parsedate_to_datetime((value or "").strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SEOUL_TZ).isoformat()


def source_domain(url):
    try:
        return canonical_domain(urlsplit(url or "").netloc)
    except ValueError:
        return ""


def source_tier(domain, company):
    kind = source_type(domain, company)
    return {"official": "official", "major": "tier1"}.get(kind, "other")


def article_id(provider, canonical_url, normalized_title):
    seed = f"{provider}|{canonical_url}|{normalized_title}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def infer_categories(text):
    normalized = normalize_title(text)
    rules = [
        ("실적", ("실적", "earnings", "profit", "revenue", "매출", "영업이익")),
        ("투자·생산", ("투자", "investment", "capex", "fab", "공장", "생산", "capacity")),
        ("기술·제품", ("hbm", "dram", "nand", "memory", "메모리", "제품", "chip")),
        ("공급·규제", ("공급", "계약", "수출", "규제", "export", "supply", "contract", "regulation")),
        ("인사·M&A", ("인사", "대표", "ceo", "appoint", "acquisition", "인수", "합병")),
        ("주가·투자의견", ("주가", "목표주가", "stock", "shares", "price target", "etf")),
    ]
    matches = [label for label, terms in rules if any(normalize_title(term) in normalized for term in terms)]
    return matches or ["기타"]


def event_signals(text):
    normalized = normalize_title(text)
    groups = {
        "investment": ("투자", "investment", "capex", "시설투자"),
        "production": ("생산", "mass production", "양산", "capacity", "fab", "공장"),
        "supply": ("공급", "supply", "contract", "계약", "납품"),
        "regulation": ("규제", "regulation", "export control", "수출 통제", "법안", "lawsuit"),
        "earnings": ("실적", "earnings", "revenue", "profit", "매출", "영업이익"),
        "personnel": ("인사", "대표이사 선임", "appoint", "appointed", "nomination", "취임"),
        "executive": ("ceo", "회장", "chairman", "chief", "최태원", "chey tae won", "chey tae-won"),
        "shareholder_message": (
            "팔지 말고", "갖고 있어라", "갖고 있으면", "보유", "사서 가만히",
            "hold onto your shares", "hold your shares", "keep your shares",
        ),
        "hbm": ("hbm", "고대역폭메모리"),
        "dram": ("dram", "디램"),
        "nand": ("nand", "낸드"),
        "ai_memory": ("ai memory", "ai 메모리", "memory as a service"),
        "m_and_a": ("인수", "합병", "acquisition", "merger", "m&a"),
    }
    signals = {name for name, terms in groups.items() if any(normalize_title(term) in normalized for term in terms)}
    signals.update(re.findall(r"(?:usd|krw|\$|₩)?\s?\d+(?:\.\d+)?\s?(?:억|조|million|billion|%|gb|tb)", normalized))
    signals.update(re.findall(r"\b(?:20\d{2}|q[1-4]|hbm\d+)\b", normalized))
    return sorted(signals)


def relevance_score(title, description, company):
    title_alias = match_company_alias(title, company)
    description_alias = match_company_alias(description, company)
    score = 80 if title_alias else 35 if description_alias else 0
    combined = normalize_title(f"{title} {description}")
    score += min(20, sum(normalize_title(keyword) in combined for keyword in company.get("important_keywords", [])) * 4)
    return min(100, score), title_alias or description_alias


def normalize_naver_item(item, company, collected_at):
    title = clean_markup(item.get("title"))
    description = clean_markup(item.get("description"))
    chosen_url = item.get("originallink") or item.get("link") or ""
    canonical_url = normalize_url(chosen_url)
    domain = source_domain(canonical_url)
    score, alias = relevance_score(title, description, company)
    normalized = normalize_title(title)
    return {
        "article_id": article_id("naver", canonical_url, normalized),
        "provider": "naver",
        "providers": ["naver"],
        "company_name": company["company_name"],
        "stock_code": company["stock_code"],
        "title": title,
        "normalized_title": normalized,
        "url": canonical_url,
        "canonical_url": canonical_url,
        "source_domain": domain,
        "source_name": domain,
        "published_at": parse_naver_pubdate(item.get("pubDate")),
        "collected_at": collected_at,
        "language": "Korean",
        "region": "domestic",
        "matched_alias": alias,
        "categories": infer_categories(f"{title} {description}"),
        "event_keywords": event_signals(title),
        "official_source": source_type(domain, company) == "official",
        "source_tier": source_tier(domain, company),
        "relevance_score": score,
        "_description": description,
        "_description_event_keywords": event_signals(description),
    }


def normalize_gdelt_item(item, company, collected_at):
    title = clean_markup(item.get("title"))
    canonical_url = normalize_url(item.get("url"))
    domain = canonical_domain(item.get("source_domain") or source_domain(canonical_url))
    normalized = normalize_title(title)
    score, alias = relevance_score(title, "", company)
    language = item.get("language") or "Unknown"
    domestic = language.lower() == "korean" or domain.endswith(".kr") or ".co.kr" in domain
    return {
        "article_id": article_id("gdelt", canonical_url, normalized),
        "provider": "gdelt",
        "providers": ["gdelt"],
        "company_name": company["company_name"],
        "stock_code": company["stock_code"],
        "title": title,
        "normalized_title": normalized,
        "url": canonical_url,
        "canonical_url": canonical_url,
        "source_domain": domain,
        "source_name": domain,
        "published_at": item.get("published_at"),
        "collected_at": collected_at,
        "language": language,
        "region": "domestic" if domestic else "international",
        "matched_alias": alias,
        "categories": infer_categories(title),
        "event_keywords": event_signals(title),
        "official_source": source_type(domain, company) == "official",
        "source_tier": source_tier(domain, company),
        "relevance_score": score,
    }


def assert_public_article(article):
    forbidden = FORBIDDEN_PUBLIC_FIELDS.intersection(article)
    if forbidden:
        raise ValueError(f"Forbidden public article fields: {sorted(forbidden)}")
