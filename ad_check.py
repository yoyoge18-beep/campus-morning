"""관리 언론사 첫 화면에서 경남정보대 배너 광고 노출 여부를 점검한다.

- managed_outlets.json 의 home 주소를 PC·모바일 화면으로 연다(광고 순환을 고려해 최대 ATTEMPTS번 새로 열기).
- 모든 프레임(광고 iframe 포함)의 HTML·주소에서 경남정보대 링크(kit.ac.kr)를 찾는다.
  광고 클릭 주소 안에 인코딩된 주소(adurl=https%3A%2F%2Fwww.kit.ac.kr...)도 풀어서 본다.
- 찾으면 배너 부분을 캡처해 data/ads/shots/<날짜>/ 에 저장.
결과: data/ads/<YYYY-MM-DD>.json (KST 날짜)
"""
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

from playwright.async_api import async_playwright

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
DAY = NOW.strftime("%Y-%m-%d")
ATTEMPTS = int(os.environ.get("AD_ATTEMPTS", "3"))
CONCURRENCY = int(os.environ.get("AD_CONCURRENCY", "4"))
FULLSHOT = os.environ.get("AD_FULLSHOT") == "1"   # 시험용: 전체 화면 캡처(Actions 아티팩트)
ONLY = [s for s in os.environ.get("AD_ONLY", "").split(",") if s]

KIT_RE = re.compile(r"kit\.ac\.kr|경남정보대", re.I)
URL_RE = re.compile(r"kit\.ac\.kr", re.I)

PROFILES = {
    "pc": dict(viewport={"width": 1366, "height": 900},
               user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "mobile": dict(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2,
                   user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"),
}

# 프레임 안에서 경남정보대로 연결되는 요소(배너) 찾기
FIND_JS = r"""
() => {
  const dec = s => { try { return decodeURIComponent(decodeURIComponent(s)); } catch(e) { try { return decodeURIComponent(s); } catch(e2) { return s; } } };
  const out = [];
  const els = document.querySelectorAll('a[href], area[href], [onclick], img, iframe');
  for (const el of els) {
    const attrs = [el.getAttribute('href'), el.getAttribute('onclick'), el.getAttribute('src'),
                   el.getAttribute('alt'), el.getAttribute('title'), el.getAttribute('data-href')]
                  .filter(Boolean).map(dec).join(' ');
    if (!/kit\.ac\.kr/i.test(attrs) && !/경남정보대/.test(el.getAttribute('alt') || '')) continue;
    const r = el.getBoundingClientRect();
    const img = el.tagName === 'IMG' ? el : el.querySelector('img');
    out.push({tag: el.tagName, link: dec(el.getAttribute('href') || el.getAttribute('onclick') || '').slice(0, 300),
              img: img ? (img.currentSrc || img.src || '').slice(0, 300) : '',
              alt: img ? (img.alt || '').slice(0, 100) : '',
              w: Math.round(r.width), h: Math.round(r.height),
              x: Math.round(r.left + window.scrollX), y: Math.round(r.top + window.scrollY)});
  }
  return out;
}
"""


async def scan_page(page):
    hits = []
    for fr in page.frames:
        try:
            furl = unquote(unquote(fr.url or ""))
            els = await fr.evaluate(FIND_JS)
            for e in els:
                e["frame"] = furl[:200]
                hits.append(e)
            if not els and URL_RE.search(furl):
                hits.append({"tag": "FRAME", "link": furl[:300], "frame": furl[:200], "img": "", "alt": ""})
            if not els:
                html = unquote(unquote(await fr.content()))
                for m in URL_RE.finditer(html):
                    ctx = html[max(0, m.start() - 120): m.end() + 80]
                    # 기사 제목 속 '경남정보대' 텍스트는 제외하고 링크 주소만
                    hits.append({"tag": "HTML", "link": re.sub(r"\s+", " ", ctx)[:300], "frame": furl[:200], "img": "", "alt": ""})
                    break
        except Exception:
            continue
    return hits


async def check_one(browser, outlet, profile, shot_dir):
    res = {"found": False, "attempts": 0, "hits": [], "error": "", "final_url": "", "title": ""}
    for attempt in range(1, ATTEMPTS + 1):
        res["attempts"] = attempt
        ctx = await browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul", **PROFILES[profile])
        page = await ctx.new_page()
        try:
            await page.goto(outlet["home"], wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(5000)
            h = await page.evaluate("document.body ? document.body.scrollHeight : 0")
            for yy in range(0, min(h, 15000), 700):   # 지연 로딩 광고 불러오기
                await page.evaluate(f"window.scrollTo(0,{yy})")
                await page.wait_for_timeout(250)
            await page.evaluate("window.scrollTo(0,0)")
            await page.wait_for_timeout(3000)
            res["final_url"] = page.url
            res["title"] = (await page.title())[:80]
            hits = await scan_page(page)
            if FULLSHOT and attempt == 1:
                Path("probe_shots").mkdir(exist_ok=True)
                await page.screenshot(path=f"probe_shots/{outlet['name']}_{profile}.jpg", full_page=True, type="jpeg", quality=40)
            if hits:
                res["found"] = True
                res["hits"] = hits[:5]
                # 배너 캡처 (메인 프레임 요소 위치 기준, 실패하면 첫 화면)
                shot = shot_dir / f"{outlet['name']}_{profile}.jpg"
                shot_dir.mkdir(parents=True, exist_ok=True)
                try:
                    loc = None
                    for fr in page.frames:
                        cand = fr.locator('a[href*="kit.ac.kr"], img[alt*="경남정보"], a[href*="kit.ac.kr" i]')
                        if await cand.count():
                            loc = cand.first
                            break
                    if loc is not None:
                        await loc.scroll_into_view_if_needed(timeout=5000)
                        await loc.screenshot(path=str(shot), type="jpeg", quality=70, timeout=8000)
                    else:
                        await page.screenshot(path=str(shot), type="jpeg", quality=50)
                    res["shot"] = str(shot)
                except Exception as e:
                    res["shot_error"] = str(e)[:120]
                await ctx.close()
                break
        except Exception as e:
            res["error"] = str(e)[:200]
        await ctx.close()
    return res


async def main():
    cfg = json.loads(Path("managed_outlets.json").read_text(encoding="utf-8"))
    outlets = [o for o in cfg["outlets"] if o.get("home") and (not ONLY or o["name"] in ONLY)]
    shot_dir = Path("data/ads/shots") / DAY
    sem = asyncio.Semaphore(CONCURRENCY)
    results = {o["name"]: {"name": o["name"], "home": o["home"]} for o in cfg["outlets"]}
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])

        async def run(o, prof):
            async with sem:
                r = await check_one(browser, o, prof, shot_dir)
                results[o["name"]][prof] = r
                print(f"{o['name']:<8} {prof:<6} {'노출' if r['found'] else '-'} {r['error'][:60]}", file=sys.stderr)

        await asyncio.gather(*(run(o, prof) for o in outlets for prof in PROFILES))
        await browser.close()
    out = {"date": DAY, "checked_at": NOW.isoformat(), "attempts": ATTEMPTS,
           "results": list(results.values())}
    Path("data/ads").mkdir(parents=True, exist_ok=True)
    Path(f"data/ads/{DAY}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    Path("data/ads/latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(1 for r in results.values() if r.get("pc", {}).get("found") or r.get("mobile", {}).get("found"))
    print(f"{DAY}: 배너 확인 {n}곳 / 점검 {len(outlets)}곳")


if __name__ == "__main__":
    asyncio.run(main())
