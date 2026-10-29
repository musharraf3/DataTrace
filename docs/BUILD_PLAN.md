# Build plan and current status

Updated October 29, 2026 Pacific. Remaining schedule items are targets, not completion claims.

## Current state

- Hackathon approval: confirmed from prior conversation.
- Meta API account: owner confirms it exists.
- Cerebral Valley event, guide, waiver, submission fields, announcements, Discord gate, and livestream page: reviewed.
- Local Git repository and planning documents: initialized in this task.
- Owner supplied https://github.com/musharraf3/DataTrace ; configured as origin. The GitHub connection returned 404 and listed no accessible installations. Publication is unverified.
- Credits/billing/key/API request: not verified.
- Implemented locally: bounded SQLite runner, snapshot replay, per-order repair validation, scripted offline diagnostics, 20 synthetic fixtures, Meta Responses tool loop, evidence export, Streamlit UI, and evaluation runner.
- Live Meta API: mock-tested only; authenticated inference is unverified.
- DuckDB backend, held-out AI evaluation, and same-model/no-tools comparison: pending.
- Licensing: project distribution license not selected.

## Remaining schedule

| Date | Target |
| --- | --- |
| Oct 29 | Verify API readiness; implement bounded data runner, metric contract, and broken-join path |
| Oct 30 | Meta tool loop and evidence trace; watch Fireworks workshop if useful |
| Oct 31 | Genuine-change and insufficient-evidence cases; independent correction checks |
| Nov 1 | Focused Streamlit interface and reproducible three-case demo |
| Nov 2 | Held-out evaluation, diagnose failures, record honest results |
| Nov 3 | Stabilize; finalize README, live access, three-minute video, and submission answers |
| Nov 4 | Final access checks; aim to submit by 3 PM PT, official deadline 6 PM PT |

## Decisions carried forward

DataTrace, rather than RightCall, is the new hackathon project. RightCall was application evidence of prior technical work. Begin with the hosted Meta API; optional open-weight support should earn its place through working implementation, not be added solely to name more products. The agentic bonus is a relevant secondary target. Focus on a verified product and demo before optional awards.

## Next executable milestone

Resolve GitHub access and publish the tested code. Configure the API key locally and run one authenticated Meta investigation, then collect live evaluation results and implement the no-tools comparison. Offline broken-join, growth, and ambiguity paths are available now. The first runner uses SQLite because DuckDB package downloads were unavailable.
