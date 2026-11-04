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

## Project description

DataTrace is an AI investigator for the question every analyst gets before a leadership review: "This metric jumped. Is it real, or is the dashboard wrong?"

You give it the previous and current SQL, two data snapshots, and the metric's definition, or simply a stakeholder's voice note and a dashboard screenshot. A Muse Spark agent then investigates like an analyst would. It replays old and new SQL on old and new data, forms hypotheses (duplicate join keys, dropped records, date and status boundaries, refund treatment), and tests each with bounded, read-only SQL in a local sandbox. It never sees raw rows, only the results of its own queries.

When it proposes a fix, an independent deterministic checker verifies the complete per-order result against the metric contract. A second model, Muse Wonder, reviews the diagnosis against the evidence and can send the agent back to revise. If the definition is incomplete, the agent pauses and asks the analyst instead of guessing.

In the flagship Black Friday incident (4,122 orders), DataTrace showed that of a +$129,045 jump, $115,080 was genuine growth and $13,966 was a CRM-migration join bug: $25,521 double-counted minus $11,555 dropped. It produced verified corrected SQL and a two-sentence CFO brief.

Across 320 paid benchmark runs against the same Meta model given all the raw rows and no tools, the agent scored 159/160 versus 150/160. On data that fits in a prompt both were accurate, but on realistic incidents the agent used 14× fewer input tokens and cost 4.3× less. At warehouse scale (42k orders, 2.06M tokens of raw data) the no-tools approach could not run at all (context_length_exceeded), while the agent solved 10/10.

## Meta products used

- **Meta Model API, Responses API** with client-side function calling, parallel tool calls, `previous_response_id` conversation state, reasoning effort control, reasoning summaries, and JSON-schema structured output.
- **muse-spark-1.3**: the investigator agent (tools `query_snapshot`, `verify_correction`, `request_clarification`) and vision intake from dashboard screenshots.
- **muse-wonder-1.0**: independent reviewer with a structured verdict, which triggers revision and writes the stakeholder brief.
- **muse-voice-transcribe-1.0** (`/v1/asr/transcribe`): voice-note intake.

## Why Meta models are important to the solution

The hard part of a metric investigation is judgement: deciding which hypothesis to test next, writing the right diagnostic query, and noticing when real growth and a bug are mixed together. Muse Spark does that judgement in a tool loop. Its 1M-token context and parallel tool calls let it plan several diagnostics per turn, and reasoning summaries let the analyst watch why it ran each query.

Using a different Meta model, Muse Wonder, as the reviewer gives an independent second opinion rather than self-grading. Voice and vision intake let a stakeholder start an investigation from a voice note or screenshot.

Local code supplies what a model shouldn't: sandboxed execution and a deterministic verifier, so a fix is only reported when it is proven order by order. The benchmark shows why the tool design matters. The same model without tools must read every raw row, which costs 14× more tokens and fails outright at warehouse scale.

## Feedback about Meta products

- The Responses API's `previous_response_id` made the multi-turn tool loop and the pause-and-resume clarification simple: the investigation resumes hours later from one ID.
- Parallel tool calls cut the flagship investigation from 85s (sequential, earlier prototype) to about 40–60s.
- Reasoning summaries are excellent for agent UX: we stream them into the live timeline.
- JSON-schema structured output was reliable for the reviewer verdict and intake draft.
- `context_length_exceeded` errors are clear and include the token count, which made the scale experiment easy to report honestly.
- Wishes: a documented way to cap spend hard (not only a notification), a field table for `/asr/transcribe` request options, and documentation of image-input limits.

## Feedback about partner technologies

No partner inference service was used. All inference ran on the Meta-hosted Model API.

## Before you click Submit

- [ ] Repository is public and opens without signing in.
- [ ] Video is 3:00 or less, plays in a private window, and shows the features built during the event.
- [ ] Read the consent checkbox text yourself before ticking it.
- [ ] After submitting, confirm the confirmation screen or email.
