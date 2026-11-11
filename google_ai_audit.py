"""
google_ai_audit.py - skeleton for a personalization audit of Google AI Overviews / AI Mode.

Design: logged-in Google accounts (one Chrome profile each), seeded with partisan
search + click activity, then queried in lockstep. >=2 accounts per condition so
within-condition differences give you the noise floor (A/B tests, randomness).

Usage
  python google_ai_audit.py login  acc_left_1   # opens real Chrome on that profile; log in by hand,
                                                # turn Web & App Activity ON, close Chrome
  python google_ai_audit.py seed   acc_left_1   # run partisan seeding for one account
  python google_ai_audit.py collect             # all accounts, same queries, same time

Requires: pip install playwright && playwright install chrome
Selectors ("AI Overview", "Show more", the "AI Mode" tab, the "AI Mode reply for" heading) change often:
verify them in the pilot. Parse saved AI Mode pages with parse_aimode.py.
Always keep raw HTML + screenshots; parse offline later (answers are not reproducible).
"""
import asyncio, hashlib, json, random, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from playwright.async_api import async_playwright

ROOT = Path("audit")
PROFILES = ROOT / "profiles"
OUT = ROOT / "raw"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"  # linux: "google-chrome"
LOCALE = "&hl=en&gl=us"  # fix language/country for every account

ACCOUNTS = {
    "acc_left_1": "left",  "acc_left_2": "left",
    "acc_right_1": "right", "acc_right_2": "right",
    "acc_bal_1": "balanced", "acc_bal_2": "balanced",
    "acc_none_1": "none",  "acc_none_2": "none",   # logged in, never seeded
}

# placeholders: replace with matched seed lists (same count, similar popularity)
LEFT = {"queries": ["..."], "domains": ["msnbc.com", "theguardian.com", "huffpost.com"]}
RIGHT = {"queries": ["..."], "domains": ["foxnews.com", "breitbart.com", "dailywire.com"]}
SEED = {
    "left": LEFT,
    "right": RIGHT,
    "balanced": {"queries": LEFT["queries"] + RIGHT["queries"],
                 "domains": LEFT["domains"] + RIGHT["domains"]},
    "none": None,
}
TEST_QUERIES = ["..."]  # identical political questions; pilot AIO activation first


def qid(q):
    return hashlib.md5(q.encode()).hexdigest()[:10]


async def open_ctx(p, acc):
    return await p.chromium.launch_persistent_context(
        str(PROFILES / acc), channel="chrome", headless=False,
        viewport={"width": 1366, "height": 900}, locale="en-US")


async def pause(a, b):
    await asyncio.sleep(random.uniform(a, b))


async def search(page, q, udm=None):
    url = f"https://www.google.com/search?q={quote_plus(q)}{LOCALE}"
    if udm:
        url += f"&udm={udm}"  # udm=50 = AI Mode (verify)
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_load_state("networkidle")
    if "/sorry/" in page.url:  # captcha page: log and skip, do not bypass
        raise RuntimeError("captcha")


def login(acc):
    # plain Chrome, not Playwright: Google often refuses sign-in from automated browsers
    d = PROFILES / acc
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run([CHROME, f"--user-data-dir={d.resolve()}", "https://accounts.google.com"])


async def seed(acc):
    s = SEED[ACCOUNTS[acc]]
    if not s:
        return
    async with async_playwright() as p:
        ctx = await open_ctx(p, acc)
        page = await ctx.new_page()
        for q in s["queries"]:
            await search(page, q)
            links = page.locator("a:has(h3)")
            for i in range(await links.count()):
                href = await links.nth(i).get_attribute("href") or ""
                if any(urlparse(href).netloc.endswith(d) for d in s["domains"]):
                    await links.nth(i).click()
                    await pause(30, 90)  # dwell on article
                    break
            await pause(10, 30)
        await ctx.close()


async def save(page, acc, q, mode, ts):
    stem = OUT / mode / f"{qid(q)}_{acc}_{ts}"
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".html").write_text(await page.content())
    await page.screenshot(path=str(stem.with_suffix(".png")), full_page=True)


async def wait_stable(page, selector, timeout=90, quiet=4):
    """wait until the element exists and its text stops changing (answer finished streaming)."""
    el = page.locator(selector).first
    await el.wait_for(timeout=timeout * 1000)
    last, still, t = "", 0, 0
    while t < timeout:
        txt = await el.inner_text()
        still = still + 1 if txt == last else 0
        if still >= quiet:
            return
        last = txt
        await asyncio.sleep(1)
        t += 1


AIM_ROOT = "xpath=//h3[starts-with(normalize-space(.), 'AI Mode reply for')]/.."


async def capture(ctx, acc, q):
    """one normal search (AI Overview), then the AI Mode tab, like a user would."""
    page = await ctx.new_page()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    meta = {"account": acc, "condition": ACCOUNTS[acc], "query": q, "ts": ts}
    try:
        await search(page, q)
        meta["aio_present"] = await page.get_by_text("AI Overview", exact=True).count() > 0
        more = page.get_by_role("button", name="Show more")  # pilot: check it expands the AIO, not PAA
        if meta["aio_present"] and await more.count():
            await more.first.click()
            await asyncio.sleep(2)
        await save(page, acc, q, "aio", ts)

        tab = page.get_by_role("link", name="AI Mode", exact=True)
        if await tab.count():
            await tab.first.click()
        else:  # tab missing: fall back to the direct URL
            meta["aimode_via"] = "udm50"
            await search(page, q, udm=50)
        await wait_stable(page, AIM_ROOT)
        await save(page, acc, q, "aimode", ts)
    except Exception as e:
        meta["error"] = str(e)
    finally:
        (OUT / "log.jsonl").parent.mkdir(parents=True, exist_ok=True)
        with open(OUT / "log.jsonl", "a") as f:
            f.write(json.dumps(meta) + "\n")
        await page.close()


async def collect():
    async with async_playwright() as p:
        ctxs = {a: await open_ctx(p, a) for a in ACCOUNTS}
        for q in TEST_QUERIES:
            # lockstep: every account sends the same query at the same moment
            await asyncio.gather(*(capture(ctxs[a], a, q) for a in ACCOUNTS))
            await pause(20, 40)
        for c in ctxs.values():
            await c.close()


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "login":
        login(sys.argv[2])
    elif cmd == "seed":
        asyncio.run(seed(sys.argv[2]))
    elif cmd == "collect":
        asyncio.run(collect())
