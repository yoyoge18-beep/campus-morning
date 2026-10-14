# 대학 조간 수집기

매일 08:00(KST)에 GitHub Actions가 대학 기사를 모아 `data/YYYY-MM-DD.json`으로 저장합니다.
08:45에 Claude 예약 작업이 이 파일을 읽어 '대학 조간'에 오늘 판을 발행합니다.

- 출처: 네이버 뉴스 검색 API(최신순, 원문 주소 포함), 부산일보 대학소식
- 우선순위: 1 경남정보대 → 2 부산 소재 대학 → 3 전국 대학 정책·입시

## 처음 설정
1. 저장소 **Settings → Secrets and variables → Actions → New repository secret**
   - `NAVER_CLIENT_ID`
   - `NAVER_CLIENT_SECRET`
2. **Actions** 탭 → '대학 조간 수집' → **Run workflow**로 한 번 실행해 확인

키워드는 `collect.py`의 `KEYWORDS`에서 바꿉니다.
