# 매일 발행 예약 작업 지시문

Claude 예약 작업 '대학 조간 매일 발행'(매일 09:00 KST)에 들어 있는 지시문 원본입니다.
작업이 사라지거나 다시 만들어야 할 때 이 내용을 그대로 쓰면 됩니다.

---

'대학 조간'(https://claude.ai/artifact/5v6MqnwGdhjaKEyPwWUbVM)에 오늘자 판을 발행한다. 사람 확인 없이 끝까지 진행하고, 끝나면 한 줄로 결과(건수)만 보고한다.

## 1. 수집 실행하고 수집 파일 읽기
- 오늘 날짜와 시각(Asia/Seoul)을 확인한다. 09:00 전이면 09:00이 지날 때까지 기다린다(Bash sleep).
- 수집 범위는 전날 09:00 ~ 오늘 09:00(KST)이다. 수집은 이 작업이 직접 실행한다(자동 예약 없음).
- ToolSearch로 `mcp__github__actions_run_trigger`, `mcp__github__actions_list`를 불러온다. 없으면 발행하지 말고 PushNotification으로 "GitHub 도구가 없어 수집을 실행하지 못함"을 알리고 끝낸다.
- `actions_run_trigger` method "run_workflow", owner "yoyoge18-beep", repo "campus-morning", workflow_id "collect.yml", ref "main" 으로 수집을 실행한다.
- 30초마다(Bash sleep 30) `actions_list` method "list_workflow_runs", resource_id "collect.yml" 로 방금 실행한 run(event workflow_dispatch, 실행 이후 created_at)의 상태를 본다. completed + success가 되면 다음으로 간다.
- 실패했거나 10분이 지나도 끝나지 않으면 한 번만 다시 실행한다. 그래도 안 되면 발행하지 말고 PushNotification으로 실패 내용을 알리고 끝낸다. 지난 수집 파일이나 웹 검색으로 대신 채우지 않는다.
- `curl -sL "https://raw.githubusercontent.com/yoyoge18-beep/campus-morning/main/data/latest.json?t=$(date +%s)"` 로 수집 파일을 읽는다. date가 오늘이고 window_end가 오늘 09:00(+09:00)인지 확인한다. 아니면 60초 뒤 다시 읽기를 5번까지 하고(또는 `mcp__github__get_file_contents`로 data/<오늘>.json), 그래도 다르면 발행하지 말고 알린다.
- 항목 필드: title, url, source/domain, published, priority(1 경남정보대, 2 부산 대학, 3 전국), via(naver=원문 링크, google=구글 경유 링크, busan.com), date_verified, outlet(언론사명), outlet_tier(언론사 순위).

## 2. 고르기
- **언론사 제한(필수):** 아래 13개 언론사 기사만 싣는다. 그 밖의 매체는 대표 기사로도, also에도 넣지 않는다. (수집 파일은 이미 이 목록으로 걸러져 있음)
  - 1순위: 부산일보, 국제신문, KNN
  - 2순위: 한국대학신문, 조선일보, 중앙일보, 동아일보, 연합뉴스, 한겨레, 경향신문, 한국일보
  - 3순위: 아시아경제, 아주경제
- 키워드만 스친 잡음은 걸러낸다. 제목·내용상 해당 대학이 주인공이 아닌 기사(교육감 선거, 화재, 타 지역 행사, 연예 인터뷰, 건강 칼럼 등)는 뺀다. 애매하면 WebFetch로 원문을 열어 확인한다.
- **날짜 검증(필수):** 구글 뉴스는 몇 달 전 기사를 재색인해 최근 날짜를 붙이는 경우가 있다(예: 2026.06.12 기사가 10.14로 표시됨). date_verified가 false인 항목은 넣기 전에 반드시 원문의 실제 발행일을 확인한다. 구글 링크는 WebFetch로 열리지 않을 수 있으므로 WebSearch로 같은 제목을 찾아 원문 페이지를 열고 '입력/승인/발행' 일자를 읽는다. 실제 발행일이 3일보다 오래됐거나 확인이 안 되면 넣지 않는다. date 필드에는 원문의 실제 발행일을 쓴다.
- 오늘판에는 지난 판에 이미 실린 기사(같은 제목·같은 소식)를 다시 넣지 않는다. 지난 판 내용은 3단계에서 읽는 월별 파일에 있다.
- 경남정보대: 경남정보대(학생·졸업생·학과 포함)가 실질적으로 등장하는 새 기사는 빠짐없이 넣는다.
- 부산 대학: 부산 소재 대학(부산대, 동아대, 동의대, 경성대, 국립부경대, 국립한국해양대, 동서대, 신라대, 동명대, 부산외대, 고신대, 부산가톨릭대, 부산교대, 영산대, 동의과학대, 부산경상대, 부산여대, 대동대, 동주대, 부산보건대, 부산과학기술대, 부산예술대, 춘해보건대, 부산디지털대 등). 병원·대학 무관 기사는 제외.
- 전국: 대학 정책·입시·주요 대학 소식.
- 같은 소식을 여러 매체가 쓴 경우 하나로 묶는다. 대표 1건 + 나머지는 also 배열 {source, url}. 대표는 언론사 순위가 가장 높은 기사(같은 순위면 via=naver 원문 주소 우선), also도 순위순.
- 기사 수는 채우려 하지 말고 해당 언론사에 실린 만큼만 싣는다(부산 대학 최대 25건, 전국 최대 8건).

## 3. 발행 (Artifact 도구 — 로그인 없이 누구나 보는 정적 파일)
1. Artifact action "read", url 위 주소, paths ["editions/index.json", "editions/<YYYY-MM>.json"] 로 현재 파일을 받는다(이번 달 파일이 없으면 새로 만든다). 페이지 본문도 action "read"(path "index.html" 또는 page 읽기)로 받아 로컬 파일로 저장해 둔다.
2. 이번 달 파일 {"editions":[...]} 에 오늘 판을 넣는다(같은 id가 있으면 교체). editions는 id 내림차순.
   오늘 판 형식:
   {"id": "YYYY-MM-DD",
    "headline": 경남정보대 기사를 앞세운 짧은 제목,
    "brief": 경남정보대 → 부산 → 전국 순 1~2문장 개관,
    "generatedAt": ISO 시각(+09:00),
    "items": [{"category": "경남정보대" | "부산 대학" | "정책·국감" | "입시" | "연구·성과" | "대학 소식" | "산학·지역",
               "title", "url", "source"(언론사명, 위 목록 표기 그대로), "tier"(언론사 순위 1|2|3), "date"("MM.DD", 원문 실제 발행일), "summary", "also": [{"source","url"}]}]}
   - 사이트는 분야 안에서 tier → 날짜 최신순으로 정렬해 보여준다.
   - summary는 한 문장. 원문 문장을 복사하지 말고 직접 다시 쓴다.
3. index.json {"months":[...], "latest": 오늘} 을 갱신한다(이번 달이 없으면 months에 추가).
4. Artifact publish: url 위 주소, file_path = 받아 둔 페이지 HTML(내용 수정 금지), files = {"editions/index.json": 로컬경로, "editions/<YYYY-MM>.json": 로컬경로}. capabilities는 넘기지 않는다. 지난달 파일은 건드리지 않는다.
5. 발행 후 Artifact read로 editions/index.json의 latest가 오늘인지 확인한다.
