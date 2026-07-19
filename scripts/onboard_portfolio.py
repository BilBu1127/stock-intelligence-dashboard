import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")
KIND_SOURCE_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
VALID_CODE = re.compile(r"^[0-9A-Z]{6}$")
TIER_BUDGETS = {
    "core": {"naver": 3, "gdelt": 1},
    "watch": {"naver": 2, "gdelt": 1},
    "background": {"naver": 1, "gdelt": 1},
}
AMBIGUOUS_SEARCH_NAMES = {"GST", "미코", "테스"}
COMMON_EXCLUDED_KEYWORDS = [
    "주가 전망", "목표주가", "종목 추천", "급등주", "stock picks", "stocks to buy", "price target",
]
MAJOR_SOURCE_DOMAINS = [
    "reuters.com", "bloomberg.com", "yna.co.kr", "yonhapnews.co.kr", "mk.co.kr",
    "hankyung.com", "etnews.com", "zdnet.co.kr", "thebell.co.kr",
]

ENGLISH_ALIASES = {
    "005930": ["Samsung Electronics", "Samsung Electronics Co"],
    "000660": ["SK hynix", "SK Hynix Inc"],
    "042700": ["Hanmi Semiconductor"],
    "240810": ["Wonik IPS"],
    "403870": ["HPSP"],
    "005290": ["Dongjin Semichem"],
    "058470": ["Leeno Industrial"],
    "018260": ["Samsung SDS"],
    "035420": ["NAVER", "Naver Corp"],
    "010120": ["LS ELECTRIC", "LS Electric"],
    "298040": ["Hyosung Heavy Industries"],
    "047050": ["POSCO International"],
    "034020": ["Doosan Enerbility"],
    "375500": ["DL E&C"],
    "000720": ["Hyundai Engineering & Construction", "Hyundai E&C"],
    "005490": ["POSCO Holdings"],
    "329180": ["HD Hyundai Heavy Industries"],
    "010140": ["Samsung Heavy Industries"],
    "012330": ["Hyundai Mobis"],
    "005380": ["Hyundai Motor", "Hyundai Motor Company"],
    "278470": ["APR Corp"],
    "079550": ["LIG Nex1", "LIG Defense & Aerospace", "LIG D&A"],
    "064350": ["Hyundai Rotem"],
    "047810": ["Korea Aerospace Industries", "KAI"],
    "012450": ["Hanwha Aerospace"],
}

SPECIAL_ALIASES = {
    "000660": ["SK하이닉스"],
    "010120": ["LS ELECTRIC", "엘에스일렉트릭"],
    "005380": ["현대차", "현대자동차"],
    "005490": ["POSCO홀딩스", "포스코홀딩스"],
    "035420": ["NAVER", "네이버"],
    "079550": ["LIG디펜스앤에어로스페이스", "LIG넥스원"],
}

PREVIOUS_NAMES = {
    "010120": ["LS산전"],
    "079550": ["LIG넥스원"],
}

OFFICIAL_SOURCE_DOMAINS = {
    "005930": ["news.samsung.com", "samsung.com"],
    "000660": ["news.skhynix.com", "skhynix.com"],
    "035420": ["navercorp.com"],
    "010120": ["ls-electric.com"],
    "034020": ["doosanenerbility.com"],
    "005490": ["posco-inc.com"],
    "329180": ["hd-hhi.com"],
    "005380": ["hyundai.com"],
    "079550": ["lignda.com", "lignex1.com"],
    "012450": ["hanwhaaerospace.com"],
}


class KindTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cell = None
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag in {"td", "th"}:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = []


def read_json(path, default=None):
    path = Path(path)
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_text_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def parse_kind_listing(path):
    parser = KindTableParser()
    parser.feed(Path(path).read_bytes().decode("euc-kr", "replace"))
    records = {}
    for row in parser.rows[1:]:
        if len(row) < 10:
            continue
        records[row[2]] = {
            "company_name": row[0],
            "market": row[1],
            "stock_code": row[2],
            "sector": row[3],
            "listed_at": row[5],
        }
    return records


def unique_strings(values):
    result = []
    seen = set()
    for value in values:
        clean = str(value).strip()
        key = clean.casefold()
        if clean and key not in seen:
            result.append(clean)
            seen.add(key)
    return result


def validate_portfolio(inputs, official_records, checked_at):
    names = Counter(item["company_name"] for item in inputs)
    codes = Counter(item["stock_code"] for item in inputs)
    validations = []
    for item in inputs:
        code = str(item["stock_code"])
        official = official_records.get(code)
        if official is None:
            status = "not_found"
            reason = "입력 종목코드를 KIND 상장법인 목록에서 찾지 못함"
        elif official["company_name"] == item["company_name"]:
            status = "verified"
            reason = "입력 종목명과 종목코드가 KIND 목록과 일치"
        else:
            status = "corrected"
            reason = "종목코드는 일치하지만 입력 종목명과 KIND 공식 종목명이 다름"
        validations.append({
            "input_company_name": item["company_name"],
            "input_stock_code": code,
            "official_company_name": official["company_name"] if official else None,
            "official_stock_code": official["stock_code"] if official else None,
            "market": official["market"] if official else None,
            "listed_at": official["listed_at"] if official else None,
            "validation_status": status,
            "reason": reason,
            "source_type": "KRX KIND 상장법인 목록",
            "source_url": KIND_SOURCE_URL,
            "checked_at": checked_at,
        })
    tiers = Counter(item["monitoring_tier"] for item in inputs)
    categories = Counter(item["category"] for item in inputs)
    invalid_codes = [item["stock_code"] for item in inputs if not VALID_CODE.fullmatch(str(item["stock_code"]))]
    return validations, {
        "total": len(inputs),
        "tier_counts": dict(tiers),
        "category_counts": dict(categories),
        "duplicate_company_names": sorted(name for name, count in names.items() if count > 1),
        "duplicate_stock_codes": sorted(code for code, count in codes.items() if count > 1),
        "invalid_stock_codes": invalid_codes,
        "leading_zero_codes": sum(str(item["stock_code"]).startswith("0") for item in inputs),
        "alphanumeric_codes": [item["stock_code"] for item in inputs if not str(item["stock_code"]).isdigit()],
        "validation_counts": dict(Counter(item["validation_status"] for item in validations)),
    }


def build_company(input_item, validation, category_keywords):
    code = str(input_item["stock_code"])
    valid = validation["validation_status"] in {"verified", "corrected"}
    official_name = validation.get("official_company_name") or input_item["company_name"]
    aliases = unique_strings([
        official_name,
        input_item["company_name"],
        *SPECIAL_ALIASES.get(code, []),
    ])
    tier = input_item["monitoring_tier"]
    category = input_item["category"]
    return {
        "company_name": official_name,
        "input_company_name": input_item["company_name"],
        "stock_code": code,
        "category": category,
        "sector": validation.get("market") or category,
        "monitoring_tier": tier,
        "aliases": aliases,
        "english_aliases": ENGLISH_ALIASES.get(code, []),
        "status": "active" if valid else "inactive",
        "news_enabled": valid,
        "disclosure_enabled": valid,
        "earnings_enabled": valid,
        "naver_query_budget": TIER_BUDGETS[tier]["naver"],
        "gdelt_query_budget": TIER_BUDGETS[tier]["gdelt"],
        "important_keywords": category_keywords.get(category, []),
        "excluded_keywords": COMMON_EXCLUDED_KEYWORDS,
        "previous_names": PREVIOUS_NAMES.get(code, []),
        "official_sources": OFFICIAL_SOURCE_DOMAINS.get(code, []),
        "major_source_domains": MAJOR_SOURCE_DOMAINS,
        "validation_status": validation["validation_status"],
        "ambiguous_search": official_name in AMBIGUOUS_SEARCH_NAMES or input_item["company_name"] in AMBIGUOUS_SEARCH_NAMES,
        "official_validation": {
            "source_type": validation["source_type"],
            "source_url": validation["source_url"],
            "checked_at": validation["checked_at"],
        },
    }


def add_cross_company_exclusions(companies):
    for company in companies:
        own_terms = unique_strings([
            company["company_name"], *company.get("aliases", []), *company.get("english_aliases", []),
        ])
        exclusions = []
        for other in companies:
            if other["stock_code"] == company["stock_code"]:
                continue
            other_terms = unique_strings([
                other["company_name"], *other.get("aliases", []), *other.get("english_aliases", []),
            ])
            for own_term in own_terms:
                for other_term in other_terms:
                    if own_term.casefold() != other_term.casefold() and own_term.casefold() in other_term.casefold():
                        exclusions.append(other_term)
        company["cross_company_excluded_terms"] = unique_strings(exclusions)
    return companies


def ensure_detail_files(companies, generated_at):
    created = []
    for company in companies:
        code = company["stock_code"]
        templates = {
            ROOT / "data" / "news" / "by-company" / f"{code}.json": {
                "generated_at": None, "company_name": company["company_name"], "stock_code": code,
                "status": "not_collected", "last_successful_update": None, "errors": [], "news": [],
            },
            ROOT / "data" / "earnings" / "by-company" / f"{code}.json": {
                "generatedAt": generated_at, "currencyUnit": "억원",
                "company": {"name": company["company_name"], "code": code, "market": company.get("sector"), "earnings": [], "news": []},
            },
            ROOT / "data" / "disclosures" / "by-company" / f"{code}.json": {
                "generatedAt": generated_at, "companyName": company["company_name"], "stockCode": code,
                "status": "not_collected", "disclosures": [],
            },
        }
        for path, payload in templates.items():
            if not path.is_file():
                write_json_atomic(path, payload)
                created.append(str(path.relative_to(ROOT)))
            elif "earnings" in path.parts:
                current = read_json(path, {}) or {}
                if "company" not in current and "earnings" in current:
                    write_json_atomic(path, payload)
    return created


def build_public_indexes(companies, generated_at, data_root=None):
    data_root = Path(data_root or ROOT / "data")
    watchlist = []
    earnings_companies = []
    disclosure_companies = []
    disclosures = []
    news_companies = []
    news = []
    for company in companies:
        code = company["stock_code"]
        common = {
            "category": company["category"],
            "monitoringTier": company["monitoring_tier"],
            "validationStatus": company["validation_status"],
        }
        watchlist.append({"name": company["company_name"], "code": code, "market": company.get("sector"), **common})
        earnings_payload = read_json(data_root / "earnings" / "by-company" / f"{code}.json", {}) or {}
        detail_company = earnings_payload.get("company", earnings_payload)
        earnings_companies.append({
            "name": company["company_name"], "code": code, "market": company.get("sector"),
            "hasDetails": bool(detail_company.get("earnings")), "earnings": detail_company.get("earnings", []), **common,
        })
        disclosure_payload = read_json(data_root / "disclosures" / "by-company" / f"{code}.json", {}) or {}
        company_disclosures = disclosure_payload.get("disclosures", [])
        disclosures.extend(company_disclosures)
        disclosure_companies.append({
            "companyName": company["company_name"], "stockCode": code,
            "disclosureCount": len(company_disclosures),
            "latestDisclosureAt": company_disclosures[0].get("disclosedAt") if company_disclosures else None,
            "category": company["category"], "monitoringTier": company["monitoring_tier"],
        })
        news_payload = read_json(data_root / "news" / "by-company" / f"{code}.json", {}) or {}
        company_news = news_payload.get("news", [])
        news.extend(company_news[:3])
        news_companies.append({
            "company_name": company["company_name"], "stock_code": code,
            "category": company["category"], "monitoring_tier": company["monitoring_tier"],
            "event_count": len(company_news),
            "latest_event_at": company_news[0].get("last_published_at") if company_news else None,
            "last_successful_update": news_payload.get("last_successful_update"),
            "status": news_payload.get("status", "not_collected"),
        })
    disclosures.sort(key=lambda item: item.get("disclosedAt") or "", reverse=True)
    news.sort(key=lambda item: item.get("last_published_at") or item.get("published_at") or "", reverse=True)
    write_json_atomic(data_root / "earnings" / "index.json", {
        "generatedAt": generated_at, "currencyUnit": "억원", "watchlist": watchlist, "companies": earnings_companies,
    })
    write_json_atomic(data_root / "disclosures" / "index.json", {
        "generatedAt": generated_at,
        "categories": ["실적", "시설투자", "공급계약", "자사주·배당", "증자·사채", "지분", "기타"],
        "companies": disclosure_companies, "disclosures": disclosures,
    })
    write_json_atomic(data_root / "news" / "index.json", {
        "generated_at": generated_at, "companies": news_companies, "news": news,
    })
    compact_roster = [
        {
            "name": company["company_name"], "code": company["stock_code"], "market": company.get("sector"),
            "category": company["category"], "monitoringTier": company["monitoring_tier"],
            "validationStatus": company["validation_status"],
        }
        for company in companies
    ]
    write_text_atomic(
        data_root / "portfolio.js",
        "window.PORTFOLIO_INDEX = " + json.dumps(compact_roster, ensure_ascii=False, separators=(",", ":")) + ";\n",
    )


def main():
    parser = argparse.ArgumentParser(description="Validate and register the local portfolio using a KIND listing export.")
    parser.add_argument("--kind-file", required=True, help="Path to the KIND listing export downloaded locally.")
    parser.add_argument("--apply", action="store_true", help="Apply verified portfolio data after writing the validation report.")
    args = parser.parse_args()

    source = read_json(ROOT / "data" / "portfolio-input.json", {}) or {}
    inputs = source.get("companies", [])
    official_records = parse_kind_listing(args.kind_file)
    checked_at = datetime.now(SEOUL).isoformat()
    validations, summary = validate_portfolio(inputs, official_records, checked_at)
    report = {
        "version": "1.0.0", "checked_at": checked_at, "source_url": KIND_SOURCE_URL,
        "expected_total": source.get("expected_total"), "expected_tiers": source.get("expected_tiers"),
        "summary": summary, "companies": validations,
    }
    write_json_atomic(ROOT / "data" / "portfolio-validation.json", report)

    blocking = bool(
        len(inputs) != source.get("expected_total")
        or summary["tier_counts"] != source.get("expected_tiers")
        or summary["duplicate_company_names"]
        or summary["duplicate_stock_codes"]
        or summary["invalid_stock_codes"]
    )
    if args.apply and not blocking:
        keywords = read_json(ROOT / "data" / "config" / "category-keywords.json", {}).get("categories", {})
        companies = add_cross_company_exclusions([
            build_company(item, validation, keywords) for item, validation in zip(inputs, validations)
        ])
        write_json_atomic(ROOT / "data" / "companies.json", {"version": "3.0.0", "companies": companies})
        created = ensure_detail_files(companies, checked_at)
        build_public_indexes(companies, checked_at)
        print(f"Portfolio applied: {len(companies)} companies; detail files created: {len(created)}")
    else:
        print(f"Portfolio validated: {len(inputs)} companies; blocking issues: {blocking}")
    print("Validation counts: " + json.dumps(summary["validation_counts"], ensure_ascii=False, sort_keys=True))
    if blocking:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
