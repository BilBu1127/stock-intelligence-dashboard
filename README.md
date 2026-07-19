# Disclosure Notification

개인용 주식 실적·공시 대시보드의 첫 번째 정적 웹 시제품입니다.

GitHub 저장소 이름은 `stock-intelligence-dashboard`이며, 개인용 earnings and disclosure dashboard 용도로 관리합니다.

## 실행 방법

1. 이 폴더에서 `index.html` 파일을 더블클릭합니다.
2. 브라우저가 열리면 관심 종목, 실적, 공시 탭을 확인합니다.
3. GitHub Pages에 올릴 때도 빌드 과정 없이 이 파일들을 그대로 사용하면 됩니다.

## 파일 구조

```text
stock-intelligence-dashboard/
├─ index.html
├─ styles.css
├─ app.js
├─ data/
│  ├─ earnings.json
│  ├─ disclosures.json
│  ├─ parse-report.json
│  ├─ companies.json
│  ├─ news.json
│  ├─ news-report.json
│  ├─ config/pipeline.json
│  ├─ state/news-cursors.json
│  ├─ state/telegram-cursor.json
│  ├─ news/index.json
│  ├─ news/by-company/{stock_code}.json
│  ├─ earnings/index.json
│  ├─ earnings/by-company/{stock_code}.json
│  ├─ disclosures/index.json
│  └─ disclosures/by-company/{stock_code}.json
├─ scripts/
│  ├─ create_telegram_session.py
│  ├─ test_telegram_access.py
│  ├─ parse_awake_message.py
│  ├─ backfill_company.py
│  ├─ score_news.py
│  ├─ fetch_gdelt_news.py
│  ├─ fetch_naver_news.py
│  ├─ normalize_news.py
│  ├─ cluster_news_events.py
│  ├─ build_news_dashboard.py
│  ├─ news_batch_pipeline.py
│  ├─ incremental_provider_adapters.py
│  ├─ run_incremental_news.py
│  ├─ telegram_incremental.py
│  ├─ migrate_split_data.py
│  └─ run_load_test.py
├─ tests/
│  ├─ test_awake_parser.py
│  ├─ test_news_pipeline.py
│  ├─ test_naver_news.py
│  ├─ test_cross_source_clustering.py
│  └─ test_scalable_pipeline.py
├─ requirements.txt
├─ README.md
└─ .gitignore
```

## 데이터 수정 위치

- 관심 종목 목록: `data/earnings.json`의 `watchlist`
- 분기 실적: `data/earnings.json`의 `companies[].earnings`
- 공시 목록: `data/disclosures.json`의 `disclosures`
- 공시 분류: `data/disclosures.json`의 `categories`
- 기업별 뉴스 검색 설정: `data/companies.json`
- 공개 뉴스 cluster: `data/news.json`
- 뉴스 수집·선별 결과: `data/news-report.json`

YoY와 QoQ는 `app.js`가 화면에서 자동 계산합니다. JSON 파일에는 계산 결과를 직접 넣지 않습니다.

관심 종목 탭에서는 기업별 최근 8개 분기 매출액과 영업이익을 작은 막대그래프로 요약합니다. 기업 행을 선택하면 실적 탭으로 이동해 상세 실적, 최근 공시, 최근 뉴스 영역을 확인할 수 있습니다.

## 현재 데이터

- SK하이닉스 `000660`: 관심 종목 구조만 포함
- 삼성전자 `005930`: 관심 종목 구조만 포함
- 동원금속 `018500`: 로컬 Telegram 백필로 검증한 2025 Q1부터 2026 Q1까지의 실적과 관련 공시 포함

동원금속은 현재 검증된 5개 분기만 표시하며, 8개를 채우기 위한 임의 분기는 추가하지 않습니다. 예상치가 없는 값은 `N/A`로 표시됩니다.

## 로컬 Telegram 백필

Telegram 인증정보와 세션은 Git에서 제외된 `.secrets/`에만 저장합니다. 과거 실적 원문은 Git에서 제외된 `private_samples/{종목코드}/` 또는 `private_samples/earnings_backfill/{종목코드}/`에만 둡니다. 이번 실적 백필은 Telegram 채널을 다시 검색하지 않고 이 로컬 TXT 파일만 사용합니다.

```powershell
.\.venv\Scripts\python.exe scripts\backfill_local_earnings.py --dry-run
.\.venv\Scripts\python.exe scripts\backfill_local_earnings.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

공개 실적 파일에는 구조화된 금액, 분기, 잠정·정정 상태, 기준, DART URL만 저장합니다. 원문 파일명·해시는 `private_samples/earnings_backfill_report.json`에만 저장하고, `review/earnings-backfill-review.html`은 로컬 검토용으로 Git에서 제외합니다.

현재 로컬 백필 결과는 61개 기업 모두 최근 8개 분기를 확보했습니다. 빈 분기를 임의의 숫자로 채우지 않으며, 누적 실적·연결/별도 혼용·충돌이 발견되면 공개 반영 전에 검토 상태로 남깁니다.

## 로컬 GDELT 뉴스 수집

GDELT DOC API의 JSON ArticleList에서 최근 제목·URL·출처·게시 시각·언어 메타데이터만 가져옵니다. 기사 본문, 웹페이지 HTML, 이미지, 쿠키, 긴 요약은 다운로드하거나 공개 JSON에 저장하지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m unittest tests\test_news_pipeline.py -v
.\.venv\Scripts\python.exe scripts\fetch_gdelt_news.py --stock-code 000660 --days 7
```

수집 실패나 rate limit 발생 시 기존 `data/news.json`은 유지되고 오류 유형만 `data/news-report.json`에 기록됩니다. 검색 별칭, 중요 키워드, 제외 키워드, 공식·주요 출처 도메인은 `data/companies.json`에서 관리합니다.

## GDELT·NAVER 통합 뉴스

통합 파이프라인은 기사 본문을 내려받지 않고 제목, 링크, 출처, 게시 시각만으로 중복 기사를 제거하고 사건 단위로 묶습니다.

```powershell
.\.venv\Scripts\python.exe scripts\build_news_dashboard.py --stock-code 000660 --days 7
```

NAVER API HUB의 뉴스 검색을 함께 사용하려면 Git에서 제외된 `.secrets/naver.env`에 아래 환경 변수 이름으로 로컬 자격정보를 둡니다. 실제 값은 소스 코드, 공개 JSON, 로그에 저장하지 않습니다.

```text
NAVER_CLIENT_ID=로컬에서_입력
NAVER_CLIENT_SECRET=로컬에서_입력
```

파일이 없거나 값이 비어 있으면 Naver 수집만 안전하게 건너뛰고 GDELT 처리는 계속됩니다. 실행 상태는 `data/news-report.json`의 `credentials_status`에서 확인할 수 있습니다.

공개 뉴스 데이터에는 대표 제목과 링크, 국내·해외 기사 수, 제공자, 중요도, 관련 기사 메타데이터만 들어갑니다. 기사 본문, 검색 결과의 설명문, HTML, 이미지는 `data/news.json`에 저장하지 않습니다.

## 대규모 증분 운영 준비

전체 데이터 갱신은 한국시간 `08:15`, `20:15` 하루 두 번을 기준으로 설계했습니다. 자동 workflow는 아직 만들지 않았습니다.

자동 운영 경로는 최근 16시간과 3시간 overlap을 사용하고, 신규 기업만 7일 백필합니다. 기업당 실행 예산은 Naver 최대 3회, GDELT 1회이며 25개 순차 batch마다 cursor와 index를 checkpoint합니다.

대시보드는 최초에 `data/*/index.json`만 읽고 기업 선택 시 `data/*/by-company/{stock_code}.json`을 지연 로딩합니다. 기존 단일 JSON은 하위 호환을 위해 유지됩니다.

자세한 운영 설계와 용량 판단은 `docs/operations.md`, mock 성능 측정 결과는 `data/load-test-report.json`에서 확인합니다.

## 참고

`index.html`을 더블클릭해 여는 경우 일부 브라우저는 보안 정책상 JSON 파일 읽기를 제한합니다. 그래서 더블클릭 실행에서도 화면이 정상적으로 보이도록 `app.js` 안에 같은 공개 데이터를 기본값으로 넣어두었습니다. GitHub Pages에서는 `data/*.json` 파일을 정상적으로 읽습니다.

서버, 데이터베이스, API 키, 비밀정보, Node.js 빌드 과정은 사용하지 않습니다.
