# 대학 조간

경남정보대 → 부산 소재 대학 → 전국 대학 순으로, 매일 아침 대학 기사를 모아 보여주는 사이트입니다.

- **사이트:** https://claude.ai/artifact/5v6MqnwGdhjaKEyPwWUbVM (링크가 있는 누구나, 로그인 없이 열람)
- **발행:** 매일 09:00 KST 자동(수집 포함) → 09:10쯤부터 확인, 발행되면 휴대폰 알림(건수)
- **수집 범위:** 전날 09:00 ~ 당일 09:00 (KST), 실행 시각과 관계없이 고정

## 매일 아침 흐름

| 시각 (KST) | 하는 곳 | 하는 일 |
|---|---|---|
| 09:00 | Claude 예약 작업 '대학 조간 매일 발행' | GitHub Actions 수집(`collect.yml`)을 직접 실행하고 끝날 때까지 기다림 → `collect.py`가 전날 09:00~당일 09:00 기사를 네이버 뉴스 API·구글 뉴스·부산일보 대학소식에서 모아 `data/YYYY-MM-DD.json`, `data/latest.json` 저장 |
| 09:02쯤 | 같은 작업 | `data/latest.json`을 읽어 잡음 제거·날짜 검증·같은 소식 묶기·요약 → 사이트의 `editions/YYYY-MM.json`에 오늘 판 추가 후 발행. 수집이 실패하면 발행하지 않고 알림 |
| 09:10쯤 | 사이트 | 오늘 판 열람, 날짜 버튼으로 지난 판 열람 |

## 폴더 구성

| 경로 | 내용 |
|---|---|
| `collect.py` | 수집 스크립트. 키워드는 `KEYWORDS`(1 경남정보대, 2 부산 대학, 3 전국)에서 수정 |
| `.github/workflows/collect.yml` | 수집 실행(자동 예약 없음). 발행 작업이 실행하며, Actions 탭 → Run workflow로 수동 실행 가능 |
| `data/` | 날짜별 수집 원자료 |
| `site/index.html` | 사이트 페이지 원본 (백업) |
| `site/editions/` | 발행된 판 백업 (`index.json` + 월별 `YYYY-MM.json`). 실제 사이트의 최신본은 아티팩트에 있음 |
| `docs/daily-publish-prompt.md` | 매일 발행 예약 작업 지시문 원본 |
| `docs/setup-log.md` | 설정 과정과 문제 해결 기록 |

## 설정 정보

- **네이버 검색 API:** 네이버 클라우드 → NAVER API HUB → Application `campus-morning`(뉴스 검색). 하루 25,000회 한도, 현재 무료.
  - 키는 저장소 Settings → Secrets and variables → Actions의 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`에 있음.
  - 키가 없어도 구글 뉴스·부산일보만으로 수집은 계속 됨.
- **지난 범위 다시 수집:** 환경변수 `COLLECT_END`(예: `2026-10-16T09:00+09:00`)를 주면 그 시각을 끝으로 24시간을 모음.
- **사이트 데이터 구조:** 페이지가 `editions/index.json`을 읽고 최신 달 파일을 불러옴. 한 판 형식은 `docs/daily-publish-prompt.md` 3단계 참고.

## 사이트를 다시 올려야 할 때

`site/index.html`과 `site/editions/*.json`을 Claude에게 주고 같은 아티팩트 주소에 다시 발행해 달라고 하면 됩니다.
