# 로컬 데이터 운영 설계

## 실행 주기

기본 운영 시각은 `Asia/Seoul` 기준 매일 `08:15`, `20:15`입니다.

- UTC cron 참고값: `15 11,23 * * *`
- 대안 참고 시각: `02:17`, `14:17`
- 대안 UTC cron: `17 5,17 * * *`
- 이번 단계에서는 GitHub Actions workflow 파일을 생성하지 않습니다.

향후 workflow를 만들 때는 concurrency group을 `stock-intelligence-data-update`로 고정하고 `cancel-in-progress: false`를 사용합니다. 같은 group의 실행이 겹치면 뒤 실행이 기다리게 하여 cursor와 공개 JSON의 동시 쓰기를 방지합니다.

## 증분 수집

일반 실행은 최근 16시간을 기본 범위로 사용합니다. 이전 정상 실행 시각과 3시간 overlap을 적용하되 16시간보다 오래 조회하지 않습니다. 신규 기업 또는 명시적인 `--backfill` 실행만 최근 7일을 조회합니다.

기업별 provider cursor는 `data/state/news-cursors.json`에 저장합니다. provider 성공 시에만 정상 실행 시각과 최신 기사 시각을 갱신합니다. 실패한 provider cursor는 진행하지 않으며 다음 실행에서 실패 기업을 먼저 처리합니다.

Telegram은 `data/state/telegram-cursor.json`의 message ID 이후 메시지를 실행당 한 번만 가져옵니다. 전체 기업 별칭·종목코드와 대조해 분배한 뒤 모든 기업 처리가 성공한 경우에만 message ID를 갱신합니다.

## 요청 예산

기본 기업당 실행 예산은 Naver 최대 3회, GDELT 1회입니다. Naver 자동 수집은 최신순 검색만 사용하며 기업명과 중요 키워드를 조합한 최대 3개 검색어만 생성합니다.

- Naver 실행 hard limit: 500회
- Naver 일일 hard limit: 20,000회
- GDELT 실행 hard limit: 220회
- GDELT 요청 사이 기본 지연: 1초
- 우선순위: 실패 재시도, `core`, `watch`, `background`

100개 기업을 하루 두 번 처리할 때 목표 호출량은 Naver 약 400회/일, GDELT 약 200회/일입니다. 기업당 최대 예산을 전부 사용해도 Naver 600회/일, GDELT 200회/일입니다.

## 배치와 파일 안전성

기본 batch 크기는 25개이며 순차 실행합니다. `max_concurrency`는 향후 확장값으로 2를 넘지 않게 설정했습니다. 각 batch가 끝날 때 cursor와 dashboard index를 임시 파일에 쓴 뒤 atomic replace합니다.

한 기업 또는 provider가 실패해도 다른 기업은 계속 처리합니다. 실패 기업의 기존 공개 파일은 빈 배열로 교체하지 않습니다. 전체 활성 기업이 실패하면 실행 보고서의 `severe_failure`가 `true`, `commit_eligible`이 `false`가 됩니다.

## 공개 파일

최초 화면은 다음 index만 읽습니다.

- `data/news/index.json`
- `data/earnings/index.json`
- `data/disclosures/index.json`

기업을 선택하면 `data/*/by-company/{stock_code}.json`을 지연 로딩합니다. 뉴스 index에는 관련 기사 배열을 넣지 않으며 기업당 최근 사건 요약 최대 3개만 포함합니다. 뉴스 화면은 40개 단위 더 보기 방식으로 렌더링합니다.

기존 `data/news.json`, `data/earnings.json`, `data/disclosures.json`은 하위 호환용으로 유지합니다. `scripts/migrate_split_data.py`가 기존 파일에서 분할 파일을 안전하게 다시 생성합니다.

## 보존 정책

- `critical`, `important`, `watch`: 최근 90일, 기업당 최대 100개 사건
- `contextual`: 최근 30일, 기업당 최대 30개 사건
- `low`, `market_noise`: 최근 30일, 검토 샘플 최대 10개
- `irrelevant`: 집계만 유지하고 공개 파일에서 제외
- 중복 hash와 event fingerprint: 최근 90일만 유지

기사 본문, 검색 description, 웹페이지 HTML, 이미지, 인증정보는 공개 데이터와 실행 보고서에 저장하지 않습니다.

## 실행 명령

실제 증분 실행 준비 명령은 다음과 같습니다. 자동 스케줄은 아직 연결하지 않았습니다.

```powershell
.\.venv\Scripts\python.exe scripts\run_incremental_news.py
```

신규 기업의 수동 7일 백필:

```powershell
.\.venv\Scripts\python.exe scripts\run_incremental_news.py --backfill
```

mock 부하 테스트:

```powershell
.\.venv\Scripts\python.exe scripts\run_load_test.py
```

## 확장 판단

100개 기업은 현재 순차 구조의 기본 권장 규모입니다. 200개도 mock 검증 범위에 포함되지만 실제 운영에서는 GDELT 요청 지연과 외부 API 응답 시간이 첫 병목입니다.

현재 mock 측정에서 100개는 약 5.89초·356KB, 200개는 약 15.62초·716KB였습니다. 이는 기업당 사건 1개인 합성 데이터이므로 실제 보존 상한에서는 더 커집니다. 현재 SK하이닉스 표본을 기준으로 사건 하나는 평균 약 3.5KB이며, 기업당 평균 20개 사건을 유지하면 100개 약 7MB, 200개 약 14MB로 예상합니다. 모든 기업이 보존 상한을 채우는 극단값은 100개 약 50MB, 200개 약 100MB입니다.

GitHub Pages 게시 사이트와 원본 저장소는 1GB 미만을 목표로 관리합니다. 하루 두 번 변경 데이터를 장기간 커밋하면 현재 파일 크기보다 Git 이력 증가가 먼저 병목이 되므로 무료 GitHub 구조의 권장 상한은 100개, 관리 가능한 상한은 200개로 둡니다.

200개를 넘으면 provider 수집과 파일 merge 단계를 분리하고, 최대 동시성 2의 worker가 기업별 임시 결과를 만든 뒤 단일 merge 단계에서 index와 cursor를 교체하는 구조가 필요합니다. 기업 검색은 정적 index 기반 검색으로 유지하고, 뉴스 목록은 현재 pagination을 가상 목록으로 교체할 수 있습니다.
