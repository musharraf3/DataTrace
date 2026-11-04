"""Build a narrated backup demo video (MP4) by driving the running app with headless Chrome.

The app must be running on http://localhost:8501 (python run.py). Narration is Windows speech synthesis;
replace it with your own voice using docs/demo_captions.srt as the script. Numbers in the narration are read
from the committed recordings and benchmark results, so they always match what is on screen.

Usage: python scripts/make_demo_video.py   ->  docs/video/datatrace-demo.mp4
"""

import asyncio
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "video"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
APP = "http://localhost:8501/"
PORT = 9334
W, H = 1440, 900


def _money(cents, millions=False):
    value = abs(cents) / 100
    if millions and value >= 1_000_000:
        return f"{value / 1_000_000:.2f} million dollars"
    return f"{value:,.0f} dollars"


def narration():
    rec = json.loads((ROOT / "examples/recorded/synpuf-eligibility_spans.json").read_text(encoding="utf-8"))["report"]
    r = rec["reconciliation"]
    moved = rec["replay"][3]["revenue_cents"] - rec["replay"][0]["revenue_cents"]
    bench = json.loads((ROOT / "results/benchmark.json").read_text(encoding="utf-8"))
    reviewer = json.loads((ROOT / "results/reviewer_eval.json").read_text(encoding="utf-8"))
    runs = sum(int(row["Correct diagnosis"].split("/")[1]) for row in bench["table"])
    agent_ok = sum(int(row["Correct diagnosis"].split("/")[0]) for row in bench["table"] if row["System"].startswith("DataTrace"))
    agent_n = sum(int(row["Correct diagnosis"].split("/")[1]) for row in bench["table"] if row["System"].startswith("DataTrace"))
    split = {row["System"][:4]: row["Dollar split correct"] for row in bench["table"] if row["Split"].startswith("Realistic")}
    return [
        ("dashboard", "Eight A M. The monthly cost review is at ten. Paid inpatient claims for November just jumped forty "
                      "percent overnight. Some claims run-out is normal. So is this real, or is the dashboard wrong?"),
        ("hero", "DataTrace is a Meta agent that answers that question with evidence. It runs real SQL, separates genuine "
                 "change from reporting errors down to the individual claim, and only reports a fix after an independent "
                 "check verifies it."),
        ("intake", "An actuary leaves a voice note. Muse Voice Transcribe turns it into text, and Muse Spark reads the note "
                   "and the dashboard screenshot, and drafts the metric definition: paid claims, November service month, "
                   "net of reversals."),
        ("investigate", "Now Muse Spark works as an agent, on real-format CMS Medicare claims. It never sees the raw rows. "
                        "It forms hypotheses, like duplicate eligibility rows, members dropped by a join, and date or "
                        "reversal boundaries, and tests each one with a bounded, read-only query. It checks a corrected "
                        "query against an independent claim-by-claim verifier, and a second model, Muse Wonder, reviews "
                        "the diagnosis against the evidence."),
        ("verdict", f"The verdict. Of a {_money(moved, True)} jump, {_money(r['underlying_change_cents'], True)} is "
                    f"genuine claims run-out. {_money(r['current_error_cents'])} is a reporting error. The eligibility "
                    f"rebuild gave members who switched coverage two rows, double counting their claims, while deceased "
                    f"members were dropped. The fix is verified claim by claim, and here is the brief for the cost review."),
        ("clarify", "When the definition is missing, DataTrace does not guess. The agent pauses and asks whether reversals "
                    "should net against paid claims. I answer: include them, net paid. The same investigation resumes "
                    "from where it paused, finishes, verifies its fix, and is reviewed again."),
        ("benchmark", f"We measured it in {runs} paid runs against the same Meta model given every raw row and no tools. "
                      f"The agent was correct in {agent_ok} of {agent_n}. On realistic incidents the baseline usually names "
                      f"the right category, but put the right dollar amounts on it in only {split.get('Same', 'half')} "
                      f"runs, against {split.get('Data', 'all')} for the agent. At forty-two thousand rows, the raw data "
                      f"no longer fits in the context window, and only the agent can investigate."),
        ("how", f"We also stress-tested the reviewer. It caught {reviewer['planted_caught']} of "
                f"{reviewer['planted_total']} planted errors. Four Meta model roles, a sandboxed SQL engine, and a "
                f"verifier the model cannot fool, all built during the hackathon. DataTrace. Evidence before explanations."),
    ]


def speak(text, path):
    script = Path(tempfile.mkdtemp()) / "say.ps1"
    (script.parent / "text.txt").write_text(text, encoding="utf-8")
    script.write_text(
        "Add-Type -AssemblyName System.Speech\n"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        "$s.Rate = 1\n"
        "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, "
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)\n"
        f"$s.SetOutputToWaveFile('{path}', $f)\n"
        f"$s.Speak([IO.File]::ReadAllText('{script.parent / 'text.txt'}'))\n"
        "$s.Dispose()\n", encoding="utf-8")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], check=True)
    with wave.open(str(path)) as handle:
        return handle.getnframes() / handle.getframerate()


class CDP:
    def __init__(self, ws):
        self.ws, self.counter, self.pending, self.frames = ws, 0, {}, []

    async def reader(self, frame_dir):
        async for raw in self.ws:
            message = json.loads(raw)
            if message.get("method") == "Page.screencastFrame":
                params = message["params"]
                path = frame_dir / f"f{len(self.frames):06d}.jpg"
                path.write_bytes(base64.b64decode(params["data"]))
                self.frames.append((params["metadata"]["timestamp"], path))
                asyncio.ensure_future(self.send("Page.screencastFrameAck", sessionId=params["sessionId"]))
            elif "id" in message and message["id"] in self.pending:
                self.pending.pop(message["id"]).set_result(message.get("result", {}))

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
  el.scrollIntoView({block:'center'});
  const box = el.closest('label') && el.closest('label').querySelector('input[type=checkbox]');
  (box || el).click(); return true })(%s)"""
SCROLL_TO = "(s => { const el = document.querySelector(s); if (el) el.scrollIntoView({behavior:'smooth', block:'start'}); return !!el })(%s)"


async def wait_for(cdp, text, seconds=60):
    for _ in range(int(seconds * 2)):
        if await cdp.js(f"document.body.innerText.includes({json.dumps(text)})"):
            return True
        await asyncio.sleep(0.5)
    return False


async def prepare(cdp, name):
    """Get the screen ready for a scene. Time spent here is cut from the final video."""
    if name == "dashboard":
        image = base64.b64encode((ROOT / "examples/claims_dashboard_screenshot.png").read_bytes()).decode()
        html = ("<html><body style='margin:0;background:#0b1736;display:flex;align-items:center;justify-content:center;"
                f"height:100vh'><img src='data:image/png;base64,{image}' style='width:88%;border-radius:14px;"
                "box-shadow:0 20px 60px rgba(0,0,0,.5)'></body></html>")
        await cdp.send("Page.navigate", url="data:text/html;base64," + base64.b64encode(html.encode()).decode())
        await asyncio.sleep(1.5)
    elif name == "hero":
        await cdp.send("Page.navigate", url=APP + "?incident=eligibility_spans&mode=live")
        await wait_for(cdp, "Is the jump real")
        await asyncio.sleep(1.5)
    elif name == "intake":
        await cdp.js(CLICK % json.dumps("① Start from what you saw"))
        await asyncio.sleep(1.5)
    elif name == "investigate":
        await cdp.send("Page.navigate", url=APP + "?incident=eligibility_spans&mode=recorded&autorun=1&speed=2")
        await wait_for(cdp, "Replayed both SQL versions")
    elif name == "verdict":
        await wait_for(cdp, "VERDICT", 120)
        await asyncio.sleep(1)
        await cdp.js(SCROLL_TO % json.dumps(".verdict"))
        await asyncio.sleep(1.5)
    elif name == "clarify":
        await cdp.send("Page.navigate", url=APP + "?incident=reversal_policy&mode=recorded&autorun=1&fast=1")
        await wait_for(cdp, "PAUSED TO ASK", 60)
        await asyncio.sleep(1)
        await cdp.js(SCROLL_TO % json.dumps(".verdict"))
        await asyncio.sleep(1.5)
    elif name == "benchmark":
        await cdp.js("window.scrollTo({top: 0})")
        await cdp.js(CLICK % json.dumps("📊 Agent vs. baseline benchmark"))
        await asyncio.sleep(3)
    elif name == "how":
        await cdp.js("window.scrollTo({top: 0})")
        await cdp.js(CLICK % json.dumps("⚙️ How it works"))
        await asyncio.sleep(2)


async def during(cdp, name, duration):
    """What happens on screen while the narration for a scene plays. Returns when the scene may end."""
    began = time.time()
    if name == "intake":
        await cdp.js(CLICK % json.dumps("Use the sample voice note"))
        await asyncio.sleep(2)
        await cdp.js(CLICK % json.dumps("Use the sample dashboard screenshot"))
        await asyncio.sleep(2.5)
        await cdp.js("window.scrollBy({top: 380, behavior: 'smooth'})")
    elif name == "investigate":
        follow = ("(() => { const box = [...document.querySelectorAll('[data-testid=stExpanderDetails]')].pop();"
                  " const items = box ? box.querySelectorAll('[data-testid=stMarkdownContainer], [data-testid=stCode]') : [];"
                  " const last = items[items.length - 1]; if (last) last.scrollIntoView({block: 'end', behavior: 'smooth'}); })()")
        while time.time() - began < duration:
            await cdp.js(follow)
            await asyncio.sleep(1.0)
    elif name == "verdict":
        await asyncio.sleep(min(10, duration / 2))
        await cdp.js("window.scrollBy({top: 520, behavior: 'smooth'})")
    elif name == "clarify":
        await asyncio.sleep(5)
        await cdp.js(CLICK % json.dumps("Include reversals"))
        await wait_for(cdp, "Resumed after the analyst", 40)
        await asyncio.sleep(1)
        await cdp.js(SCROLL_TO % json.dumps(".verdict"))
    elif name == "benchmark":
        await asyncio.sleep(min(12, duration / 2))
        await cdp.js("window.scrollBy({top: 560, behavior: 'smooth'})")
    remaining = duration + 0.8 - (time.time() - began)
    if remaining > 0:
        await asyncio.sleep(remaining)
    if name == "clarify":
        await asyncio.sleep(2.5)  # Hold on the resumed verdict.


async def record(scenes, audio_paths, durations, frame_dir):
    profile = tempfile.mkdtemp(prefix="dt-video-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}", "--no-first-run",
                               "--hide-scrollbars", f"--user-data-dir={profile}", f"--window-size={W},{H}", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2).read())
                ws_url = next(p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page")
                break
            except Exception:
                time.sleep(0.5)
        async with websockets.connect(ws_url, max_size=50_000_000) as ws:
            cdp = CDP(ws)
            reader = asyncio.ensure_future(cdp.reader(frame_dir))
            await cdp.send("Page.enable")
            await cdp.send("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
            await cdp.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
            await cdp.send("Page.navigate", url=APP + "?incident=eligibility_spans&mode=live")  # Warm caches.
            await wait_for(cdp, "Is the jump real")
            await cdp.send("Page.startScreencast", format="jpeg", quality=85, maxWidth=W, maxHeight=H, everyNthFrame=1)
            windows = []
            for (name, _), duration in zip(scenes, durations):
                await prepare(cdp, name)
                start = time.time()
                await during(cdp, name, duration)
                windows.append((start, time.time()))
                print(f"scene {name}: {windows[-1][1] - start:.1f}s (narration {duration:.1f}s)", flush=True)
            await cdp.send("Page.stopScreencast")
            reader.cancel()
            return windows, cdp.frames
    finally:
        chrome.terminate()


def build(windows, frames, audio_paths):
    """Concatenate only the narrated windows; preparation time is cut."""
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    listing = OUT / "frames.txt"
    offsets, cursor = [], 0.0
    with listing.open("w", encoding="utf-8") as handle:
        last = None
        for start, end in windows:
            offsets.append(cursor)
            before = [f for f in frames if f[0] <= start]
            inside = [f for f in frames if start < f[0] < end]
            shots = ([(start, before[-1][1])] if before else []) + inside
            for index, (ts, path) in enumerate(shots):
                nxt = shots[index + 1][0] if index + 1 < len(shots) else end
                handle.write(f"file '{path.as_posix()}'\nduration {max(0.034, nxt - ts):.3f}\n")
                last = path
            cursor += end - start
        handle.write(f"file '{last.as_posix()}'\n")
    rate = 16000
    audio = bytearray(int((cursor + 1) * rate) * 2)
    for offset, path in zip(offsets, audio_paths):
        with wave.open(str(path)) as handle:
            data = handle.readframes(handle.getnframes())
        at = int((offset + 0.3) * rate) * 2
        audio[at:at + len(data)] = data[: max(0, len(audio) - at)]
    track = OUT / "narration.wav"
    with wave.open(str(track), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(audio))
    target = OUT / "datatrace-demo.mp4"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(track),
                    "-vf", "fps=30,scale=1440:900,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "22",
                    "-c:a", "aac", "-b:a", "128k", "-shortest", str(target)], check=True)
    return target, offsets, cursor


def captions(scenes, offsets, durations):
    def stamp(seconds):
        ms = int(round(seconds * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    blocks = []
    for index, ((_, text), offset, duration) in enumerate(zip(scenes, offsets, durations), 1):
        blocks.append(f"{index}\n{stamp(offset + 0.3)} --> {stamp(offset + 0.3 + duration)}\n{text}\n")
    (ROOT / "docs" / "demo_captions.srt").write_text("\n".join(blocks), encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="dt-demo-"))
    frame_dir = work / "frames"
    frame_dir.mkdir()
    scenes = narration()
    audio_paths, durations = [], []
    for index, (name, text) in enumerate(scenes):
        path = work / f"{index:02d}-{name}.wav"
        durations.append(speak(text, path))
        audio_paths.append(path)
    print(f"narration total {sum(durations):.0f}s", flush=True)
    windows, frames = asyncio.run(record(scenes, audio_paths, durations, frame_dir))
    target, offsets, total = build(windows, frames, audio_paths)
    captions(scenes, offsets, durations)
    print(f"video: {target} ({total:.0f}s, {len(frames)} frames)")


if __name__ == "__main__":
    sys.exit(main())
