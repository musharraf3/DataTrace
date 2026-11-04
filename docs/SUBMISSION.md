# Cerebral Valley submission: copy-ready answers

Deadline: **Wednesday Nov 4, 2026, 6:00 PM PT / 9:00 PM ET**. Submit early in the morning.

| Field | Value |
| --- | --- |
| Project name | DataTrace |
| Team name | DataTrace (solo) |
| Team members | Musharraf Shaikh |
| Track | **Indie Developer** |
| Problem statement | **Build for Your World** |
| Public GitHub repository | https://github.com/musharraf3/DataTrace |
| Demo video | *(your YouTube unlisted or Loom link; check it plays in a private window)* |
| X post URL (optional, Most Viral) | *(your post link; see docs/X_POST.md)* |

## Short versions (for fields with character limits)

**One line (under 120 characters)**
> An agent that tells you if a claims or revenue jump is real or a data bug, and proves it with verified SQL.

**About 280 characters**
> DataTrace is a Muse Spark agent that investigates why a healthcare cost or revenue metric moved. It runs sandboxed SQL, never sees raw rows, verifies every fix claim by claim, asks when a definition is missing, and gets a second opinion from Muse Wonder.

**About 500 characters**
> Every month, claims and finance teams ask: is this cost jump real? DataTrace's Muse Spark agent tests hypotheses with bounded, read-only SQL on real-format CMS Medicare claims, separates genuine run-out from data defects down to the claim, and only reports a fix after an independent check passes. Muse Wonder reviews each diagnosis (it caught 28/28 planted errors). Against the same model reading raw rows, the agent got the dollar split right in 16/16 claims runs vs 4/16.

## GitHub repository "About" box

Set it on the repo page via the gear icon next to **About**:

- **Description:** `Meta-model agent that explains why a healthcare cost or revenue metric moved and verifies the fix claim by claim. Muse Spark + Muse Wonder.`
- **Topics:** `meta-ai`, `muse-spark`, `ai-agents`, `tool-calling`, `healthcare-analytics`, `claims`, `cms-synpuf`, `sql`, `data-quality`, `streamlit`, `hackathon`
- **Website:** your Streamlit Cloud URL if you deploy one, otherwise the video link.

## Project description

Every month, healthcare finance, actuarial and analytics teams get the same question before the cost review: paid claims jumped, so is it real? Claims data makes it hard. Late claims keep arriving for weeks (run-out), adjudication is pending, reversals net against paid, and eligibility files get rebuilt. A genuine trend and a data defect often land in the same month.

DataTrace gives that question to a Muse Spark agent with real tools. Given the previous and current SQL, two data snapshots and the metric definition (or just an actuary's voice note and a dashboard screenshot), it:

- replays old and new SQL on old and new data;
- tests hypotheses (duplicate eligibility rows, members dropped by joins, service-date boundaries, pending claims, reversals) with bounded, read-only SQL in a local sandbox, never seeing raw rows;
- reports a fix only after a deterministic checker verifies the complete per-claim result;
- gets an independent review from Muse Wonder, which can send it back to revise;
- pauses and asks when the definition is incomplete, instead of guessing.

On real-format CMS DE-SynPUF Medicare claims, it showed that of a +$5.21M jump in November paid claims, $4.56M was genuine run-out and $649,400 was an eligibility-rebuild defect across 69 claims. It produced verified corrected SQL and a leadership brief. The same engine runs retail revenue incidents through a domain profile.

Across 360 paid benchmark runs against the same model given every raw row and no tools, the agent scored 179/180 versus 168/180. More importantly, it put the right dollar amounts on real change and reporting error in 16/16 claims runs versus 4/16. At 42k rows the no-tools approach cannot run at all (context_length_exceeded). In a planted-error test, the reviewer caught 28/28 errors.

## Meta products used

- **Meta Model API, Responses API:** client-side function calling, parallel tool calls, `previous_response_id` state (including pause and resume for clarification), reasoning effort control, reasoning summaries, and JSON-schema structured output.
- **muse-spark-1.3:** the investigator agent (tools `query_snapshot`, `verify_correction`, `request_clarification`) and vision intake from dashboard screenshots.
- **muse-wonder-1.0:** an independent reviewer with concerns-first structured output and blocking or minor severity; it triggers revisions and writes the leadership brief.
- **muse-voice-transcribe-1.0** (`/v1/asr/transcribe`): voice-note intake.
- **Chat Completions endpoint:** an adapter, tested against Meta's API, that runs the same agent on open-weight Muse models via Baseten, Fireworks or Modal.

## Why Meta models are important to the solution

The hard part of a claims investigation is judgement: which hypothesis to test next, which diagnostic query separates run-out from a join defect, and when a definition is missing. Muse Spark makes those decisions in a tool loop. Parallel tool calls and reasoning summaries let an analyst watch why it ran each query.

A different Meta model, Muse Wonder, gives an independent review rather than self-grading. Our planted-error test shows it catches every inflated amount, invented cause, flipped classification and unverified fix we planted. Voice and vision intake let a stakeholder start an investigation from a voice note or a screenshot.

Local code supplies what a model shouldn't: sandboxed execution and a deterministic verifier. The benchmark shows why this design matters. The same model reading raw rows names the right category but gets the dollars wrong in most claims runs, and fails outright at warehouse scale.

## Feedback about Meta products

- `previous_response_id` made the multi-turn tool loop and the pause-and-resume clarification simple.
- Parallel tool calls cut investigations from 85s (sequential prototype) to about 40–75s.
- Reasoning summaries are excellent for agent UX; we stream them into the live timeline.
- JSON-schema output was reliable. One lesson: field order matters. Asking for the verdict before the concerns made the reviewer commit early; putting concerns first raised planted-error catches from 19/28 to 28/28.
- `context_length_exceeded` errors are clear and include the token count.
- `tool_choice` currently supports only `"auto"`; supporting `"none"` would make forced-final turns simpler.
- Wishes: a hard spend cap (not only a notification), a field table for `/asr/transcribe`, and documented image-input limits.

## Feedback about partner technologies

No partner inference was used in the submitted runs. The open-weight adapter is ready for Baseten, Fireworks or Modal (credits applied for).

## Before you click Submit

- [ ] Repository is public and opens without signing in (done).
- [ ] Video is 3:00 or less, plays in a private window, and shows the features built during the event.
- [ ] Read the consent checkbox text yourself before ticking it.
- [ ] After submitting, confirm the confirmation screen or email.
