import hashlib
import json
import os
import time
import tracemalloc
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .cluster_news_events import build_public_event, cluster_event_articles, deduplicate_standard_articles
    from .score_news import normalize_title, parse_datetime
except ImportError:
    from cluster_news_events import build_public_event, cluster_event_articles, deduplicate_standard_articles
    from score_news import normalize_title, parse_datetime


ROOT = Path(__file__).resolve().parents[1]
SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")
TIER_PRIORITY = {"core": 0, "watch": 1, "background": 2}


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


def company_defaults(company):
    merged = {
        "status": "active",
        "monitoring_tier": "watch",
        "news_enabled": True,
        "disclosure_enabled": True,
        "earnings_enabled": True,
        "naver_query_budget": 3,
        "gdelt_query_budget": 1,
    }
    merged.update(company)
    return merged


def load_pipeline_config(path=ROOT / "data" / "config" / "pipeline.json"):
    return read_json(path, {}) or {}


def provider_cursor_template():
    return {
        "last_successful_run": None,
        "last_article_published_at": None,
        "last_collected_at": None,
        "continuation": None,
        "last_error": None,
        "consecutive_failures": 0,
    }


def collection_window(cursor, now, config, backfill=False):
    collection = config["collection"]
    if backfill or not cursor.get("last_successful_run"):
        return now - timedelta(days=collection["initial_backfill_days"]), now
    last_success = parse_datetime(cursor.get("last_successful_run"))
    default_start = now - timedelta(hours=collection["incremental_window_hours"])
    overlap_start = last_success - timedelta(hours=collection["overlap_hours"]) if last_success else default_start
    return max(default_start, overlap_start), now


def event_timestamp(event):
    return parse_datetime(event.get("last_published_at") or event.get("published_at"))


def retain_public_events(events, now, retention):
    material, contextual, low = [], [], []
    seen = set()
    for event in sorted(events, key=lambda item: event_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        event_id = event.get("cluster_id")
        if event_id in seen:
            continue
        seen.add(event_id)
        published = event_timestamp(event)
        age_days = (now - published).days if published else 10_000
        level = event.get("importance_level", "low")
        if level in {"critical", "important", "watch"} and age_days <= retention["critical_important_watch"]["days"]:
            material.append(event)
        elif level == "contextual" and age_days <= retention["contextual"]["days"]:
            contextual.append(event)
        elif level in {"low", "market_noise"} and age_days <= retention["low_market_noise"]["days"]:
            low.append(event)
    return (
        material[: retention["critical_important_watch"]["max_events"]]
        + contextual[: retention["contextual"]["max_events"]]
        + low[: retention["low_market_noise"]["max_review_samples"]]
    )


def public_event_summary(event):
    keys = (
        "cluster_id", "company_name", "stock_code", "representative_title", "representative_url",
        "representative_source", "representative_language", "first_published_at", "last_published_at",
        "article_count", "domestic_article_count", "international_article_count", "providers",
        "source_domains", "categories", "event_keywords", "importance_score", "importance_level",
        "scoring_reasons", "needs_review",
    )
    return {key: event.get(key) for key in keys}


def build_news_index(data_root, companies, generated_at, per_company_limit=3):
    summaries = []
    company_rows = []
    for company in companies:
        code = company["stock_code"]
        payload = read_json(Path(data_root) / "news" / "by-company" / f"{code}.json", {"news": []}) or {"news": []}
        events = sorted(payload.get("news", []), key=lambda item: event_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        summaries.extend(public_event_summary(item) for item in events[:per_company_limit])
        company_rows.append({
            "company_name": company["company_name"],
            "stock_code": code,
            "monitoring_tier": company.get("monitoring_tier", "watch"),
            "event_count": len(events),
            "latest_event_at": events[0].get("last_published_at") if events else None,
            "last_successful_update": payload.get("last_successful_update"),
            "status": payload.get("status", "not_collected"),
        })
    summaries.sort(key=lambda item: event_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return {"generated_at": generated_at, "companies": company_rows, "news": summaries}


def directory_json_size(path):
    path = Path(path)
    return sum(item.stat().st_size for item in path.rglob("*.json") if item.is_file()) if path.exists() else 0


class MockNewsProvider:
    def __init__(self, name, requests_per_company, fail_codes=None):
        self.name = name
        self.requests_per_company = requests_per_company
        self.fail_codes = set(fail_codes or [])

    def fetch(self, company, start_at, end_at, request_budget, continuation=None):
        code = company["stock_code"]
        if code in self.fail_codes:
            raise RuntimeError(f"Mock{self.name.title()}Failure")
        request_count = min(request_budget, self.requests_per_company)
        articles = []
        for index in range(request_count):
            published = end_at - timedelta(minutes=index + 1)
            event_key = f"event_{index}"
            canonical = f"https://mock.example/{code}/{event_key}"
            title = f"{company['company_name']} mock material event {index}"
            articles.append({
                "article_id": f"{self.name}-{code}-{index}",
                "provider": self.name,
                "providers": [self.name],
                "company_name": company["company_name"],
                "stock_code": code,
                "title": title,
                "normalized_title": normalize_title(title),
                "url": canonical,
                "canonical_url": canonical,
                "source_domain": f"{self.name}.mock.example",
                "source_name": f"{self.name}.mock.example",
                "published_at": published.isoformat().replace("+00:00", "Z"),
                "collected_at": end_at.isoformat().replace("+00:00", "Z"),
                "language": "Korean" if self.name == "naver" else "English",
                "region": "domestic" if self.name == "naver" else "international",
                "matched_alias": company["company_name"],
                "categories": ["투자·생산"],
                "event_keywords": [event_key, f"material_{index}"],
                "official_source": False,
                "source_tier": "other",
                "relevance_score": 90,
            })
        return articles, {
            "request_count": request_count,
            "raw_count": len(articles),
            "continuation": None,
            "oldest_result_at": articles[-1]["published_at"] if articles else None,
        }


class BatchNewsPipeline:
    def __init__(self, data_root, config, providers, cursor_path=None, report_path=None):
        self.data_root = Path(data_root)
        self.config = config
        self.providers = providers
        self.cursor_path = Path(cursor_path or self.data_root / "state" / "news-cursors.json")
        self.report_path = Path(report_path or self.data_root / "news-run-report.json")

    def _provider_budget(self, company, provider_name):
        return int(company.get(f"{provider_name}_query_budget", self.config["budgets"][provider_name]["default_company_requests"]))

    def _state_for(self, state, code, provider_name):
        company_state = state.setdefault("companies", {}).setdefault(code, {"providers": {}})
        return company_state["providers"].setdefault(provider_name, provider_cursor_template())

    def _priority(self, company, state):
        company_state = state.get("companies", {}).get(company["stock_code"], {})
        failures = sum(item.get("consecutive_failures", 0) for item in company_state.get("providers", {}).values())
        return (0 if failures else 1, TIER_PRIORITY.get(company.get("monitoring_tier", "watch"), 1), company["stock_code"])

    def run(self, companies, now=None, backfill=False):
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        started = time.perf_counter()
        tracemalloc.start()
        state = read_json(self.cursor_path, {"version": "1.0.0", "updated_at": None, "companies": {}}) or {"companies": {}}
        state.setdefault("api_usage", {})
        usage_day = now.astimezone(SEOUL).date().isoformat()
        if state["api_usage"].get("date") != usage_day:
            state["api_usage"] = {"date": usage_day, "naver": 0, "gdelt": 0}

        configured = [company_defaults(item) for item in companies]
        active = [item for item in configured if item["status"] == "active" and item["news_enabled"]]
        active.sort(key=lambda item: self._priority(item, state))
        batch_size = int(self.config["batch"]["batch_size"])
        provider_calls = Counter()
        provider_errors = {name: Counter() for name in self.providers}
        per_company_calls = {}
        company_durations = {}
        batch_durations = []
        successful, failed, skipped = [], [], []
        raw_count = new_count = duplicate_count = new_cluster_count = 0
        data_changed = False
        cursor_updates = []

        for batch_number, offset in enumerate(range(0, len(active), batch_size), start=1):
            batch_started = time.perf_counter()
            batch = active[offset: offset + batch_size]
            for company in batch:
                company_started = time.perf_counter()
                code = company["stock_code"]
                per_company_calls[code] = {name: 0 for name in self.providers}
                collected = []
                provider_successes = 0
                company_errors = []
                for provider_name, provider in self.providers.items():
                    budget = self._provider_budget(company, provider_name)
                    run_limit = int(self.config["budgets"][provider_name]["per_run_hard_limit"])
                    daily_limit = int(self.config["budgets"][provider_name].get("daily_hard_limit", 10**9))
                    if provider_calls[provider_name] + budget > run_limit or state["api_usage"].get(provider_name, 0) + budget > daily_limit:
                        company_errors.append({"provider": provider_name, "type": "BudgetSkipped"})
                        continue
                    cursor = self._state_for(state, code, provider_name)
                    start_at, end_at = collection_window(cursor, now, self.config, backfill=backfill)
                    try:
                        articles, meta = provider.fetch(company, start_at, end_at, budget, cursor.get("continuation"))
                        calls = int(meta.get("request_count", 0))
                        provider_calls[provider_name] += calls
                        state["api_usage"][provider_name] = state["api_usage"].get(provider_name, 0) + calls
                        per_company_calls[code][provider_name] += calls
                        raw_count += int(meta.get("raw_count", len(articles)))
                        collected.extend(articles)
                        provider_successes += 1
                        latest = max((parse_datetime(item.get("published_at")) for item in articles), default=None)
                        cursor.update({
                            "last_successful_run": now.isoformat().replace("+00:00", "Z"),
                            "last_article_published_at": latest.isoformat().replace("+00:00", "Z") if latest else cursor.get("last_article_published_at"),
                            "last_collected_at": now.isoformat().replace("+00:00", "Z"),
                            "continuation": meta.get("continuation"),
                            "last_error": None,
                            "consecutive_failures": 0,
                        })
                        cursor_updates.append({"stock_code": code, "provider": provider_name, "updated": True})
                    except Exception as error:
                        error_type = getattr(error, "error_type", type(error).__name__)
                        attempted_calls = int(getattr(error, "attempts", 0))
                        provider_calls[provider_name] += attempted_calls
                        state["api_usage"][provider_name] = state["api_usage"].get(provider_name, 0) + attempted_calls
                        per_company_calls[code][provider_name] += attempted_calls
                        cursor["last_error"] = error_type
                        cursor["consecutive_failures"] = cursor.get("consecutive_failures", 0) + 1
                        provider_errors[provider_name][error_type] += 1
                        company_errors.append({"provider": provider_name, "type": error_type})
                        cursor_updates.append({"stock_code": code, "provider": provider_name, "updated": False})

                output_path = self.data_root / "news" / "by-company" / f"{code}.json"
                existing_payload = read_json(output_path, {"generated_at": None, "news": []}) or {"news": []}
                if provider_successes:
                    deduplicated, dedupe_meta = deduplicate_standard_articles(collected)
                    duplicate_count += dedupe_meta["removed_count"]
                    clusters = cluster_event_articles(deduplicated)
                    new_events = [build_public_event(cluster, company, now=now) for cluster in clusters]
                    new_count += len(deduplicated)
                    new_cluster_count += len(new_events)
                    merged = new_events + existing_payload.get("news", [])
                    retained = retain_public_events(merged, now, self.config["retention"])
                    fingerprint_cutoff = now - timedelta(days=self.config["collection"]["fingerprint_retention_days"])
                    company_state = state.setdefault("companies", {}).setdefault(code, {"providers": {}})
                    fingerprints = []
                    article_hashes = []
                    for event in retained:
                        published = event_timestamp(event)
                        if not published or published < fingerprint_cutoff:
                            continue
                        fingerprints.append({
                            "cluster_id": event.get("cluster_id"),
                            "last_seen_at": published.isoformat().replace("+00:00", "Z"),
                        })
                        for article in event.get("articles", []):
                            url = article.get("url") or ""
                            if not url:
                                continue
                            article_hashes.append({
                                "hash": hashlib.sha256(url.encode("utf-8")).hexdigest()[:24],
                                "published_at": article.get("published_at"),
                            })
                    company_state["event_fingerprints"] = fingerprints
                    company_state["article_hashes"] = article_hashes
                    payload = {
                        "generated_at": now.isoformat().replace("+00:00", "Z"),
                        "company_name": company["company_name"],
                        "stock_code": code,
                        "status": "partial" if company_errors else "ok",
                        "last_successful_update": now.isoformat().replace("+00:00", "Z"),
                        "errors": company_errors,
                        "news": retained,
                    }
                    if payload != existing_payload:
                        write_json_atomic(output_path, payload)
                        data_changed = True
                    successful.append(code)
                else:
                    if company_errors:
                        failed.append(code)
                    else:
                        skipped.append(code)
                company_durations[code] = round(time.perf_counter() - company_started, 6)

            state["updated_at"] = now.isoformat().replace("+00:00", "Z")
            write_json_atomic(self.cursor_path, state)
            index = build_news_index(
                self.data_root,
                active,
                state["updated_at"],
                self.config["dashboard"]["index_event_limit_per_company"],
            )
            write_json_atomic(self.data_root / "news" / "index.json", index)
            batch_durations.append({
                "batch": batch_number,
                "company_count": len(batch),
                "duration_seconds": round(time.perf_counter() - batch_started, 6),
                "checkpoint_written": True,
            })

        _, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        by_company_sizes = {}
        for company in active:
            path = self.data_root / "news" / "by-company" / f"{company['stock_code']}.json"
            by_company_sizes[company["stock_code"]] = path.stat().st_size if path.is_file() else 0
        tier_counts = Counter(item["monitoring_tier"] for item in active)
        report = {
            "executed_at": now.isoformat().replace("+00:00", "Z"),
            "mode": "backfill" if backfill else "incremental",
            "total_companies": len(configured),
            "active_companies": len(active),
            "processed_companies": len(successful) + len(failed),
            "successful_companies": successful,
            "failed_companies": failed,
            "skipped_companies": skipped,
            "monitoring_tier_counts": dict(tier_counts),
            "provider_api_calls": dict(provider_calls),
            "company_api_calls": per_company_calls,
            "provider_error_counts": {name: dict(counts) for name, counts in provider_errors.items()},
            "provider_transient_error_counts": {
                name: {
                    "http_429": sum(count for error, count in counts.items() if "429" in error),
                    "timeout": sum(count for error, count in counts.items() if "timeout" in error.casefold()),
                    "http_5xx": sum(count for error, count in counts.items() if any(f"HTTP{code}" in error for code in range(500, 600))),
                }
                for name, counts in provider_errors.items()
            },
            "raw_article_count": raw_count,
            "new_article_count": new_count,
            "duplicate_article_count": duplicate_count,
            "new_event_cluster_count": new_cluster_count,
            "company_duration_seconds": company_durations,
            "batch_duration_seconds": batch_durations,
            "total_duration_seconds": round(time.perf_counter() - started, 6),
            "public_json_total_bytes": directory_json_size(self.data_root / "news"),
            "company_json_bytes": by_company_sizes,
            "peak_memory_bytes": peak_memory,
            "cursor_updates": cursor_updates,
            "data_changed": data_changed,
            "severe_failure": bool(active) and not successful,
            "commit_eligible": bool(successful),
            "pipeline_version": "3.0.0",
        }
        write_json_atomic(self.report_path, report)
        return report
