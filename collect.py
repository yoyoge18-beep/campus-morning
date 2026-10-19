"""대학 조간 수집기 — 매일 09:00 발행 작업이 GitHub Actions로 실행.

1) 네이버 뉴스 검색 API(최신순)로 키워드별 기사 수집 → 원문 주소(originallink) 포함
2) 부산일보 대학소식 목록 페이지 수집
수집 범위: 전날 09:00 ~ 당일 09:00 (KST). 실행 시각과 관계없이 "직전 09:00"이 끝.
  단, 월요일판의 경남정보대(1순위)는 금요일 09:00 ~ 월요일 09:00 (주말 보도분까지).
결과: data/YYYY-MM-DD.json (범위 끝 날짜 기준)
"""
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
CUTOFF_HOUR = 9  # 판 마감 시각 (KST)


def window_end(now: datetime) -> datetime:
    """직전 09:00. 09:00 이전에 실행하면 전날 09:00."""
    end = now.replace(hour=CUTOFF_HOUR, minute=0, second=0, microsecond=0)
    return end if now >= end else end - timedelta(days=1)


# COLLECT_END(예: 2026-10-16T09:00+09:00)로 범위 끝을 직접 지정할 수 있음(다시 수집할 때)
_end_env = os.environ.get("COLLECT_END", "").strip()
END = datetime.fromisoformat(_end_env).astimezone(KST) if _end_env else window_end(NOW)
SINCE = END - timedelta(hours=24)
# 월요일판: 경남정보대 기사는 금요일 09:00부터 (금·토·일 보도분도 월요일판에 다시 모음)
SINCE_KIT = END - timedelta(days=3) if END.weekday() == 0 else SINCE


def in_window(t: datetime, since: datetime = None) -> bool:
    return (since or SINCE) <= t < END


def is_kit(title: str) -> bool:
    return "경남정보" in (title or "")

# 우선순위 순서: 1 = 경남정보대, 2 = 부산 대학, 3 = 전국
KEYWORDS = {
    1: ["경남정보대", "경남정보대학교"],
    2: [
        "부산대", "부산대학교", "동아대", "동의대", "경성대", "부경대", "국립부경대",
        "한국해양대", "동서대", "신라대", "동명대", "부산외대", "부산외국어대",
        "고신대", "부산가톨릭대", "부산교대", "영산대", "부산디지털대",
        "동의과학대", "부산경상대", "부산여대", "대동대", "동주대", "부산보건대",
        "부산과학기술대", "부산예술대", "춘해보건대", "부산 대학", "부산 전문대",
    ],
    3: ["대학 교육부", "대학 입시", "전문대학", "글로컬대학", "RISE 대학"],
}

UA = {"User-Agent": "Mozilla/5.0 (campus-morning collector)"}

# 싣는 언론사 (이 목록 밖의 매체는 버림). tier: 1이 가장 우선.
OUTLETS = [
    # (도메인 끝부분, 매체명, 순위)
    ("busan.com", "부산일보", 1),
    ("kookje.co.kr", "국제신문", 1),
    ("knn.co.kr", "KNN", 1),
    ("unn.net", "한국대학신문", 2),
    ("chosun.com", "조선일보", 2),
    ("joongang.co.kr", "중앙일보", 2),
    ("donga.com", "동아일보", 2),
    ("yna.co.kr", "연합뉴스", 2),
    ("hani.co.kr", "한겨레", 2),
    ("khan.co.kr", "경향신문", 2),
    ("hankookilbo.com", "한국일보", 2),
    ("asiae.co.kr", "아시아경제", 3),
    ("ajunews.com", "아주경제", 3),
]
OUTLET_BY_NAME = {n: (n, t) for _, n, t in OUTLETS}
OUTLET_BY_NAME.update({"한겨례": ("한겨레", 2), "KNN 뉴스": ("KNN", 1)})


def outlet_of(domain: str, source_name: str = ""):
    d = (domain or "").lower()
    for suffix, name, tier in OUTLETS:
        if d == suffix or d.endswith("." + suffix):
            return name, tier
    s = (source_name or "").strip()
    return OUTLET_BY_NAME.get(s, (None, None))


# 1순위 지역 언론사는 사이트 지정 검색으로 한 번 더 훑음(구글 뉴스)
SITE_QUERIES = [f"{kw} site:{dom}" for dom in ("busan.com", "kookje.co.kr", "knn.co.kr")
                for kw in ("경남정보대", "대학")]


def clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return html.unescape(s).strip()


def naver_news(query: str, cid: str, secret: str, since: datetime = None) -> list[dict]:
    since = since or SINCE
    # NAVER API HUB (2026.7.31 이후 신규 발급분) — 네이버 클라우드 콘솔에서 발급한 키
    url = "https://naverapihub.apigw.ntruss.com/search/v1/news"
    headers = {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": secret}
    out = []
    for start in (1, 101):
        r = requests.get(url, headers=headers,
                         params={"query": query, "display": 100, "start": start,
                                 "sort": "date", "format": "json"},
                         timeout=20)
        if r.status_code != 200:
            print(f"[naver] {query} {r.status_code} {r.text[:200]}", file=sys.stderr)
            break
        items = r.json().get("items", [])
        stop = False
        for it in items:
            try:
                pub = parsedate_to_datetime(it["pubDate"]).astimezone(KST)
            except Exception:
                continue
            if pub < since:
                stop = True  # 최신순이므로 이후는 모두 범위 밖
                continue
            if pub >= END:
                continue
            link = it.get("originallink") or it.get("link")
            out.append({
                "title": clean(it.get("title")),
                "url": link,
                "naver_url": it.get("link"),
                "domain": urlparse(link).netloc.replace("www.", ""),
                "published": pub.isoformat(),
                "snippet": clean(it.get("description"))[:160],
                "query": query,
                "via": "naver",
            })
        if stop or len(items) < 100:
            break
        time.sleep(0.2)
    return out


def busan_ilbo() -> list[dict]:
    out = []
    for page in (1, 2):
        try:
            r = requests.get("https://www.busan.com/university/", params={"page": page},
                             headers=UA, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print(f"[busan.com] {e}", file=sys.stderr)
            break
        soup = BeautifulSoup(r.text, "html.parser")
        seen = set()
        for a in soup.select('a[href*="view.php?code="]'):
            title = a.get_text(" ", strip=True)
            href = requests.compat.urljoin("https://www.busan.com/", a.get("href"))
            if len(title) < 8 or href in seen:
                continue
            seen.add(href)
            # 기사 코드 앞 12자리 = 입력 시각(YYYYMMDDHHMM)
            m = re.search(r"code=(\d{12})", href)
            if not m:
                continue
            try:
                day = datetime.strptime(m.group(1), "%Y%m%d%H%M").replace(tzinfo=KST)
            except ValueError:
                continue
            if not in_window(day, SINCE_KIT if is_kit(title) else SINCE):
                continue
            out.append({
                "title": title[:120], "url": href, "domain": "busan.com",
                "published": day.isoformat(), "snippet": "", "query": "부산일보 대학소식",
                "via": "busan.com",
            })
    return out


def google_news(query: str, since: datetime = None) -> list[dict]:
    """구글 뉴스 RSS — 링크는 구글 경유 주소(누르면 원문으로 이동)."""
    since = since or SINCE
    days = max(2, (END - since).days + 1)
    try:
        r = requests.get("https://news.google.com/rss/search",
                         params={"q": f"{query} when:{days}d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"},
                         headers=UA, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"[gnews] {query} {e}", file=sys.stderr)
        return []
    soup = BeautifulSoup(r.content, "xml")
    out = []
    for it in soup.find_all("item"):
        try:
            pub = parsedate_to_datetime(it.pubDate.text).astimezone(KST)
        except Exception:
            continue
        if not in_window(pub, since):
            continue
        src = it.source.text.strip() if it.source else ""
        src_url = it.source.get("url", "") if it.source else ""
        title = clean(it.title.text)
        if src and title.endswith(" - " + src):
            title = title[: -len(" - " + src)]
        out.append({
            "title": title, "url": it.link.text.strip(), "source": src,
            "domain": urlparse(src_url).netloc.replace("www.", ""),
            "published": pub.isoformat(), "snippet": "", "query": query, "via": "google",
        })
    return out


def save_managed_kit(by_url: dict):
    """광고비 지원 관리 언론사(managed_outlets.json)의 경남정보대 기사 — 언론사별 기사 노출 집계용.
    월요일 확장 범위와 관계없이 하루(전날 09:00~당일 09:00) 기준으로만 센다."""
    try:
        cfg = json.loads(Path("managed_outlets.json").read_text(encoding="utf-8"))["outlets"]
    except Exception as e:
        print(f"[managed] {e}", file=sys.stderr)
        return
    by_name = {o["name"]: o for o in cfg}

    def managed_of(it):
        d = (it.get("domain") or "").lower()
        for o in cfg:
            if any(d == x or d.endswith("." + x) for x in o["domains"]):
                return o["name"]
        src = (it.get("source") or "").replace(" ", "")
        for n in by_name:
            if src and (src == n.replace(" ", "") or src.startswith(n)):
                return n
        return None

    rows, seen = [], set()
    for it in sorted(by_url.values(), key=lambda x: x["via"] != "naver"):
        if it["priority"] != 1:
            continue
        # 네이버는 '경남'·'정보대'를 따로 맞추기도 하므로 제목이나 요약에 '경남정보'가 있어야 함
        if "경남정보" not in (it.get("title", "") + it.get("snippet", "")):
            continue
        t = datetime.fromisoformat(it["published"])
        if not (SINCE <= t < END):
            continue
        name = managed_of(it)
        if not name:
            continue
        tkey = (name, re.sub(r"\W", "", it["title"])[:25])
        if tkey in seen:
            continue
        seen.add(tkey)
        rows.append({"outlet": name, "title": it["title"], "url": it["url"],
                     "published": it["published"], "via": it["via"],
                     "in_title": "경남정보" in it["title"]})
    day = END.strftime("%Y-%m-%d")
    Path("data/kit").mkdir(parents=True, exist_ok=True)
    Path(f"data/kit/{day}.json").write_text(json.dumps(
        {"date": day, "window_start": SINCE.isoformat(), "window_end": END.isoformat(),
         "count": len(rows), "items": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"관리 언론사 경남정보대 기사 {len(rows)}건", file=sys.stderr)


def main():
    cid = os.environ.get("NAVER_CLIENT_ID")
    secret = os.environ.get("NAVER_CLIENT_SECRET")
    use_naver = bool(cid and secret)
    if not use_naver:
        print("네이버 키 없음 → 구글 뉴스 + 부산일보만 수집", file=sys.stderr)

    by_url: dict[str, dict] = {}
    seen_titles: set[str] = set()
    uni_names = [w for w in KEYWORDS[1] + KEYWORDS[2] if " " not in w] + ["경남정보大", "부산대"]
    for priority, words in KEYWORDS.items():
        since = SINCE_KIT if priority == 1 else SINCE
        for q in words:
            found = naver_news(q, cid, secret, since) if use_naver else []
            found += google_news(q, since)
            for it in found:
                tkey = re.sub(r"\W", "", it["title"])[:40]
                if it["via"] == "google" and tkey in seen_titles:
                    continue
                seen_titles.add(tkey)
                key = it["url"]
                prev = by_url.get(key)
                if prev:
                    prev["priority"] = min(prev["priority"], priority)
                    prev.setdefault("queries", [prev["query"]]).append(q)
                    continue
                it["priority"] = priority
                by_url[key] = it
            time.sleep(0.15)
    for q in SITE_QUERIES:
        for it in google_news(q, SINCE_KIT if "경남정보대" in q else SINCE):
            if it["url"] in by_url:
                continue
            # 사이트 검색은 본문 옆 기사 목록까지 걸리므로, 제목에 대학 이름이 있는 기사만
            if not any(n in it["title"] for n in uni_names):
                continue
            tkey = re.sub(r"\W", "", it["title"])[:40]
            if tkey in seen_titles:
                continue
            seen_titles.add(tkey)
            it["priority"] = 1 if "경남정보대" in it["title"] else 2
            by_url[it["url"]] = it
        time.sleep(0.15)
    for it in busan_ilbo():
        if it["url"] not in by_url:
            it["priority"] = 2
            by_url[it["url"]] = it

    # 구글 결과는 본문 옆 목록 때문에 무관한 기사가 섞임 → 제목 기준으로 다시 거름
    for url in list(by_url):
        it = by_url[url]
        if it["via"] != "google" or it["priority"] == 3:
            continue
        t = it["title"]
        if "경남정보" in t:
            it["priority"] = 1
        elif any(n in t for n in uni_names):
            it["priority"] = 2
        else:
            del by_url[url]

    save_managed_kit(by_url)

    # 지정 언론사만 남김
    kept = {}
    for url, it in by_url.items():
        name, tier = outlet_of(it.get("domain", ""), it.get("source", ""))
        if not name:
            continue
        it["outlet"], it["outlet_tier"] = name, tier
        kept[url] = it
    print(f"지정 언론사 {len(kept)}건 / 전체 {len(by_url)}건", file=sys.stderr)
    by_url = kept

    # 구글 뉴스는 옛 기사를 재색인하며 날짜를 새로 붙이는 경우가 있음(예: 6월 기사가 10월로 표시).
    # 네이버 결과에 같은 제목이 없으면 날짜 미확인으로 표시 → 발행 단계에서 원문 날짜 확인.
    naver_titles = {re.sub(r"\W", "", i["title"])[:25] for i in by_url.values() if i["via"] == "naver"}
    for it in by_url.values():
        if it["via"] == "google":
            it["date_verified"] = re.sub(r"\W", "", it["title"])[:25] in naver_titles
        else:
            it["date_verified"] = True

    items = sorted(by_url.values(), key=lambda x: (x["priority"], x["published"]), reverse=False)
    items.sort(key=lambda x: (x["priority"], x["outlet_tier"], -datetime.fromisoformat(x["published"]).timestamp()))

    day = END.strftime("%Y-%m-%d")
    Path("data").mkdir(exist_ok=True)
    payload = {"date": day, "collected_at": NOW.isoformat(),
               "window_start": SINCE.isoformat(), "window_end": END.isoformat(),
               "window_start_kit": SINCE_KIT.isoformat(),
               "count": len(items), "items": items}
    Path(f"data/{day}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    Path("data/latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {p: sum(1 for i in items if i["priority"] == p) for p in (1, 2, 3)}
    print(f"{day}: 총 {len(items)}건 (경남정보대 {counts[1]}, 부산 {counts[2]}, 전국 {counts[3]})")


if __name__ == "__main__":
    main()
