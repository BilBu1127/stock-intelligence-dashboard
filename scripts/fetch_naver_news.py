import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from .normalize_news import normalize_naver_item
except ImportError:
    from normalize_news import normalize_naver_item


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NAVER_ENV_PATH = PROJECT_ROOT / ".secrets" / "naver.env"
NAVER_ENDPOINT = "https://naverapihub.apigw.ntruss.com/search/v1/news"
NAVER_QUERIES = [
    "SK하이닉스",
    '"SK하이닉스" HBM',
    '"SK하이닉스" 반도체',
    '"SK하이닉스" 투자',
    '"SK하이닉스" 수출',
    '"SK하이닉스" 실적',
]


def build_company_queries(company, query_budget=None):
    budget = max(1, int(query_budget or company.get("naver_query_budget", 3)))
    name = company["company_name"]
    if company.get("ambiguous_search"):
        category = str(company.get("category") or company.get("sector") or "").strip()
        code = str(company.get("stock_code") or "").strip()
        queries = []
        if category:
            queries.append(f'"{name}" {category}')
        if code:
            queries.append(f'"{name}" {code}')
    else:
        queries = [name]
    for keyword in company.get("important_keywords", []):
        clean = str(keyword).strip()
        if not clean or clean.casefold() in {"earnings", "profit", "revenue"}:
            continue
        candidate = f'"{name}" {clean}'
        if candidate not in queries:
            queries.append(candidate)
        if len(queries) >= budget:
            break
    return queries[:budget]


class NaverRequestError(Exception):
    def __init__(self, error_type, attempts=1):
        super().__init__(error_type)
        self.error_type = error_type
        self.attempts = attempts


def load_naver_credentials(path=NAVER_ENV_PATH):
    if not Path(path).is_file():
        return None
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#") or "=" not in clean:
            continue
        key, value = clean.split("=", 1)
        values[key.strip()] = value.strip()
    client_id = values.get("NAVER_CLIENT_ID", "")
    client_secret = values.get("NAVER_CLIENT_SECRET", "")
    return (client_id, client_secret) if client_id and client_secret else None


def request_naver_json(url, client_id, client_secret, timeout=20, retries=3):
    last_type = "UnknownError"
    for attempt in range(1, retries + 1):
        request = Request(url, headers={
            "Accept": "application/json",
            "X-NCP-APIGW-API-KEY-ID": client_id,
            "X-NCP-APIGW-API-KEY": client_secret,
            "User-Agent": "stock-intelligence-dashboard-local-prototype/2.0",
        })
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("items", []), list):
                raise ValueError("Unexpected Naver response structure")
            return payload, attempt
        except HTTPError as error:
            last_type = f"HTTP{error.code}"
            if error.code not in {429, 500, 502, 503, 504}:
                break
        except (URLError, TimeoutError) as error:
            last_type = type(error).__name__
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            last_type = type(error).__name__
            break
        if attempt < retries:
            time.sleep(2 ** (attempt - 1))
    raise NaverRequestError(last_type, attempt)


def build_naver_url(query, sort):
    return f"{NAVER_ENDPOINT}?{urlencode({'query': query, 'display': 100, 'start': 1, 'sort': sort, 'format': 'json'})}"


def collect_naver_articles(company, start_at, end_at, credentials_path=NAVER_ENV_PATH, request_fn=request_naver_json,
                           query_budget=None, sorts=("date",)):
    credentials = load_naver_credentials(credentials_path)
    if credentials is None:
        return [], {"request_count": 0, "raw_count": 0, "credentials_status": "naver_credentials_missing", "errors": []}
    client_id, client_secret = credentials
    collected_at = datetime.now(timezone(timedelta(hours=9))).isoformat()
    articles = []
    request_count = 0
    errors = []
    queries = build_company_queries(company, query_budget=query_budget)
    for query_index, query in enumerate(queries):
        for sort in sorts:
            try:
                payload, attempts = request_fn(build_naver_url(query, sort), client_id, client_secret)
                request_count += attempts
                for item in payload.get("items", []):
                    try:
                        article = normalize_naver_item(item, company, collected_at)
                        published = datetime.fromisoformat(article["published_at"])
                        if start_at <= published.astimezone(timezone.utc) <= end_at:
                            articles.append(article)
                    except (TypeError, ValueError, OverflowError):
                        continue
            except NaverRequestError as error:
                request_count += error.attempts
                errors.append({"provider": "naver", "type": error.error_type, "query_index": query_index, "sort": sort})
    return articles, {
        "request_count": request_count,
        "raw_count": len(articles),
        "credentials_status": "available",
        "errors": errors,
    }
