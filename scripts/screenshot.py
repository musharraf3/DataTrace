"""Capture README screenshots of the running app with headless Chrome (DevTools protocol, no extra installs).

Usage: python scripts/screenshot.py  (app must be running on http://localhost:8501)
"""

import asyncio
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9333
BASE = "http://localhost:8501/"
SHOTS = [
    ("verdict.png", "?incident=eligibility_spans&mode=recorded&autorun=1&fast=1", None, 1150),
    ("verdict_retail.png", "?incident=crm_migration&mode=recorded&autorun=1&fast=1", None, 1150),
    ("timeline.png", "?incident=eligibility_spans&mode=recorded&autorun=1&fast=1", "Agent timeline", 1400),
    ("benchmark.png", "", "Agent vs. baseline benchmark", 1100),
    ("clarification.png", "?incident=reversal_policy&mode=recorded&autorun=1&fast=1", None, 900),
]


async def call(ws, counter, method, **params):
    counter[0] += 1
    await ws.send(json.dumps({"id": counter[0], "method": method, "params": params}))
    while True:
        message = json.loads(await ws.recv())
        if message.get("id") == counter[0]:
            return message.get("result", {})


async def shoot(ws_url, name, query, tab, height):
    counter = [0]
    async with websockets.connect(ws_url, max_size=50_000_000) as ws:
        await call(ws, counter, "Emulation.setDeviceMetricsOverride", width=1440, height=height,
                   deviceScaleFactor=1, mobile=False)
        await call(ws, counter, "Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
        await call(ws, counter, "Page.navigate", url=BASE + query)
        await asyncio.sleep(14)
        if tab:
            script = ("(() => { const t = [...document.querySelectorAll('[role=tab]')].find(b => b.innerText.includes(%s));"
                      " if (t) { t.click(); t.scrollIntoView({block: 'start'}); } })()" % json.dumps(tab))
            await call(ws, counter, "Runtime.evaluate", expression=script)
            await asyncio.sleep(3)
        if name in {"verdict.png", "verdict_retail.png", "clarification.png"}:  # Frame the result, not the hero.
            await call(ws, counter, "Runtime.evaluate", expression=(
                "document.querySelector('.verdict')?.scrollIntoView({block:'start'})"))
            await asyncio.sleep(1)
        shot = await call(ws, counter, "Page.captureScreenshot", format="png")
        (ROOT / "docs" / "screenshots" / name).write_bytes(base64.b64decode(shot["data"]))
        print("saved", name)


def main():
    (ROOT / "docs" / "screenshots").mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="dt-cdp-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}", "--no-first-run",
                               "--hide-scrollbars", f"--user-data-dir={profile}", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2).read())
                ws_url = next(p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page")
                break
            except Exception:
                time.sleep(0.5)
        else:
            sys.exit("Chrome DevTools did not start.")
        for name, query, tab, height in SHOTS:
            asyncio.run(shoot(ws_url, name, query, tab, height))
    finally:
        chrome.terminate()


if __name__ == "__main__":
    main()
