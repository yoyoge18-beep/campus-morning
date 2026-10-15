# 대학 조간

경남정보대 → 부산 소재 대학 → 전국 대학 순으로, 매일 아침 대학 기사를 모아 보여주는 사이트입니다.

- **사이트:** https://claude.ai/artifact/5v6MqnwGdhjaKEyPwWUbVM (링크가 있는 누구나, 로그인 없이 열람)
- **발행:** 매일 08:40 KST 자동 → 09:00부터 확인

## 매일 아침 흐름

| 시각 (KST) | 하는 곳 | 하는 일 |
|---|---|---|
| 07:30 | GitHub Actions (`.github/workflows/collect.yml`) | `collect.py` 실행 → 네이버 뉴스 API·구글 뉴스·부산일보 대학소식 수집 → `data/YYYY-MM-DD.json`, `data/latest.json` 저장 |
| 08:40 | Claude 예약 작업 '대학 조간 매일 발행' | `data/latest.json`을 읽어 잡음 제거·날짜 검증·같은 소식 묶기·요약 → 사이트의 `editions/YYYY-MM.json`에 오늘 판 추가 후 발행 |
| 09:00 | 사이트 | 오늘 판 열람, 날짜 버튼으로 지난 판 열람 |

## 폴더 구성

| 경로 | 내용 |
|---|---|
| `collect.py` | 수집 스크립트. 키워드는 `KEYWORDS`(1 경남정보대, 2 부산 대학, 3 전국)에서 수정 |
| `.github/workflows/collect.yml` | 매일 07:30 수집 실행. Actions 탭 → Run workflow로 수동 실행 가능 |
| `data/` | 날짜별 수집 원자료 |
| `site/index.html` | 사이트 페이지 원본 (백업) |
| `site/editions/` | 발행된 판 백업 (`index.json` + 월별 `YYYY-MM.json`). 실제 사이트의 최신본은 아티팩트에 있음 |
| `docs/daily-publish-prompt.md` | 매일 발행 예약 작업 지시문 원본 |
| `docs/setup-log.md` | 설정 과정과 문제 해결 기록 |

## 설정 정보

- **네이버 검색 API:** 네이버 클라우드 → NAVER API HUB → Application `campus-morning`(뉴스 검색). 하루 25,000회 한도, 현재 무료.
  - 키는 저장소 Settings → Secrets and variables → Actions의 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`에 있음.
  - 키가 없어도 구글 뉴스·부산일보만으로 수집은 계속 됨.
- **사이트 데이터 구조:** 페이지가 `editions/index.json`을 읽고 최신 달 파일을 불러옴. 한 판 형식은 `docs/daily-publish-prompt.md` 3단계 참고.

## 사이트를 다시 올려야 할 때

`site/index.html`과 `site/editions/*.json`을 Claude에게 주고 같은 아티팩트 주소에 다시 발행해 달라고 하면 됩니다.
