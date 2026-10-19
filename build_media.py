"""관리 언론사 현황 페이지용 자료 만들기.

data/kit/*.json(언론사별 경남정보대 기사)와 data/ads/*.json(배너 점검)을 모아
media/status.json 과 media/shots/*.jpg(최근 배너 캡처)를 만든다.
"""
import json
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
cfg = json.loads(Path("managed_outlets.json").read_text(encoding="utf-8"))["outlets"]
names = [o["name"] for o in cfg]

kit_days = sorted(Path("data/kit").glob("????-??-??.json"))
ad_days = sorted(Path("data/ads").glob("????-??-??.json"))

articles = defaultdict(list)            # name -> [{date,title,url,published,in_title}]
article_days = []
for p in kit_days:
    d = json.loads(p.read_text(encoding="utf-8"))
    article_days.append(d["date"])
    for it in d["items"]:
        articles[it["outlet"]].append({"date": d["date"], "title": it["title"], "url": it["url"],
                                       "published": it["published"], "in_title": it.get("in_title", True)})

checks = defaultdict(dict)              # name -> date -> {pc, mobile, shot_pc, shot_mobile, error}
ad_dates = []
for p in ad_days:
    d = json.loads(p.read_text(encoding="utf-8"))
    ad_dates.append(d["date"])
    for r in d["results"]:
        if "pc" not in r and "mobile" not in r:
            continue
        c = {}
        for prof in ("pc", "mobile"):
            x = r.get(prof) or {}
            c[prof] = bool(x.get("found"))
            if x.get("shot"):
                c["shot_" + prof] = x["shot"]
            if x.get("error") and not x.get("found"):
                c.setdefault("error", x["error"][:80])
        checks[r["name"]][d["date"]] = c


def periods(by_date: dict):
    """점검한 날 기준 연속 노출 기간. 점검했는데 안 보인 날에 끊는다."""
    out, cur = [], None
    for day in sorted(by_date):
        c = by_date[day]
        seen = c.get("pc") or c.get("mobile")
        if seen:
            if cur is None:
                cur = {"start": day, "end": day, "pc": False, "mobile": False}
            cur["end"] = day
            cur["pc"] |= bool(c.get("pc"))
            cur["mobile"] |= bool(c.get("mobile"))
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    return out


latest_ad = ad_dates[-1] if ad_dates else None
latest_kit = article_days[-1] if article_days else None
month = (latest_kit or latest_ad or datetime.now(KST).strftime("%Y-%m-%d"))[:7]

Path("media/shots").mkdir(parents=True, exist_ok=True)
for f in Path("media/shots").glob("*.jpg"):
    f.unlink()

rows = []
for i, o in enumerate(cfg, 1):
    n = o["name"]
    arts = sorted(articles.get(n, []), key=lambda a: a["published"], reverse=True)
    ch = checks.get(n, {})
    per = periods(ch)
    today = ch.get(latest_ad, {}) if latest_ad else {}
    on_now = bool(today.get("pc") or today.get("mobile"))
    shot = None
    # 가장 최근에 배너가 잡힌 날의 캡처를 페이지용으로 복사
    for day in sorted(ch, reverse=True):
        c = ch[day]
        for prof in ("pc", "mobile"):
            src = c.get("shot_" + prof)
            if src and Path(src).exists():
                dst = f"media/shots/o{i:02d}_{prof}.jpg"
                shutil.copyfile(src, dst)
                shot = {"path": dst.removeprefix("media/"), "date": day, "profile": prof}
                break
        if shot:
            break
    rows.append({
        "name": n, "home": o.get("home", ""), "checkable": bool(o.get("home")),
        "articles_today": sum(1 for a in arts if a["date"] == latest_kit),
        "articles_month": sum(1 for a in arts if a["date"].startswith(month)),
        "articles_total": len(arts),
        "articles": arts[:40],
        "banner_today": {"pc": bool(today.get("pc")), "mobile": bool(today.get("mobile")),
                         "checked": bool(today), "error": today.get("error", "")},
        "banner_now": on_now,
        "banner_since": per[-1]["start"] if on_now and per else None,
        "banner_last_seen": per[-1]["end"] if per else None,
        "banner_days_month": sum(1 for d, c in ch.items() if d.startswith(month) and (c.get("pc") or c.get("mobile"))),
        "banner_periods": per[-10:],
        "shot": shot,
    })

daily = []
for day in sorted(set(article_days) | set(ad_dates))[-60:]:
    daily.append({"date": day,
                  "articles": sum(1 for n in names for a in articles.get(n, []) if a["date"] == day),
                  "banners": sum(1 for n in names if (checks.get(n, {}).get(day) or {}).get("pc")
                                 or (checks.get(n, {}).get(day) or {}).get("mobile"))})

out = {"updated_at": datetime.now(KST).isoformat(timespec="minutes"),
       "latest_article_date": latest_kit, "latest_check_date": latest_ad, "month": month,
       "tracking_since": {"articles": article_days[0] if article_days else None,
                          "banners": ad_dates[0] if ad_dates else None},
       "daily": daily, "outlets": rows}
Path("media/status.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"media/status.json: 언론사 {len(rows)}곳, 기사일 {len(article_days)}일, 점검일 {len(ad_dates)}일,"
      f" 배너 노출 중 {sum(r['banner_now'] for r in rows)}곳")
