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
│  └─ disclosures.json
├─ README.md
└─ .gitignore
```

## 데이터 수정 위치

- 관심 종목 목록: `data/earnings.json`의 `watchlist`
- 분기 실적: `data/earnings.json`의 `companies[].earnings`
- 공시 목록: `data/disclosures.json`의 `disclosures`
- 공시 분류: `data/disclosures.json`의 `categories`

YoY와 QoQ는 `app.js`가 화면에서 자동 계산합니다. JSON 파일에는 계산 결과를 직접 넣지 않습니다.

관심 종목 탭에서는 기업별 최근 8개 분기 매출액과 영업이익을 작은 막대그래프로 요약합니다. 기업 행을 선택하면 실적 탭으로 이동해 상세 실적, 최근 공시, 최근 뉴스 영역을 확인할 수 있습니다.

## 현재 포함된 예시 데이터

- SK하이닉스 `000660`: 관심 종목 구조만 포함
- 삼성전자 `005930`: 관심 종목 구조만 포함
- 동원금속 `018500`: 제공된 2025 Q1부터 2026 Q1까지의 실적과 2026년 6월 19일 사업보고서 공시 포함

최근 8개 분기 중 동원금속의 2024 Q2, 2024 Q3, 2024 Q4는 데이터가 없어 `N/A`로 표시됩니다.

## 참고

`index.html`을 더블클릭해 여는 경우 일부 브라우저는 보안 정책상 JSON 파일 읽기를 제한합니다. 그래서 더블클릭 실행에서도 화면이 정상적으로 보이도록 `app.js` 안에 같은 예시 데이터를 기본값으로 넣어두었습니다. GitHub Pages에서는 `data/*.json` 파일을 정상적으로 읽습니다.

서버, 데이터베이스, API 키, 비밀정보, Node.js 빌드 과정은 사용하지 않습니다.
