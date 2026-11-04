"""Build the narrated demo video (1920x1080 MP4) by driving the running app with headless Chrome.

Everything on screen is the real app at http://localhost:8501 (python run.py). The voice-note intake, the claims
investigation and the clarification are LIVE Meta API calls (about $0.30 per build). Model waiting time is trimmed
or sped up, and the video says so on screen. Pass --recorded to replay the committed recorded runs instead (no cost).

Narration uses a neural voice through edge-tts when it is installed (pip install edge-tts), otherwise Windows
speech. Every number in the narration is read from the committed recording and benchmark results, and the script
checks that the live run shows the same dollars before it writes the video.

Usage: python scripts/make_demo_video.py [--recorded]
Output: docs/video/datatrace-demo.mp4 and docs/demo_captions.srt
"""

import argparse
import asyncio
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "video"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
APP = "http://localhost:8501/"
PORT = 9334
W, H, SCALE = 1440, 810, 4 / 3        # CSS viewport; frames come out at 1920x1080
FW, FH = 1920, 1080
VOICE, RATE = "en-US-AndrewMultilingualNeural", "+6%"
LEAD, TAIL = 0.35, 0.6                # silence before and after each scene's narration
RATE_HZ = 24000
MAX_SECONDS = 179.0


# ---------------------------------------------------------------- narration

def _millions(cents):
    return "$" + f"{abs(cents) / 100 / 1_000_000:.2f}".rstrip("0").rstrip(".") + " million"


def facts():
    rec = json.loads((ROOT / "examples/recorded/synpuf-eligibility_spans.json").read_text(encoding="utf-8"))["report"]
    r = rec["reconciliation"]
    bench = json.loads((ROOT / "results/benchmark.json").read_text(encoding="utf-8"))
    reviewer = json.loads((ROOT / "results/reviewer_eval.json").read_text(encoding="utf-8"))
    rows = bench["table"]
    agent = lambda row: row["System"].startswith("DataTrace")
    claims = {agent(row): row for row in rows if row["Split"].startswith("Healthcare")}
    scale = {agent(row): row for row in rows if row["Split"].startswith("Warehouse")}
    frac = lambda text: tuple(int(x) for x in text.split("/"))
    return {
        "moved": rec["replay"][3]["revenue_cents"] - rec["replay"][0]["revenue_cents"],
        "real": r["underlying_change_cents"], "error": r["current_error_cents"], "claims": r["affected_order_count"],
        "corrected": r["current_expected_cents"],
        "runs": sum(frac(row["Correct diagnosis"])[1] for row in rows),
        "agent_ok": sum(frac(row["Correct diagnosis"])[0] for row in rows if agent(row)),
        "agent_n": sum(frac(row["Correct diagnosis"])[1] for row in rows if agent(row)),
        "base_ok": sum(frac(row["Correct diagnosis"])[0] for row in rows if not agent(row)),
        "claims_agent": frac(claims[True]["Dollar split correct"]), "claims_base": frac(claims[False]["Dollar split correct"]),
        "scale_agent": frac(scale[True]["Correct diagnosis"]), "scale_base": frac(scale[False]["Correct diagnosis"]),
        "planted": (reviewer["planted_caught"], reviewer["planted_total"]),
    }


@dataclass
class Scene:
    name: str
    chapter: str
    text: str
    audio: Path = None
    duration: float = 0.0                     # narration length in seconds
    sentences: list = field(default_factory=list)  # (offset, duration, text) from the voice engine
    pieces: list = field(default_factory=list)     # (real_start, real_end, speed) kept from the recording

    @property
    def length(self):
        return LEAD + self.duration + TAIL

    def cue(self, fragment):
        """Seconds into the scene at which `fragment` is spoken (estimated within its sentence)."""
        for offset, span, sentence in self.sentences:
            at = sentence.find(fragment)
            if at >= 0:
                return LEAD + offset + span * at / max(1, len(sentence))
        at = self.text.find(fragment)
        return LEAD + self.duration * max(0, at) / max(1, len(self.text))


def script(f, recorded):
    live = "Replay of a captured Meta run" if recorded else "Live"
    ca, cb = f["claims_agent"], f["claims_base"]
    return [
        Scene("dashboard", "",
              "It's 8 a.m. The monthly cost review is at 10, and paid inpatient claims for November just jumped 40% "
              "overnight. Some claims run-out is normal. So is this jump real, or is the dashboard wrong?"),
        Scene("hero", "DataTrace",
              "In healthcare finance, that question lands on an analyst's desk every month, and a wrong answer moves "
              "budgets and reserves. DataTrace is a Meta agent that answers it with evidence, not guesses."),
        Scene("intake", "Intake  ·  Muse Voice Transcribe + Muse Spark vision",
              "It starts from what the actuary sent: a voice note and a dashboard screenshot. Muse Voice Transcribe "
              "turns the note into text, and Muse Spark reads both and drafts the metric definition: paid claims, "
              "November service month, net of reversals."),
        Scene("investigate", f"{live} investigation  ·  Muse Spark agent  ·  sandboxed SQL",
              "Now Muse Spark investigates real-format CMS Medicare claims, and it never sees a raw row. Each step is a "
              "hypothesis, tested with bounded, read-only SQL: duplicate eligibility rows, members dropped by a join, "
              "date boundaries, pending claims, reversals. It proposes a corrected query, an independent verifier "
              "checks it claim by claim, and a second Meta model, Muse Wonder, reviews the diagnosis."),
        Scene("verdict", "Verdict  ·  verified fix  ·  reviewed by Muse Wonder",
              f"Here's the verdict. Of a {_millions(f['moved'])} jump, {_millions(f['real'])} is genuine claims "
              f"run-out. ${f['error'] / 100:,.0f} is a reporting error, across {f['claims']} claims. The eligibility "
              f"rebuild gave members who switched coverage two rows, double counting their claims, and dropped "
              f"deceased members. The corrected query is verified, and Muse Wonder writes the brief for the cost review."),
        Scene("clarify", "It asks instead of guessing  ·  request_clarification",
              "When the definition is missing, it doesn't guess. This request never said how reversals count, so the "
              "agent pauses and asks. The analyst answers: net paid. The same investigation resumes where it stopped, "
              "verifies its fix, and is reviewed again."),
        Scene("benchmark", f"Measured  ·  {f['runs']} paid runs against the same model given raw rows",
              f"We ran {f['runs']} paid runs against the same Meta model given every raw "
              f"row and no tools. On CMS claims, the baseline usually named the right problem, but put the right "
              f"dollars on it in only {cb[0]} of {cb[1]} runs. The agent: {ca[0]} of {ca[1]}. At 42,000 rows, the raw "
              f"data doesn't even fit in the context window."),
        Scene("reviewer", "Reviewer stress test  ·  Muse Wonder",
              f"We also stress-tested the reviewer by planting errors in correct diagnoses: inflated amounts, invented "
              f"causes, unverified fixes. Muse Wonder caught {f['planted'][0]} of {f['planted'][1]}."),
        Scene("architecture", "",
              "Four Meta model roles, around a sandboxed SQL engine and a verifier the model can't fool. The same "
              "engine also runs retail revenue, and an adapter runs it on open-weight models."),
        Scene("end", "",
              "DataTrace. Evidence before explanations. Built during the hackathon, and open source on GitHub."),
    ]


# ---------------------------------------------------------------- voice

def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _to_wav(source, target):
    subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-i", str(source), "-ac", "1", "-ar", str(RATE_HZ),
                    "-sample_fmt", "s16", str(target)], check=True)
    with wave.open(str(target)) as handle:
        return handle.getnframes() / handle.getframerate()


def speak(scene, work):
    """Synthesize one scene; fills scene.audio, scene.duration and scene.sentences."""
    target = work / f"{scene.name}.wav"
    try:
        import edge_tts

        async def run():
            sentences = []
            communicate = edge_tts.Communicate(scene.text, VOICE, rate=RATE, boundary="SentenceBoundary")
            with (work / f"{scene.name}.mp3").open("wb") as handle:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        handle.write(chunk["data"])
                    elif chunk["type"] == "SentenceBoundary":
                        sentences.append((chunk["offset"] / 1e7, chunk["duration"] / 1e7, chunk["text"]))
            return sentences

        for attempt in range(4):
            try:
                scene.sentences = asyncio.run(run())
                break
            except edge_tts.exceptions.NoAudioReceived:  # The service occasionally drops a request.
                if attempt == 3:
                    raise
                time.sleep(2 + attempt * 2)
        scene.duration = _to_wav(work / f"{scene.name}.mp3", target)
    except ImportError:
        say = work / "say.ps1"
        (work / "text.txt").write_text(scene.text, encoding="utf-8")
        say.write_text(
            "Add-Type -AssemblyName System.Speech\n$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n$s.Rate = 1\n"
            f"$s.SetOutputToWaveFile('{work / 'sapi.wav'}')\n$s.Speak([IO.File]::ReadAllText('{work / 'text.txt'}'))\n"
            "$s.Dispose()\n", encoding="utf-8")
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(say)], check=True)
        scene.duration = _to_wav(work / "sapi.wav", target)
        scene.sentences = [(0.0, scene.duration, scene.text)]
    scene.audio = target


# ---------------------------------------------------------------- browser

FPS_ROLLING, FPS_IDLE = 15, 2


class CDP:
    def __init__(self, ws):
        self.ws, self.counter, self.pending, self.frames, self.rolling = ws, 0, {}, [], False

    async def reader(self, frame_dir=None):
        async for raw in self.ws:
            message = json.loads(raw)
            if "id" in message and message["id"] in self.pending:
                self.pending.pop(message["id"]).set_result(message.get("result", {}))

    async def capture(self, frame_dir):
        """Screenshot the page at a fixed rate; each frame is stamped with the time it was requested.

        (Page.startScreencast queues frames faster than they can be delivered at 1080p, so the picture
        drifts seconds behind the narration; direct screenshots cannot drift.)"""
        while True:
            began = time.time()
            try:
                result = await self.send("Page.captureScreenshot", format="jpeg", quality=86, optimizeForSpeed=True)
                path = frame_dir / f"f{len(self.frames):06d}.jpg"
                path.write_bytes(base64.b64decode(result["data"]))
                self.frames.append((began, path))
            except (asyncio.TimeoutError, KeyError):
                pass
            rate = FPS_ROLLING if self.rolling else FPS_IDLE
            await asyncio.sleep(max(0.0, 1 / rate - (time.time() - began)))

    async def send(self, method, **params):
        self.counter += 1
        future = asyncio.get_event_loop().create_future()
        self.pending[self.counter] = future
        await self.ws.send(json.dumps({"id": self.counter, "method": method, "params": params}))
        return await asyncio.wait_for(future, 60)

    async def js(self, expression):
        result = await self.send("Runtime.evaluate", expression=expression, awaitPromise=True)
        return result.get("result", {}).get("value")


CLICK = """(t => { const el = [...document.querySelectorAll('button, [role=tab], summary, label, p')]
  .find(e => e.innerText && e.innerText.trim().startsWith(t)); if (!el) return false;
  const r = el.getBoundingClientRect(); if (r.top < 70 || r.bottom > innerHeight - 20) el.scrollIntoView({block:'center'});
  const box = el.closest('label') && el.closest('label').querySelector('input[type=checkbox]');
  (box || el).click(); return true })(%s)"""
SCROLL = """((sel, text, how, margin) => { const el = [...document.querySelectorAll(sel)]
  .find(e => !text || (e.innerText && e.innerText.trim().startsWith(text))); if (!el) return false;
  el.style.scrollMarginTop = margin + 'px'; el.scrollIntoView({behavior: how, block: 'start'}); return true })(%s, %s, %s, %d)"""
COLLAPSE = """(() => { const side = document.querySelector('[data-testid=stSidebar]');
  const button = document.querySelector('[data-testid=stSidebarCollapseButton] button');
  if (side && side.getBoundingClientRect().width > 60 && button) { button.click(); return true } return false })()"""
FOLLOW = """(() => { const box = [...document.querySelectorAll('[data-testid=stExpanderDetails]')].pop();
  const items = box ? box.querySelectorAll('[data-testid=stMarkdownContainer], [data-testid=stCode], [data-testid=stDataFrame]') : [];
  const last = items[items.length - 1]; if (last) last.scrollIntoView({block: 'end', behavior: 'smooth'}); })()"""


async def wait_for(cdp, text, seconds=60):
    for _ in range(int(seconds * 2)):
        if await cdp.js(f"document.body.innerText.includes({json.dumps(text)})"):
            return True
        await asyncio.sleep(0.5)
    return False


async def scroll_to(cdp, selector, smooth=False, above=80):
    how = json.dumps("smooth" if smooth else "instant")
    return await cdp.js(SCROLL % (json.dumps(selector), "null", how, above))


async def scroll_text(cdp, text, smooth=False, above=80):
    how = json.dumps("smooth" if smooth else "instant")
    return await cdp.js(SCROLL % (json.dumps("h1, h2, h3, p, strong, summary, [role=tab]"), json.dumps(text), how, above))


async def goto(cdp, url, ready=None):
    await cdp.send("Page.navigate", url=url)
    if ready:
        await wait_for(cdp, ready)
    await asyncio.sleep(1.5)


async def open_app(cdp, query, ready="Is the jump real"):
    await goto(cdp, APP + query, ready)
    for _ in range(6):
        if not await cdp.js(COLLAPSE):
            break
        await asyncio.sleep(0.8)
    await asyncio.sleep(0.6)


def _page(body, extra_css=""):
    html = f"""<html><head><meta charset="utf-8"><style>
      html,body{{margin:0;height:100%;overflow:hidden;font-family:'Segoe UI',system-ui,sans-serif;
        background:radial-gradient(1200px 700px at 20% 10%,#1d3a8a 0%,#0b1736 55%,#070f25 100%);color:#fff}}
      .wrap{{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center}}
      {extra_css}</style></head><body>{body}</body></html>"""
    return "data:text/html;base64," + base64.b64encode(html.encode("utf-8")).decode()


def dashboard_page():
    image = base64.b64encode((ROOT / "examples/claims_dashboard_screenshot.png").read_bytes()).decode()
    css = """.shot{width:84%;border-radius:14px;box-shadow:0 24px 70px rgba(0,0,0,.55);transform-origin:18% 22%;
               transition:transform 15s ease-out} .go .shot{transform:scale(1.13)}
             .tag{position:absolute;top:34px;left:44px;font-size:22px;letter-spacing:.14em;font-weight:700;color:#a9bdf5}"""
    return _page(f"<div class='wrap' id='w'><img class='shot' src='data:image/png;base64,{image}'></div>"
                 "<div class='tag'>8:02 AM · NOVEMBER CLAIMS DASHBOARD AFTER THE OVERNIGHT REFRESH</div>", css)


def architecture_page():
    svg = (ROOT / "docs/architecture.svg").read_text(encoding="utf-8")
    css = """.card{width:86%;background:#fff;border-radius:18px;box-shadow:0 24px 70px rgba(0,0,0,.5);padding:10px;
               transition:transform 14s ease-out} .go .card{transform:scale(1.04)} .card svg{width:100%;height:auto;display:block}
             .kick{font-size:20px;letter-spacing:.16em;font-weight:700;color:#a9bdf5;margin-bottom:22px}"""
    return _page(f"<div class='wrap' id='w'><div class='kick'>HOW IT WORKS</div><div class='card'>{svg}</div></div>", css)


def end_page(f):
    ca, cb, sa, sb, pl = f["claims_agent"], f["claims_base"], f["scale_agent"], f["scale_base"], f["planted"]
    css = """h1{font-size:96px;margin:0;font-weight:800;letter-spacing:-.02em} .sub{font-size:34px;color:#c7d4fb;margin:6px 0 46px}
             .stats{display:flex;gap:26px} .stat{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.18);
               border-radius:18px;padding:26px 30px;width:330px} .big{font-size:54px;font-weight:800;color:#fff}
             .vs{font-size:26px;color:#9fb2ea;font-weight:600} .lbl{font-size:21px;color:#d5defa;margin-top:8px;line-height:1.35}
             .models{margin-top:46px;font-size:22px;color:#c7d4fb} code{background:rgba(255,255,255,.12);padding:3px 9px;
               border-radius:7px;font-family:Consolas,monospace;font-size:20px;color:#fff}
             .repo{margin-top:26px;font-size:32px;font-weight:700} .foot{margin-top:14px;font-size:19px;color:#8ea2dc}
             .wrap{opacity:0;transform:translateY(14px);transition:all 1s ease-out} .go .wrap,.go.wrap{opacity:1;transform:none}"""
    body = f"""<div class='wrap' id='w'><h1>DataTrace</h1><div class='sub'>Evidence before explanations.</div>
      <div class='stats'>
        <div class='stat'><div class='big'>{ca[0]}/{ca[1]} <span class='vs'>vs {cb[0]}/{cb[1]}</span></div>
          <div class='lbl'>right dollar split on CMS claims, agent vs. the same model reading every raw row</div></div>
        <div class='stat'><div class='big'>{pl[0]}/{pl[1]}</div>
          <div class='lbl'>planted errors caught by the Muse Wonder reviewer</div></div>
        <div class='stat'><div class='big'>{sa[0]}/{sa[1]} <span class='vs'>vs {sb[0]}/{sb[1]}</span></div>
          <div class='lbl'>at 42,000 rows, where raw rows no longer fit in the context window</div></div>
      </div>
      <div class='models'>Built on <code>muse-spark-1.3</code> · <code>muse-wonder-1.0</code> · <code>muse-voice-transcribe-1.0</code></div>
      <div class='repo'>github.com/musharraf3/DataTrace</div>
      <div class='foot'>Meta Global AI Developer Hackathon 2026 · Indie Developer · Build for Your World</div></div>"""
    return _page(body, css)


class Take:
    """Collects the parts of the screen recording a scene keeps, each with a playback speed."""

    def __init__(self, scene, cdp):
        self.scene, self.cdp, self.open_at, self.speed = scene, cdp, None, 1.0

    def roll(self, speed=1.0):
        self.open_at, self.speed, self.cdp.rolling = time.time(), speed, True

    def cut(self):
        if self.open_at is not None:
            self.scene.pieces.append((self.open_at, time.time(), self.speed))
            self.open_at = None
        self.cdp.rolling = False

    def shown(self):
        kept = sum((b - a) / s for a, b, s in self.scene.pieces)
        return kept + ((time.time() - self.open_at) / self.speed if self.open_at else 0.0)

    async def until(self, seconds):
        """Keep rolling until `seconds` of the scene have been shown."""
        if self.open_at is None:
            self.roll()
        while self.shown() < seconds:
            await asyncio.sleep(0.05)

    async def fit(self, done, budget, follow=None, timeout=300):
        """Roll until `done()` is true, then speed this piece up so it fills at most `budget` seconds."""
        self.cut()  # Keep whatever was rolling before as its own real-time piece.
        self.roll()
        start = self.open_at
        while time.time() - start < timeout and not await done():
            if follow:
                await cdp_follow(follow)
            await asyncio.sleep(1.0)
        self.cut()
        a, b, _ = self.scene.pieces[-1]
        self.scene.pieces[-1] = (a, b, max(1.0, (b - a) / max(budget, 1.0)))
        return b - a


async def cdp_follow(cdp):
    await cdp.js(FOLLOW)


async def body_has(cdp, *texts):
    page = await cdp.js("document.body.innerText") or ""
    return any(text in page for text in texts)


async def perform(cdp, scene, f, recorded, checks):
    """Prepare the screen (not recorded), then play the scene while its narration would run."""
    take, length = Take(scene, cdp), scene.length
    name = scene.name
    if name == "dashboard":
        await goto(cdp, dashboard_page())
        take.roll()
        await cdp.js("document.body.classList.add('go')")
        await take.until(length)
    elif name == "hero":
        await open_app(cdp, "?incident=eligibility_spans&mode=live")
        take.roll()
        await take.until(length)
    elif name == "intake":
        await cdp.js(CLICK % json.dumps("① Start from what you saw"))
        await asyncio.sleep(1.2)
        await cdp.js(CLICK % json.dumps("Use the sample voice note"))
        await asyncio.sleep(1.5)
        await cdp.js(CLICK % json.dumps("Use the sample dashboard screenshot"))
        await asyncio.sleep(2.0)
        await scroll_text(cdp, "① Start from what you saw", above=10)
        await asyncio.sleep(1.0)
        take.roll()
        await take.until(min(scene.cue("Muse Voice Transcribe"), 5.5))
        if recorded:
            await take.until(length)
        else:
            await cdp.js(CLICK % json.dumps("Draft the investigation with Meta"))
            await asyncio.sleep(1.2)
            take.cut()
            ok = await wait_for(cdp, "Draft from muse-spark-1.3", 120)
            draft = await cdp.js("document.body.innerText") or ""
            checks["intake"] = ok and '"refund_policy":"include"' in re.sub(r"\s+", "", draft)
            await scroll_text(cdp, "🎙️ Transcript", above=20)
            await asyncio.sleep(0.8)
            take.roll()
            await take.until(scene.cue("drafts the metric"))
            await scroll_text(cdp, "🧠 Draft from muse-spark-1.3", smooth=True, above=20)
            await take.until(length)
    elif name == "investigate":
        mode = "recorded&autorun=1&speed=2" if recorded else "live"
        await open_app(cdp, f"?incident=eligibility_spans&mode={mode}")
        if not recorded:
            take.roll()
            await asyncio.sleep(1.0)
            await cdp.js(CLICK % json.dumps("③ Investigate metric change"))
            await asyncio.sleep(0.8)
            take.cut()
        else:
            await wait_for(cdp, "Replayed both SQL versions")
        real = await take.fit(lambda: body_has(cdp, "VERDICT ·", "Investigation stopped"), length - take.shown(), follow=cdp)
        checks["investigate_seconds"] = round(real)
        await take.until(length)
    elif name == "verdict":
        await asyncio.sleep(1.0)
        await scroll_to(cdp, ".verdict")
        await asyncio.sleep(1.2)
        page = await cdp.js("document.body.innerText") or ""
        checks["verdict"] = all(x in page for x in (f"{f['real'] / 100:,.0f}", f"{f['error'] / 100:,.0f}"))
        take.roll()
        await take.until(scene.cue("The eligibility"))
        await cdp.js("[...document.querySelectorAll('[role=tab]')].find(e => e.innerText.trim().startsWith('Affected claims')).click()")
        await scroll_text(cdp, "Affected claims", smooth=True, above=120)
        await take.until(scene.cue("The corrected query"))
        await scroll_to(cdp, ".brief", smooth=True, above=260)
        await take.until(length)
    elif name == "clarify":
        paused = False
        if not recorded:
            await open_app(cdp, "?incident=reversal_policy&mode=live")
            await cdp.js(CLICK % json.dumps("③ Investigate metric change"))
            paused = await wait_for(cdp, "PAUSED TO ASK", 240)
        if not paused:
            checks["clarify_live"] = False if not recorded else "recorded"
            await open_app(cdp, "?incident=reversal_policy&mode=recorded&autorun=1&fast=1")
            await wait_for(cdp, "PAUSED TO ASK", 60)
        await asyncio.sleep(1.0)
        await scroll_to(cdp, ".verdict", above=110)
        await asyncio.sleep(1.0)
        take.roll()
        await take.until(scene.cue("The analyst answers"))
        await cdp.js(CLICK % json.dumps("Include reversals"))
        await asyncio.sleep(0.6)
        hold = 3.0
        await take.fit(lambda: body_has(cdp, "Resumed after the analyst", "Investigation stopped"),
                       length - take.shown() - hold, follow=cdp, timeout=240)
        await asyncio.sleep(0.8)
        await scroll_to(cdp, ".verdict")
        await asyncio.sleep(0.4)
        take.roll()
        await take.until(length)
    elif name == "benchmark":
        await cdp.js("window.scrollTo({top: 0})")
        await cdp.js(CLICK % json.dumps("📊 Agent vs. baseline benchmark"))
        await asyncio.sleep(2.5)
        await scroll_text(cdp, "Right dollars on the real change", above=20)
        await asyncio.sleep(2.0)
        take.roll()
        await take.until(length)
    elif name == "reviewer":
        await scroll_text(cdp, "Is the reviewer more than decoration?", above=20)
        await asyncio.sleep(1.5)
        take.roll()
        await take.until(length)
    elif name == "architecture":
        await goto(cdp, architecture_page())
        take.roll()
        await cdp.js("document.body.classList.add('go')")
        await take.until(length)
    elif name == "end":
        await goto(cdp, end_page(f))
        take.roll()
        await cdp.js("document.body.classList.add('go')")
        await take.until(length + 2.0)
    take.cut()


async def record(scenes, f, recorded, frame_dir):
    profile = tempfile.mkdtemp(prefix="dt-video-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}", "--no-first-run",
                               "--hide-scrollbars", "--window-size=1600,1000", f"--force-device-scale-factor={SCALE:.7f}",
                               f"--user-data-dir={profile}", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    checks = {}
    try:
        for _ in range(40):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2).read())
                ws_url = next(p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page")
                break
            except Exception:
                time.sleep(0.5)
        async with websockets.connect(ws_url, max_size=80_000_000) as ws:
            cdp = CDP(ws)
            reader = asyncio.ensure_future(cdp.reader())
            await cdp.send("Page.enable")
            await cdp.send("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=SCALE, mobile=False)
            await cdp.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
            await open_app(cdp, "?incident=eligibility_spans&mode=live")  # Warm caches.
            capture = asyncio.ensure_future(cdp.capture(frame_dir))
            for scene in scenes:
                await perform(cdp, scene, f, recorded, checks)
                kept = sum((b - a) / s for a, b, s in scene.pieces)
                speeds = ", ".join(f"{s:.1f}x" for _, _, s in scene.pieces if s > 1.01)
                shots = sum(1 for ts, _ in cdp.frames for a, b, _ in scene.pieces if a < ts < b)
                print(f"scene {scene.name:12s} {kept:5.1f}s (narration {scene.duration:4.1f}s) {shots:4d} frames {speeds}",
                      flush=True)
                checks.setdefault("frames", {})[scene.name] = shots
            capture.cancel()
            await asyncio.sleep(0.3)
            reader.cancel()
            return cdp.frames, checks
    finally:
        chrome.terminate()


# ---------------------------------------------------------------- assembly

def _stamp(seconds, srt=False):
    cs = int(round(seconds * 100))
    if srt:
        ms = int(round(seconds * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def caption_chunks(scene, start):
    """Split each spoken sentence into short caption lines timed within the sentence."""
    out = []
    for offset, span, sentence in scene.sentences:
        words, lines, line = sentence.split(), [], ""
        for word in words:
            if line and (len(line) + 1 + len(word) > 58 or (len(line) > 30 and line[-1] in ",:;")):
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            lines.append(line)
        total = sum(len(x) for x in lines) or 1
        at = 0
        for text in lines:
            begin = start + LEAD + offset + span * at / total
            at += len(text)
            out.append((begin, start + LEAD + offset + span * at / total + 0.15, text))
    return out


def build(scenes, frames, work):
    ffmpeg = _ffmpeg()
    listing = work / "frames.txt"
    starts, cursor, last = [], 0.0, None
    badges = []
    with listing.open("w", encoding="utf-8") as handle:
        for scene in scenes:
            starts.append(cursor)
            previous_end = None
            for a, b, speed in scene.pieces:
                if previous_end is not None and a - previous_end > 2:
                    badges.append((cursor, cursor + 2.2, f"Model wait trimmed  ·  {a - previous_end:.0f} s"))
                if speed > 1.01:
                    badges.append((cursor, cursor + (b - a) / speed, f"LIVE  ·  {speed:.1f}× speed"))
                before = [x for x in frames if x[0] <= a]
                inside = [x for x in frames if a < x[0] < b]
                shots, kept_at = [], None
                for ts, path in ([(a, before[-1][1])] if before else []) + inside:
                    # Sped-up pieces drop frames rather than hold each one longer, so picture and narration stay in sync.
                    if kept_at is None or (ts - kept_at) / speed >= 1 / 30:
                        shots.append((ts, path))
                        kept_at = ts
                for index, (ts, path) in enumerate(shots):
                    nxt = shots[index + 1][0] if index + 1 < len(shots) else b
                    handle.write(f"file '{path.as_posix()}'\nduration {max(0.001, (nxt - ts) / speed):.4f}\n")
                    last = path
                cursor += (b - a) / speed
                previous_end = b
        handle.write(f"file '{last.as_posix()}'\nduration 0.1\nfile '{last.as_posix()}'\n")
    total = cursor

    audio = bytearray(int((total + 1) * RATE_HZ) * 2)
    for scene, start in zip(scenes, starts):
        with wave.open(str(scene.audio)) as handle:
            data = handle.readframes(handle.getnframes())
        at = int((start + LEAD) * RATE_HZ) * 2
        audio[at:at + len(data)] = data[: max(0, len(audio) - at)]
    track = work / "narration.wav"
    with wave.open(str(track), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE_HZ)
        handle.writeframes(bytes(audio))

    captions = [c for scene, start in zip(scenes, starts) for c in caption_chunks(scene, start)]
    esc = lambda text: text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")
    events = []
    for scene, start in zip(scenes, starts):
        if scene.chapter:
            end = start + sum((b - a) / s for a, b, s in scene.pieces)
            events.append(f"Dialogue: 1,{_stamp(start + 0.15)},{_stamp(end - 0.1)},Chapter,,0,0,0,,{{\\fad(250,200)}}{esc(scene.chapter)}")
    for begin, end, text in badges:
        events.append(f"Dialogue: 2,{_stamp(begin)},{_stamp(end)},Badge,,0,0,0,,{{\\fad(150,150)}}{esc(text)}")
    for begin, end, text in captions:
        events.append(f"Dialogue: 3,{_stamp(begin)},{_stamp(end)},Caption,,0,0,0,,{esc(text)}")
    (work / "overlay.ass").write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {FW}
PlayResY: {FH}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Segoe UI,38,&H00FFFFFF,&H000000FF,&H2A2A1A10,&H00000000,-1,0,0,0,100,100,0,0,3,13,0,2,80,80,42,1
Style: Chapter,Segoe UI,27,&H00FFFFFF,&H000000FF,&H00AE5636,&H00000000,-1,0,0,0,100,100,0.5,0,3,11,0,7,110,80,30,1
Style: Badge,Segoe UI,25,&H00FFFFFF,&H000000FF,&H00202DD9,&H00000000,-1,0,0,0,100,100,0.5,0,3,10,0,9,80,70,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(events) + "\n", encoding="utf-8")

    fonts = work / "fonts"
    fonts.mkdir(exist_ok=True)
    for name in ("segoeui.ttf", "segoeuib.ttf"):
        if (Path(r"C:\Windows\Fonts") / name).exists():
            shutil.copy(Path(r"C:\Windows\Fonts") / name, fonts / name)
    target = OUT / "datatrace-demo.mp4"
    fade_out = max(0.0, total - 0.9)
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "frames.txt", "-i", "narration.wav",
                    "-vf", f"fps=30,scale={FW}:{FH}:flags=lanczos:out_range=tv,format=yuv420p,"
                           f"subtitles=overlay.ass:fontsdir=fonts,fade=t=in:st=0:d=0.5,fade=t=out:st={fade_out:.2f}:d=0.9",
                    "-pix_fmt", "yuv420p", "-color_range", "tv",
                    "-af", f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,afade=t=out:st={fade_out:.2f}:d=0.9", "-c:v", "libx264", "-preset", "slow", "-crf", "19",
                    "-profile:v", "high", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                    "-t", f"{total:.2f}", str(target.resolve())], check=True, cwd=work)
    srt = [f"{i}\n{_stamp(b, True)} --> {_stamp(e, True)}\n{t}\n" for i, (b, e, t) in enumerate(captions, 1)]
    (ROOT / "docs" / "demo_captions.srt").write_text("\n".join(srt), encoding="utf-8")
    return target, total, starts


CHAPTERS = {"dashboard": "The 8 a.m. question", "hero": "What DataTrace is", "intake": "Voice note + screenshot intake",
            "investigate": "The agent investigates", "verdict": "Verdict: real run-out vs. reporting error",
            "clarify": "It asks instead of guessing", "benchmark": "Benchmark: agent vs. raw rows",
            "reviewer": "Reviewer stress test", "architecture": "How it works"}


def youtube(scenes, starts, total, f, recorded):
    stamp = lambda t: f"{int(t) // 60}:{int(t) % 60:02d}"
    chapters = "\n".join(f"{stamp(start)} {CHAPTERS[scene.name]}" for scene, start in zip(scenes, starts)
                         if scene.name in CHAPTERS)
    how = ("All screens are the real app replaying captured Meta runs" if recorded else
           "All screens are the real app making live Meta API calls")
    text = f"""# Uploading the demo video

**File:** `docs/video/datatrace-demo.mp4` ({stamp(total)}, 1920x1080). **Captions:** `docs/demo_captions.srt`.

1. YouTube → Create → Upload video → choose the file. Visibility: **Unlisted**.
2. Paste the title and description below. YouTube turns the timestamps into chapters.
3. Optional: Subtitles → Add language → English → Upload file → *With timing* → `docs/demo_captions.srt`
   (captions are already burned into the video; this adds a searchable, toggleable track).
4. Open the link in a private window to check it plays, then paste it into the submission form.

**Title**

DataTrace: is the claims jump real, or is the dashboard wrong? (Meta Muse Spark agent)

**Description**

DataTrace is an agent that tells a healthcare finance team whether a jump in paid claims is real or a data defect, and proves it with verified SQL. Built for the Meta Global AI Developer Hackathon 2026 (Indie Developer · Build for Your World).

• Muse Spark (muse-spark-1.3) investigates with sandboxed, read-only SQL and never sees raw rows
• Muse Wonder (muse-wonder-1.0) independently reviews every diagnosis and caught {f['planted'][0]}/{f['planted'][1]} planted errors
• Muse Voice Transcribe turns an actuary's voice note into the request
• On CMS claims: right dollar split in {f['claims_agent'][0]}/{f['claims_agent'][1]} runs vs. {f['claims_base'][0]}/{f['claims_base'][1]} for the same model reading every raw row

Code: https://github.com/musharraf3/DataTrace

{chapters}

{how}; model waiting time is trimmed or sped up as labelled on screen. Narration is a synthetic voice. Data: CMS 2008–2010 DE-SynPUF synthetic Medicare claims (public domain, no real patients); claims lag, reversals and the defect are simulated.
"""
    (OUT / "YOUTUBE.md").write_text(text, encoding="utf-8")


def save_take(work, scenes, frames, checks):
    data = {"checks": checks, "frames": [(ts, str(path)) for ts, path in frames],
            "scenes": [{"name": s.name, "chapter": s.chapter, "text": s.text, "audio": str(s.audio), "duration": s.duration,
                        "sentences": s.sentences, "pieces": s.pieces} for s in scenes]}
    (work / "take.json").write_text(json.dumps(data), encoding="utf-8")


def load_take(work):
    data = json.loads((work / "take.json").read_text(encoding="utf-8"))
    scenes = [Scene(d["name"], d["chapter"], d["text"], Path(d["audio"]), d["duration"],
                    [tuple(x) for x in d["sentences"]], [tuple(x) for x in d["pieces"]]) for d in data["scenes"]]
    return scenes, [(ts, Path(path)) for ts, path in data["frames"]], data["checks"]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recorded", action="store_true", help="replay committed recorded runs instead of live calls")
    parser.add_argument("--keep", action="store_true", help="keep the working folder with frames")
    parser.add_argument("--rebuild", metavar="WORK", help="re-assemble a kept recording without recording again")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    f = facts()
    if args.rebuild:
        work = Path(args.rebuild)
        scenes, frames, checks = load_take(work)
        target, total, starts = build(scenes, frames, work)
        youtube(scenes, starts, total, f, args.recorded)
        print(f"checks: {checks}\nvideo: {target} ({total:.1f}s)")
        return
    work = Path(tempfile.mkdtemp(prefix="dt-demo-"))
    (work / "frames").mkdir()
    scenes = script(f, args.recorded)
    for scene in scenes:
        speak(scene, work)
    narration = sum(s.length for s in scenes) + 2.0
    print(f"narration {narration:.0f}s (limit {MAX_SECONDS:.0f}s)", flush=True)
    if narration > MAX_SECONDS:
        sys.exit("Narration is too long for a 3-minute video; shorten the script.")
    frames, checks = asyncio.run(record(scenes, f, args.recorded, work / "frames"))
    save_take(work, scenes, frames, checks)
    target, total, starts = build(scenes, frames, work)
    youtube(scenes, starts, total, f, args.recorded)
    print(f"checks: {checks}")
    print(f"video: {target} ({total:.1f}s, {len(frames)} frames, work folder {work})")
    if not args.keep:
        shutil.rmtree(work / "frames", ignore_errors=True)
    if checks.get("verdict") is False:
        print("WARNING: the live verdict did not show the narrated dollars; re-run or use --recorded.")


if __name__ == "__main__":
    sys.exit(main())
