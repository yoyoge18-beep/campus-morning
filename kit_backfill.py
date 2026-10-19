"""(한 번만) 지난 기간의 관리 언론사 경남정보대 기사(data/kit/<날짜>.json)를 네이버 검색으로 채운다.
이미 있는 날짜 파일은 건드리지 않는다. BACKFILL_FROM(기본 2026-10-01)부터 어제 판까지."""
import os
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

import collect

cid, secret = os.environ["NAVER_CLIENT_ID"], os.environ["NAVER_CLIENT_SECRET"]
H = {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": secret}
start_day = datetime.fromisoformat(os.environ.get("BACKFILL_FROM") or "2026-10-01").date()

items = {}
for q in collect.KEYWORDS[1]:
    for start in range(1, 1001, 100):
        r = requests.get("https://naverapihub.apigw.ntruss.com/search/v1/news", headers=H,
                         params={"query": q, "display": 100, "start": start, "sort": "date", "format": "json"},
                         timeout=20)
        if r.status_code != 200:
            print(q, start, r.status_code, r.text[:100])
            break
        got = r.json().get("items", [])
        old = False
        for it in got:
            pub = parsedate_to_datetime(it["pubDate"]).astimezone(collect.KST)
            if pub.date() < start_day - timedelta(days=1):
                old = True
                continue
            link = it.get("originallink") or it.get("link")
            items.setdefault(link, {"title": collect.clean(it.get("title")), "url": link,
                                    "domain": urlparse(link).netloc.replace("www.", ""),
                                    "published": pub.isoformat(), "via": "naver", "priority": 1})
        if old or len(got) < 100:
            break
        time.sleep(0.2)
print(f"네이버 기사 {len(items)}건")

end = collect.window_end(collect.NOW)
day_end = datetime.combine(start_day, datetime.min.time()).replace(hour=collect.CUTOFF_HOUR, tzinfo=collect.KST)
while day_end <= end:
    path = Path(f"data/kit/{day_end:%Y-%m-%d}.json")
    if not path.exists():
        collect.END, collect.SINCE = day_end, day_end - timedelta(hours=24)
        collect.save_managed_kit(items)
    day_end += timedelta(days=1)
