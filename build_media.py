"""관리 언론사 노출 현황(대시보드)용 자료 만들기.

data/kit/*.json(언론사별 경남정보대 기사)와 data/ads/*.json(배너 점검)을 모아
media/ 아래에 행(row) 배열 JSON 4개를 만든다. 매일 발행 작업이 이 파일들을 대시보드에 올린다.

- media/outlets.json     언론사별 요약(오늘·이번 달·누적 기사, 배너 상태, 최근 배너 캡처)
- media/articles.json    관리 언론사의 경남정보대 기사 목록
- media/banner_log.json  날짜·언론사별 배너 점검 결과
- media/daily.json       날짜별 합계(기사 수, 배너 노출 언론사 수)
"""
import base64
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
cfg = json.loads(Path("managed_outlets.json").read_text(encoding="utf-8"))["outlets"]
names = [o["name"] for o in cfg]

# ── 기사
articles, article_days = [], []
for p in sorted(Path("data/kit").glob("????-??-??.json")):
    d = json.loads(p.read_text(encoding="utf-8"))
    article_days.append(d["date"])
    for it in d["items"]:
        articles.append({"date": d["date"], "outlet": it["outlet"], "title": it["title"],
                         "url": it["url"], "published": it["published"][:16].replace("T", " ")})
articles.sort(key=lambda a: a["published"], reverse=True)

# ── 배너 점검
log, ad_days, shots = [], [], {}
for p in sorted(Path("data/ads").glob("????-??-??.json")):
    d = json.loads(p.read_text(encoding="utf-8"))
    ad_days.append(d["date"])
    for r in d["results"]:
        if "pc" not in r and "mobile" not in r:
            continue          # 점검 주소가 없는 언론사
        pc, mo = r.get("pc") or {}, r.get("mobile") or {}
        seen = bool(pc.get("found") or mo.get("found"))
        failed = not seen and bool(pc.get("error")) and bool(mo.get("error"))
        log.append({"date": d["date"], "outlet": r["name"], "pc": bool(pc.get("found")),
                    "mobile": bool(mo.get("found")),
                    "status": "노출" if seen else ("점검 실패" if failed else "미확인")})
        for prof, x in (("PC", pc), ("모바일", mo)):
            sp = x.get("shot")
            if x.get("found") and sp and Path(sp).exists() and Path(sp).stat().st_size < 150_000:
                shots[r["name"]] = (d["date"], prof, sp)   # 날짜순이라 마지막이 최신

latest_ad = ad_days[-1] if ad_days else None
latest_kit = article_days[-1] if article_days else None
month = (latest_kit or latest_ad or datetime.now(KST).strftime("%Y-%m-%d"))[:7]


def periods(rows):
    """점검한 날 기준 연속 노출 기간(점검했는데 안 보인 날에 끊음)."""
    out, cur = [], None
    for r in sorted(rows, key=lambda x: x["date"]):
        if r["status"] == "노출":
            cur = cur or {"start": r["date"], "end": r["date"]}
            cur["end"] = r["date"]
        elif r["status"] == "미확인" and cur:
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    return out


by_outlet_log = defaultdict(list)
for r in log:
    by_outlet_log[r["outlet"]].append(r)

outlets = []
for o in cfg:
    n = o["name"]
    arts = [a for a in articles if a["outlet"] == n]
    lg = by_outlet_log.get(n, [])
    today = next((r for r in lg if r["date"] == latest_ad), None)
    per = periods(lg)
    on_now = bool(today and today["status"] == "노출")
    if not o.get("home"):
        status = "주소 확인 필요"
    elif today is None:
        status = "점검 전"
    else:
        status = "노출 중" if on_now else today["status"]
    shot = shots.get(n)
    outlets.append({
        "outlet": n,
        "articles_today": sum(1 for a in arts if a["date"] == latest_kit),
        "articles_month": sum(1 for a in arts if a["date"].startswith(month)),
        "articles_total": len(arts),
        "banner_status": status,
        "banner_pc": bool(today and today["pc"]),
        "banner_mobile": bool(today and today["mobile"]),
        "banner_since": per[-1]["start"] if on_now and per else None,
        "banner_last_seen": per[-1]["end"] if per else None,
        "banner_days_month": sum(1 for r in lg if r["date"].startswith(month) and r["status"] == "노출"),
        "shot": ("data:image/jpeg;base64," + base64.b64encode(Path(shot[2]).read_bytes()).decode()) if shot else None,
        "shot_date": shot[0] if shot else None,
        "shot_view": shot[1] if shot else None,
        "home": o.get("home", ""),
    })

daily = []
for day in sorted(set(article_days) | set(ad_days)):
    daily.append({"date": day,
                  "articles": sum(1 for a in articles if a["date"] == day),
                  "banners": sum(1 for r in log if r["date"] == day and r["status"] == "노출"),
                  "banner_checked": day in ad_days})

Path("media").mkdir(exist_ok=True)
for name, rows in (("outlets", outlets), ("articles", articles), ("banner_log", log), ("daily", daily)):
    Path(f"media/{name}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
print(f"media: 언론사 {len(outlets)}곳, 기사 {len(articles)}건({len(article_days)}일), "
      f"배너 점검 {len(ad_days)}일, 노출 중 {sum(o['banner_status'] == '노출 중' for o in outlets)}곳")
