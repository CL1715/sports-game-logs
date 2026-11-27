"""Record the site's own projections so their accuracy can be tracked.

Opens the built site in headless Chrome, asks the page for:
  * live projections for games starting in the next 30 hours (overwritten each hour until tip-off/kickoff), and
  * a back-test of the current season, re-run whenever the model version changes.
Results go to site/history_<league>.json. Grading against real box scores happens in the page.

Run after build_data.py and build_news.py:  python scripts/snapshot.py site
"""
import asyncio
import functools
import http.server
import json
import os
import shutil
import socketserver
import sys
import threading

from playwright.async_api import async_playwright

SITE = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "site")
PORT = 8765


def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), functools.partial(Quiet, directory=SITE))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def chrome_path():
    for c in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(c)
        if p:
            return p
    return None


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"v": None, "rows": []}


async def main():
    serve()
    async with async_playwright() as p:
        exe = chrome_path()
        browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        page = await browser.new_page()
        page.on("pageerror", lambda e: print("page error:", e))
        await page.goto(f"http://127.0.0.1:{PORT}/index.html#home-nba")
        await page.wait_for_function('typeof window.__glExport === "function"', timeout=60000)
        version = await page.evaluate("window.__glModelVersion")
        for lg in ("nba", "nfl"):
            path = os.path.join(SITE, f"history_{lg}.json")
            hist = load(path)
            rows = hist.get("rows", [])
            # back-test: recompute whenever the model changes (live rows are never rewritten)
            if hist.get("v") != version or not any(r[13] == 0 for r in rows):
                bt = await page.evaluate("([m, l]) => window.__glExport(m, l)", ["bt", lg])
                rows = [r for r in rows if r[13] != 0] + bt
                print(f"{lg}: back-test {len(bt)} rows (model {version})")
            live = await page.evaluate("([m, l]) => window.__glExport(m, l)", ["live", lg])
            # newest pre-game snapshot wins; games already started are never in `live`, so they stay frozen
            keyed = {(r[0], r[1], r[2], r[13]): r for r in rows}
            for r in live:
                r.append(version)  # remember which model made each live projection
                keyed[(r[0], r[1], r[2], 1)] = r
            rows = sorted(keyed.values(), key=lambda r: (r[0], r[1], r[2]))
            with open(path, "w") as f:
                json.dump({"v": version, "rows": rows}, f, separators=(",", ":"))
            print(f"{lg}: {len(live)} live projections saved, {len(rows)} rows total")
        await browser.close()


asyncio.run(main())
