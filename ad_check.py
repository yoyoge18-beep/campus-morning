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
from urllib.parse import unquote, urljoin, urlparse

from playwright.async_api import async_playwright

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
DAY = NOW.strftime("%Y-%m-%d")
ATTEMPTS = int(os.environ.get("AD_ATTEMPTS", "3"))
CONCURRENCY = int(os.environ.get("AD_CONCURRENCY", "6"))
ATTEMPT_TIMEOUT = 75  # 초. 한 번 열어 보는 데 이보다 오래 걸리면 포기
FULLSHOT = os.environ.get("AD_FULLSHOT") == "1"   # 시험용: 전체 화면 캡처(Actions 아티팩트)
ONLY = [s for s in os.environ.get("AD_ONLY", "").split(",") if s]

KIT_RE = re.compile(r"kit\.ac\.kr|경남정보대", re.I)
URL_RE = re.compile(r"kit\.ac\.kr", re.I)
# 광고 중간 페이지가 자바스크립트·meta 로 경남정보대에 보내는 경우
JSREDIR_RE = re.compile(r"(location(\.href)?\s*=|location\.(replace|assign)\(|http-equiv=[\"']?refresh[^>]*url=)[^<\n]{0,300}?kit\.ac\.kr", re.I)

PROFILES = {
    "pc": dict(viewport={"width": 1366, "height": 900},
               user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "mobile": dict(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2,
                   user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"),
}

# 프레임 안에서 (1) 경남정보대 주소로 바로 연결되는 요소, (2) 광고로 보이는 외부 링크 이미지 찾기
FIND_JS = r"""
(topHost) => {
  const dec = s => { try { return decodeURIComponent(decodeURIComponent(s)); } catch(e) { try { return decodeURIComponent(s); } catch(e2) { return s; } } };
  const kit = [], ads = [];
  const els = document.querySelectorAll('a[href], area[href], [onclick], iframe');
  for (const el of els) {
    const attrs = [el.getAttribute('href'), el.getAttribute('onclick'), el.getAttribute('src'),
                   el.getAttribute('data-href')].filter(Boolean).map(dec).join(' ');
    const img = el.querySelector('img');
    const ra = el.getBoundingClientRect(), ri = img ? img.getBoundingClientRect() : ra;
    const r = (ri.width * ri.height > ra.width * ra.height) ? ri : ra;
    const row = {tag: el.tagName, link: dec(el.getAttribute('href') || el.getAttribute('onclick') || el.getAttribute('src') || '').slice(0, 400),
                 img: img ? (img.currentSrc || img.src || '').slice(0, 300) : '',
                 alt: img ? (img.alt || '').slice(0, 100) : '',
                 w: Math.round(r.width), h: Math.round(r.height),
                 x: Math.round(r.left + window.scrollX), y: Math.round(r.top + window.scrollY)};
    if (/kit\.ac\.kr/i.test(attrs)) { kit.push(row); continue; }
    // 광고 후보: 이미지가 든 바깥 링크(언론사 자체 주소가 아닌 것), 일정 크기 이상
    // 슬라이드처럼 지금 안 보이는 광고도 잡도록 이미지 원본 크기로 판단
    if (el.tagName === 'A' && img && Math.max(row.w, img.naturalWidth || 0) >= 80 && Math.max(row.h, img.naturalHeight || 0) >= 40) {
      let host = '';
      try { host = new URL(el.href, location.href).hostname; } catch(e) {}
      const base = (topHost || '').split('.').slice(-2).join('.');
      const own = base && (host === topHost || host.endsWith('.' + base) || host === base);
      const social = /(facebook|twitter|instagram|youtube|kakao|naver\.com|apple\.com|play\.google)/i.test(host);
      if (host && !own && !social) ads.push({...row, href: el.href, host});
    }
  }
  return {kit, ads};
}
"""


async def scan_page(page):
    """경남정보대 직접 링크(hits)와 광고 후보(ads)를 모든 프레임에서 모은다."""
    hits, ads = [], []
    top = urlparse(page.url).hostname or ""
    for fr in page.frames:
        try:
            furl = unquote(unquote(fr.url or ""))
            got = await asyncio.wait_for(fr.evaluate(FIND_JS, top), 10)
            for e in got["kit"]:
                e["frame"] = furl[:200]
                hits.append(e)
            for e in got["ads"]:
                e["frame"] = furl[:200]
                ads.append(e)
            if not got["kit"] and fr != page.main_frame and URL_RE.search(furl):
                hits.append({"tag": "FRAME", "link": furl[:300], "frame": furl[:200], "img": "", "alt": ""})
        except Exception:
            continue
    return hits, ads


async def resolve_ads(ctx, ads, limit=24):
    """광고 클릭 주소를 실제로 따라가 최종 도착 주소를 확인(경남정보대로 가는지). 동시에 따라간다."""
    seen, todo = set(), []
    for a in ads:
        href = a.get("href", "")
        if href.startswith("http") and href not in seen and len(todo) < limit:
            seen.add(href)
            todo.append(a)
    sem = asyncio.Semaphore(8)

    async def one(a):
        async with sem:
            await follow(ctx, a)
        return a

    return list(await asyncio.gather(*(one(a) for a in todo)))


async def follow(ctx, a):
    final, kit, url = "", False, a["href"]
    try:
        # 이동 단계를 하나씩 따라가며 주소에 kit.ac.kr 가 나오는지 확인
        for _ in range(8):
            if URL_RE.search(unquote(unquote(url))):
                kit = True
                break
            resp = await asyncio.wait_for(ctx.request.get(url, max_redirects=0, timeout=6000), 8)
            loc = resp.headers.get("location")
            if 300 <= resp.status < 400 and loc:
                url = urljoin(url, loc)
                continue
            if resp.ok:
                body = (await asyncio.wait_for(resp.text(), 5))[:30000]
                kit = bool(JSREDIR_RE.search(unquote(body)))   # 자바스크립트·meta 방식 이동
            break
        final = url
    except Exception as e:
        final = url + " ERR " + str(e)[:60]
    a["final"] = final[:200]
    a["kit"] = kit


async def check_one(browser, outlet, profile, shot_dir):
    res = {"found": False, "attempts": 0, "hits": [], "error": "", "final_url": "", "title": ""}
    for attempt in range(1, ATTEMPTS + 1):
        res["attempts"] = attempt
        ctx = await browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul", **PROFILES[profile])
        ctx.set_default_timeout(15000)
        try:
            done = await asyncio.wait_for(one_attempt(ctx, outlet, profile, shot_dir, attempt, res), ATTEMPT_TIMEOUT)
        except asyncio.TimeoutError:
            res["error"] = "시간 초과"
            done = False
        except Exception as e:
            res["error"] = str(e)[:200]
            done = False
        try:
            await asyncio.wait_for(ctx.close(), 15)
        except Exception:
            pass
        if done:
            break
    return res


async def one_attempt(ctx, outlet, profile, shot_dir, attempt, res):
    page = await ctx.new_page()
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
    hits, ads = await scan_page(page)
    if FULLSHOT and attempt == 1:
        Path("probe_shots").mkdir(exist_ok=True)
        vh = PROFILES[profile]["viewport"]["height"]
        for k in range(3):   # 첫 화면부터 세 화면 분량
            await page.evaluate(f"window.scrollTo(0,{k * vh})")
            await page.wait_for_timeout(800)
            await page.screenshot(path=f"probe_shots/{outlet['name']}_{profile}_{k}.jpg", type="jpeg", quality=45)
        await page.evaluate("window.scrollTo(0,0)")
    if not hits and ads:
        checked = await resolve_ads(ctx, ads)
        res["ads"] = [{k: a.get(k) for k in ("host", "img", "final", "kit", "w", "h")} for a in checked][:30]
        for a in checked:
            if a["kit"]:
                a["tag"] = "AD>KIT"
                a["link"] = a.get("href", "")[:300] + " -> " + a.get("final", "")
                hits.append(a)
    elif ads:
        res["ads"] = [{k: a.get(k) for k in ("host", "img", "w", "h")} for a in ads][:30]
    if hits:
        res["found"] = True
        res["hits"] = hits[:5]
        # 배너 캡처 (메인 프레임 요소 위치 기준, 실패하면 첫 화면)
        shot = shot_dir / f"{outlet['name']}_{profile}.jpg"
        shot_dir.mkdir(parents=True, exist_ok=True)
        try:
            loc = None
            for fr in page.frames:
                sel = 'a[href*="kit.ac.kr" i]'
                for h_ in hits:
                    if h_.get("href"):
                        sel += ', a[href="' + h_["href"].replace('"', '\\"') + '"]'
                cand = fr.locator(sel)
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
            # 슬라이드 등으로 지금 안 보이는 배너: 배너 이미지 파일 자체를 저장
            src = next((h_.get("img") for h_ in hits if str(h_.get("img", "")).startswith("http")), "")
            if src:
                try:
                    r = await asyncio.wait_for(page.context.request.get(src, timeout=8000), 10)
                    body = await r.body()
                    if r.ok and 0 < len(body) < 400_000:
                        img_path = shot.with_suffix(".img")
                        img_path.write_bytes(body)
                        res["shot"] = str(img_path)
                except Exception as e2:
                    res["shot_error"] += " / " + str(e2)[:60]
        res["error"] = ""
        return True
    return False


def save(results):
    """점검이 끝날 때마다 저장(중간에 멈춰도 결과가 남도록)."""
    out = {"date": DAY, "checked_at": NOW.isoformat(), "attempts": ATTEMPTS,
           "results": list(results.values())}
    Path("data/ads").mkdir(parents=True, exist_ok=True)
    txt = json.dumps(out, ensure_ascii=False, indent=1)
    Path(f"data/ads/{DAY}.json").write_text(txt, encoding="utf-8")
    Path("data/ads/latest.json").write_text(txt, encoding="utf-8")


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
                save(results)
                print(f"{o['name']:<8} {prof:<6} {'노출' if r['found'] else '-'} {r['error'][:60]}", file=sys.stderr)

        await asyncio.gather(*(run(o, prof) for o in outlets for prof in PROFILES))
        await browser.close()
    save(results)
    n = sum(1 for r in results.values() if r.get("pc", {}).get("found") or r.get("mobile", {}).get("found"))
    print(f"{DAY}: 배너 확인 {n}곳 / 점검 {len(outlets)}곳")


if __name__ == "__main__":
    asyncio.run(main())
