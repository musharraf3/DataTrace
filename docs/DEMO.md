# Three-minute demo video

Target length **2:45–3:00**. Judging weights: Impact 30%, Meta AI tooling 25%, Technical depth 20%, Demo 25%.

## Two ways to submit a video

1. **Ready to submit as is:** [`docs/video/datatrace-demo.mp4`](video/datatrace-demo.mp4) (under 3:00, 1920×1080, neural-voice narration, burned-in captions and chapter labels). It was recorded from the real app making **live** Meta API calls: voice-note intake, the claims investigation, and the clarification pause and resume. Model waiting time is trimmed or sped up, and the video labels it on screen. Upload steps, title, description and chapters: [`docs/video/YOUTUBE.md`](video/YOUTUBE.md). Rebuild it with `python scripts/make_demo_video.py` (live, about $0.30) or `--recorded` (free).
2. **Optional: your own voice over the same flow.** Judges respond to a real person who knows the domain. Follow the script below, or play the video muted and read `docs/demo_captions.srt` over it while screen-recording.

Every number below comes from the committed recording `examples/recorded/synpuf-eligibility_spans.json` and the deterministic reconciliation, so a live run produces the same dollars with slightly different wording.

## Before you record (10 minutes)

1. Close any older DataTrace terminal (Ctrl-C). Run `.\.venv\Scripts\python.exe scripts\doctor.py` (it must print `RESULT OK`), then `.\.venv\Scripts\python.exe run.py`.
2. Browser zoom 90%, window 1440×900 or larger, bookmarks bar hidden. If Streamlit shows a "Help agents write better apps" popup, click **Don't show again**.
3. Close every window showing `.env`. The app only ever shows "Meta key configured".
4. Recorder: **Win+Alt+R** (Xbox Game Bar), OBS or Clipchamp. Use a headset mic.
5. Open these tabs in order:

| Scene | Link |
| --- | --- |
| Claims dashboard image | `examples/claims_dashboard_screenshot.png` |
| Intake and live run | <http://localhost:8501/?incident=eligibility_spans&mode=live> |
| Flagship replay (backup for the live run) | <http://localhost:8501/?incident=eligibility_spans&mode=recorded&autorun=1&speed=2> |
| The agent asks about reversals | <http://localhost:8501/?incident=reversal_policy&mode=recorded&autorun=1&fast=1> |
| Reviewer challenge and revision (optional) | <http://localhost:8501/?incident=service_date_cutoff&mode=recorded&autorun=1&fast=1> |

Links never auto-run live mode, so opening a tab never spends credits.

## Script

| Time | On screen | Say |
| --- | --- | --- |
| 0:00–0:15 | Claims dashboard image | "8 a.m. The monthly cost review is at 10. Paid inpatient claims for November just jumped 40% overnight. Some run-out is normal, but is this real, or is the dashboard wrong?" |
| 0:15–0:30 | DataTrace hero | **Your line (Build for Your World):** "In healthcare analytics, [one true sentence from your own work, e.g. 'I've had to explain a cost spike that turned out to be an eligibility load']. DataTrace is the tool I wanted: an agent that investigates with evidence and verifies its own fix." |
| 0:30–0:45 | ① Start from what you saw → tick the actuarial voice note and the claims screenshot → **Draft the investigation with Meta** | "An actuary leaves a voice note. Muse Voice Transcribe turns it into text; Muse Spark reads it with the screenshot and drafts the definition: paid claims, November service month, net of reversals." |
| 0:45–1:20 | Press **③ Investigate** (live), or the flagship replay tab | "This is Muse Spark as an agent on real-format CMS Medicare claims. It never sees raw rows. It tests hypotheses, duplicate eligibility rows, members dropped by a join, date and reversal boundaries, each with a bounded, read-only query, then checks a corrected query claim by claim. A second model, Muse Wonder, reviews the diagnosis." |
| 1:20–1:50 | Verdict card, four metrics, leadership brief, bridge; briefly **Affected claims** | "Of a $5.2 million jump, $4.56 million is genuine run-out. $649,400 is a reporting error: the eligibility rebuild gave members who switched coverage two rows, double-counting their claims, and dropped deceased members. The fix is verified claim by claim, and here's the brief for the cost review." |
| 1:50–2:10 | Reversal tab → it pauses → **Include reversals (net paid)** | "When the definition is missing it doesn't guess. It asks whether reversals net against paid claims. I answer, and the same investigation resumes." |
| 2:10–2:40 | **📊 Agent vs. baseline benchmark** tab, scroll to the reviewer panel | "360 paid runs against the same model given every raw row and no tools. On CMS claims, the baseline put the right dollars on the split in 4 of 16 runs; the agent, 16 of 16. At 42,000 rows the raw data doesn't fit in the context window at all. And when we planted errors, the reviewer caught 28 of 28." |
| 2:40–3:00 | **⚙️ How it works** table | "Four Meta model roles, a sandboxed SQL engine, and a verifier the model can't fool. The same engine runs retail revenue, and an adapter runs it on open-weight Muse models. Built during the hackathon. DataTrace: evidence before explanations." |

## Built during the event

All commits on `main` are dated Oct 28 – Nov 4, 2026, inside the building window. Show the GitHub commit list for 2 seconds or mention it.

## Backup plan

- API slow or down: use the recorded tabs for every scene; they are real captured Meta runs.
- Out of time: submit `docs/video/datatrace-demo.mp4`.
- Upload as **unlisted** on YouTube and check it plays in a private window.
