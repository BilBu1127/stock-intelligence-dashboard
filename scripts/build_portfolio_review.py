import html
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .news_batch_pipeline import directory_json_size, read_json, write_json_atomic
except ImportError:
    from news_batch_pipeline import directory_json_size, read_json, write_json_atomic


ROOT = Path(__file__).resolve().parents[1]
SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")


def esc(value):
    return html.escape(str(value if value is not None else "N/A"), quote=True)


def company_public_result(company, news_run, audit, telegram):
    code = company["stock_code"]
    news_payload = read_json(ROOT / "data" / "news" / "by-company" / f"{code}.json", {}) or {}
    disclosure_payload = read_json(ROOT / "data" / "disclosures" / "by-company" / f"{code}.json", {}) or {}
    events = news_payload.get("news", [])
    levels = Counter(item.get("importance_level", "low") for item in events)
    quality = news_run.get("company_quality", {}).get(code, {})
    cursor = read_json(ROOT / "data" / "state" / "news-cursors.json", {}).get("companies", {}).get(code, {})
    provider_failures = {
        provider: state.get("consecutive_failures", 0)
        for provider, state in cursor.get("providers", {}).items()
        if state.get("consecutive_failures", 0)
    }
    telegram_result = telegram.get("company_results", {}).get(code, {})
    return {
        "company_name": company["company_name"],
        "input_company_name": company.get("input_company_name"),
        "stock_code": code,
        "category": company.get("category"),
        "monitoring_tier": company.get("monitoring_tier"),
        "validation_status": company.get("validation_status"),
        "news_events": len(events),
        "disclosures": len(disclosure_payload.get("disclosures", [])),
        "provider_calls": news_run.get("company_api_calls", {}).get(code, {}),
        "raw_articles": quality.get("raw_articles", 0),
        "relevant_articles": quality.get("relevant_articles", 0),
        "duplicate_articles": quality.get("duplicate_articles", 0),
        "importance_counts": {level: levels.get(level, 0) for level in ("critical", "important", "watch", "low")},
        "quality_exclusions": audit.get("company_exclusion_reasons", {}).get(code, {}),
        "needs_review_clusters": sum(bool(item.get("needs_review")) for item in events),
        "telegram_matches": telegram_result.get("matched_messages", 0),
        "duration_seconds": news_run.get("company_duration_seconds", {}).get(code, 0),
        "json_bytes": news_run.get("company_json_bytes", {}).get(code, 0),
        "provider_consecutive_failures": provider_failures,
        "top_news": [
            {
                "title": item.get("representative_title"), "url": item.get("representative_url"),
                "source": item.get("representative_source"), "score": item.get("importance_score"),
                "level": item.get("importance_level"), "published_at": item.get("last_published_at"),
            }
            for item in sorted(events, key=lambda value: (value.get("importance_score", 0), value.get("last_published_at") or ""), reverse=True)
        ],
        "recent_disclosures": disclosure_payload.get("disclosures", [])[:5],
    }


def build_report():
    companies = read_json(ROOT / "data" / "companies.json", {"companies": []}).get("companies", [])
    validation = read_json(ROOT / "data" / "portfolio-validation.json", {}) or {}
    news_run = read_json(ROOT / "data" / "news-run-report.json", {}) or {}
    audit = read_json(ROOT / "data" / "portfolio-quality-audit.json", {}) or {}
    telegram = read_json(ROOT / "data" / "telegram-portfolio-report.json", {}) or {}
    rows = [company_public_result(company, news_run, audit, telegram) for company in companies]
    levels = Counter()
    for row in rows:
        levels.update(row["importance_counts"])
    report = {
        "generated_at": datetime.now(SEOUL).isoformat(),
        "registration": {
            "input_companies": validation.get("summary", {}).get("total", len(companies)),
            "registered_companies": len(companies),
            "validation_counts": validation.get("summary", {}).get("validation_counts", {}),
            "tier_counts": dict(Counter(item.get("monitoring_tier") for item in companies)),
            "category_counts": dict(Counter(item.get("category") for item in companies)),
        },
        "news": {
            "provider_calls": news_run.get("provider_api_calls", {}),
            "provider_errors": news_run.get("provider_error_counts", {}),
            "raw_articles": news_run.get("raw_article_count", 0),
            "relevant_articles": news_run.get("new_article_count", 0),
            "duplicates_removed": news_run.get("duplicate_article_count", 0),
            "clusters_before_quality_audit": news_run.get("new_event_cluster_count", 0),
            "quality_exclusions": audit.get("excluded_event_count", 0),
            "quality_exclusion_reasons": audit.get("exclusion_reasons", {}),
            "remaining_cross_company_duplicates": len(audit.get("remaining_cross_company_duplicate_assignments", [])),
            "importance_counts": {level: levels.get(level, 0) for level in ("critical", "important", "watch", "low")},
            "zero_news_companies": [row["stock_code"] for row in rows if row["news_events"] == 0],
            "total_duration_seconds": news_run.get("total_duration_seconds", 0),
            "public_json_total_bytes": directory_json_size(ROOT / "data"),
        },
        "telegram": {
            "status": "completed" if telegram else "not_run",
            "messages_fetched": telegram.get("messages_fetched", 0),
            "unique_matched_messages": telegram.get("unique_matched_messages", 0),
            "companies_with_matches": telegram.get("companies_with_matches", 0),
            "errors": telegram.get("errors", []),
            "cursor_updated": telegram.get("cursor_updated", False),
        },
        "disclosures": {
            "zero_disclosure_companies": [row["stock_code"] for row in rows if row["disclosures"] == 0],
            "total_disclosures": sum(row["disclosures"] for row in rows),
        },
        "companies": rows,
    }
    return report


def top_news_for_review(row):
    tier = row["monitoring_tier"]
    if tier == "core":
        return row["top_news"][:3]
    if tier == "watch":
        return row["top_news"][:1]
    return [item for item in row["top_news"] if item["level"] in {"critical", "important"}]


def render_html(report):
    company_rows = []
    news_sections = []
    disclosure_sections = []
    for row in report["companies"]:
        calls = row["provider_calls"]
        company_rows.append(
            f"<tr><td>{esc(row['company_name'])}</td><td>{esc(row['stock_code'])}</td>"
            f"<td>{esc(row['category'])}</td><td>{esc(row['monitoring_tier'])}</td>"
            f"<td>{esc(row['validation_status'])}</td><td>{row['news_events']}</td><td>{row['disclosures']}</td>"
            f"<td>{calls.get('naver', 0)} / {calls.get('gdelt', 0)}</td><td>{row['duration_seconds']:.1f}s</td></tr>"
        )
        selected_news = top_news_for_review(row)
        if selected_news or row["needs_review_clusters"]:
            items = "".join(
                f"<li><span class='score {esc(item['level'])}'>{esc(item['level'])} {esc(item['score'])}</span> "
                f"<a href='{esc(item['url'])}' target='_blank' rel='noopener'>{esc(item['title'])}</a> "
                f"<small>{esc(item['source'])}</small></li>" for item in selected_news
            ) or "<li>표시할 중요 뉴스 없음</li>"
            news_sections.append(
                f"<details><summary>{esc(row['company_name'])} · {esc(row['monitoring_tier'])} · {row['news_events']}건</summary><ul>{items}</ul></details>"
            )
        if row["recent_disclosures"]:
            items = "".join(
                f"<li><a href='{esc(item.get('dartUrl'))}' target='_blank' rel='noopener'>{esc(item.get('reportName'))}</a> "
                f"<small>{esc(item.get('disclosedAt'))}</small></li>" for item in row["recent_disclosures"]
            )
            disclosure_sections.append(f"<details><summary>{esc(row['company_name'])}</summary><ul>{items}</ul></details>")

    corrected = [item for item in report["companies"] if item["validation_status"] == "corrected"]
    corrected_rows = "".join(
        f"<tr><td>{esc(item['input_company_name'])}</td><td>{esc(item['company_name'])}</td><td>{esc(item['stock_code'])}</td></tr>"
        for item in corrected
    ) or "<tr><td colspan='3'>없음</td></tr>"
    zero_news = ", ".join(report["news"]["zero_news_companies"]) or "없음"
    zero_disclosures = ", ".join(report["disclosures"]["zero_disclosure_companies"]) or "없음"
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>포트폴리오 로컬 검토</title><style>
:root{{--ink:#18201f;--muted:#64706d;--line:#dce2df;--panel:#fff;--soft:#f4f7f5;--accent:#00645c}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--soft);color:var(--ink);font:14px/1.55 Arial,"Noto Sans KR",sans-serif}}
main{{width:min(1280px,calc(100% - 32px));margin:32px auto 64px}}header{{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:24px}}
h1{{margin:0;font-size:30px}}h2{{margin:0 0 14px;font-size:20px}}p{{color:var(--muted)}}section{{margin:0 0 18px;padding:20px;background:var(--panel);border:1px solid var(--line);border-radius:6px}}
.metrics{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line)}}.metric{{padding:14px;background:#fff}}.metric b{{display:block;font-size:21px}}.metric span{{color:var(--muted);font-size:12px}}
.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}th{{background:var(--soft);font-size:12px}}
details{{border-top:1px solid var(--line);padding:10px 0}}summary{{cursor:pointer;font-weight:700}}ul{{margin:10px 0 0;padding-left:20px}}li{{margin:7px 0}}a{{color:var(--accent);font-weight:650;text-decoration:none}}small{{color:var(--muted)}}
.score{{display:inline-block;min-width:92px;font-size:11px;font-weight:800;text-transform:uppercase}}.critical{{color:#b42318}}.important{{color:#9a6700}}.watch{{color:#00645c}}.notice{{padding:12px;background:#fff8e6;border-left:3px solid #9a6700}}
@media(max-width:760px){{main{{width:min(100% - 20px,1280px);margin-top:18px}}header{{display:block}}.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}section{{padding:14px}}}}
</style></head><body><main>
<header><div><h1>포트폴리오 로컬 검토</h1><p>61개 관심 기업 등록, 뉴스 품질, 공시 수집 상태</p></div><p>{esc(report['generated_at'])}</p></header>
<section><h2>실행 요약</h2><div class="metrics">
<div class="metric"><b>{report['registration']['registered_companies']}</b><span>등록 기업</span></div>
<div class="metric"><b>{report['news']['raw_articles']}</b><span>원시 기사</span></div>
<div class="metric"><b>{report['news']['relevant_articles']}</b><span>관련 기사</span></div>
<div class="metric"><b>{report['news']['duplicates_removed']}</b><span>중복 제거</span></div>
<div class="metric"><b>{report['news']['quality_exclusions']}</b><span>품질 제외</span></div>
<div class="metric"><b>{report['disclosures']['total_disclosures']}</b><span>공시</span></div></div></section>
<section><h2>공식 검증 보정</h2><div class="table-wrap"><table><thead><tr><th>입력명</th><th>KIND 공식명</th><th>코드</th></tr></thead><tbody>{corrected_rows}</tbody></table></div></section>
<section><h2>기업별 현황</h2><div class="table-wrap"><table><thead><tr><th>기업</th><th>코드</th><th>카테고리</th><th>Tier</th><th>검증</th><th>뉴스</th><th>공시</th><th>N/G 호출</th><th>시간</th></tr></thead><tbody>{''.join(company_rows)}</tbody></table></div></section>
<section><h2>Tier별 상위 뉴스</h2>{''.join(news_sections) or '<p>표시할 뉴스 없음</p>'}</section>
<section><h2>최근 공시</h2>{''.join(disclosure_sections) or '<p>수집된 공시 없음</p>'}</section>
<section><h2>데이터 공백</h2><p><b>뉴스 0건:</b> {esc(zero_news)}</p><p><b>공시 0건:</b> {esc(zero_disclosures)}</p></section>
<section><h2>품질 및 오류</h2><p>품질 제외 {report['news']['quality_exclusions']}건 · 교차 기업 중복 후보 {report['news']['remaining_cross_company_duplicates']}건</p>
<p>Naver 호출 {report['news']['provider_calls'].get('naver',0)}회 · GDELT 호출 {report['news']['provider_calls'].get('gdelt',0)}회</p>
<p>Provider 오류: {esc(json.dumps(report['news']['provider_errors'], ensure_ascii=False))}</p>
<p class="notice">Telegram 상태: {esc(report['telegram']['status'])}. 승인되지 않은 경우 cursor와 공개 공시 데이터는 갱신되지 않습니다.</p></section>
</main></body></html>"""


def main():
    report = build_report()
    write_json_atomic(ROOT / "data" / "portfolio-operation-report.json", report)
    review_path = ROOT / "review" / "portfolio-review.html"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(render_html(report), encoding="utf-8")
    print(f"Review companies: {len(report['companies'])}")
    print(f"Zero-news companies: {len(report['news']['zero_news_companies'])}")
    print(f"Zero-disclosure companies: {len(report['disclosures']['zero_disclosure_companies'])}")


if __name__ == "__main__":
    main()
