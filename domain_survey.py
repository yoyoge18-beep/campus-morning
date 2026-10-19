"""(시험용) 네이버 뉴스에서 '경남정보대' 기사를 최근 순으로 최대 1000건 받아 언론사 도메인별로 센다.
관리 언론사 도메인 확인용. 결과: data/probe/domains.json"""
import json, os, time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse
import requests

cid, secret = os.environ["NAVER_CLIENT_ID"], os.environ["NAVER_CLIENT_SECRET"]
H = {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": secret}
cnt, samples, oldest = Counter(), defaultdict(list), ""
for q in ("경남정보대", "경남정보대학교"):
    for start in range(1, 1001, 100):
        r = requests.get("https://naverapihub.apigw.ntruss.com/search/v1/news", headers=H,
                         params={"query": q, "display": 100, "start": start, "sort": "date", "format": "json"}, timeout=20)
        if r.status_code != 200:
            print(q, start, r.status_code, r.text[:100]); break
        items = r.json().get("items", [])
        for it in items:
            link = it.get("originallink") or it.get("link")
            d = urlparse(link).netloc.replace("www.", "")
            cnt[d] += 1
            if len(samples[d]) < 2:
                samples[d].append(it["title"][:50] + " | " + link)
            oldest = it.get("pubDate", oldest)
        if len(items) < 100: break
        time.sleep(0.2)
Path("data/probe").mkdir(parents=True, exist_ok=True)
out = {"oldest": oldest, "domains": [{"domain": d, "n": n, "samples": samples[d]} for d, n in cnt.most_common()]}
Path("data/probe/domains.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("oldest", oldest)
for d, n in cnt.most_common(80): print(n, d, samples[d][0][:60])
