# Three-minute demo video: script and shot list

Target length **2:50–3:00**. Judging weights: Impact 30%, Meta AI tooling 25%, Technical depth 20%, Demo 25%.
Every number below comes from the committed recorded run `examples/recorded/realistic-crm_migration.json`.
A live run will produce the same diagnosis with slightly different wording.

## Before you record (10 minutes)

1. Close any older DataTrace terminal first (Ctrl-C). An old server left running from before the upgrade keeps answering on port 8501 with the old Streamlit and shows errors. Then run `.\.venv\Scripts\python.exe scripts\doctor.py` (it must print `RESULT OK`), start `.\.venv\Scripts\python.exe run.py`, and open the URL it prints. Browser zoom 90%, window 1440×900 or larger, bookmarks bar hidden. If Streamlit shows a "Help agents write better apps" popup, click **Don't show again**.
2. Close every window showing `.env`. The app only ever shows "Meta key configured".
3. Do one warm-up live run of the flagship incident so the first real take starts quickly.
4. Recorder: Windows **Win+Alt+R** (Xbox Game Bar), OBS, or Clipchamp screen recording. Use a headset mic.
5. **Safe path:** if the network or API is slow, use **Recorded live run** mode. It replays a real captured Meta run step by step. Say "this is a recorded run from the app" if you use it.
6. If you speed up waiting time in editing, put a small "2× speed" label on screen.

## One-click links for recording

Open these in separate browser tabs before you start, so every scene is one click away:

| Scene | Link |
| --- | --- |
| Flagship, live (press Investigate) | <http://localhost:8501/?incident=crm_migration&mode=live> |
| Flagship, recorded replay | <http://localhost:8501/?incident=crm_migration&mode=recorded&autorun=1> |
| Agent asks about refunds | <http://localhost:8501/?incident=refund_policy&mode=recorded&autorun=1> |
| Genuine growth, no fix | <http://localhost:8501/?incident=holiday_growth&mode=recorded&autorun=1> |

Links never auto-run live mode, so opening a tab never spends credits.

## Script

| Time | On screen | Say |
| --- | --- | --- |
| 0:00–0:15 | `examples/dashboard_screenshot.png` full screen | "It's 8 a.m. The CFO review is at 10. Paid November revenue just jumped 68% overnight. Black Friday was strong, but is this real, or is the dashboard wrong?" |
| 0:15–0:30 | DataTrace hero | **Your line (Build for Your World):** "I've been the analyst who had to answer that question at 8 a.m., [one true sentence from your work]. DataTrace is the tool I wanted: an agent that investigates the change with evidence and checks its own fix." |
| 0:30–0:55 | Open **① Start from what you saw**. Tick *Use the sample voice note* and *Use the sample dashboard screenshot*. Click **Draft the investigation with Meta** | "A stakeholder leaves a voice note. **Muse Voice Transcribe** turns it into text, and **Muse Spark** reads the note and the screenshot and drafts the metric definition: paid orders, November, refunds excluded. I confirm it." Click **Use this description and definition**. |
| 0:55–1:45 | Click **③ Investigate metric change**. Let the timeline stream | "Muse Spark is now an agent. It never sees the raw rows. It sees the schema and a four-way replay of old and new SQL on old and new data. Watch it form hypotheses: duplicate customer keys, unmatched customers dropped by the join, date and refund boundaries. Each one is a real SQL query in a read-only sandbox, run in parallel. It finds that a CRM migration duplicated 126 customers, and it tests a corrected query with an independent per-order checker. Then a second model, **Muse Wonder**, reviews the diagnosis against the evidence." |
| 1:45–2:15 | Verdict card, four metrics, CFO brief, revenue bridge. Briefly open **Affected orders** | "The verdict: revenue really grew **$115,080**. **$13,966** is a reporting error, made of **$25,521** of double-counted orders minus **$11,555** of orders the join dropped. The fix restores **$304,397**, and it is verified order by order, not just on the total. Here is the two-sentence brief for the CFO, and here are the 406 affected orders." |
| 2:15–2:35 | Sidebar → **Refund treatment undefined** → Investigate → the agent pauses → click **Exclude refunds** | "When the definition is missing, DataTrace doesn't guess. The agent pauses and asks a precise question. I answer, and the same investigation resumes and finishes." (Use Recorded live run mode here to save time.) |
| 2:35–2:50 | **📊 Agent vs. baseline benchmark** tab | "We ran 320 paid runs against the same Meta model given all the raw rows and no tools. When the data fits in a prompt, both are accurate, but the agent uses 14× fewer tokens and never sees a raw row. At 42,000 orders the raw data is 2 million tokens and doesn't fit in the context window: the baseline scores zero, and the agent solves 10 out of 10, because it only reads what it queries." |
| 2:50–3:00 | **⚙️ How it works** diagram | "Four Meta model roles, a sandboxed SQL engine, and a verifier a model can't fool. Everything here was built during the hackathon. DataTrace: evidence before explanations." |

## What to show that was built during the event

All commits on `main` were made between Oct 28 and Nov 3, 2026, inside the building window (Oct 27 – Nov 4). Show the GitHub commit list for 2 seconds or mention it in the description.

## Backup plan

- API slow or down: use **Recorded live run** for every scene. It is real captured Meta output, replayed at about 5× speed.
- Something errors on camera: switch incidents and continue; the recorded mode needs no network.
