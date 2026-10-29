# DataTrace

**Explain why a business metric changed—and test the explanation.**

DataTrace investigates SQL metric movements through executed evidence and independent repair checks. It distinguishes calculation defects, genuine data changes, mixed changes, and incidents that need more evidence.

Built for the **Meta Global AI Developer Hackathon 2026**, Indie Developer track, **Build for Your World** theme.

## Status

The first local milestone includes a Streamlit interface, three synthetic demo stories, 20 fixture cases, four-way SQL/snapshot replay, bounded SQL queries, independent per-order repair checks, evidence export, and a Meta Responses API tool loop. Offline mode runs scripted diagnostics; **it is not an AI system or an AI accuracy benchmark**. Live Meta behavior is tested with mock responses only; authenticated inference remains unverified.

The current SQL runner is **SQLite**, available in Python's standard library. DuckDB package downloads were blocked in the development environment, so DuckDB migration remains planned. No production performance is claimed.

## Run locally

Requires Python 3.11+ and package-index access for a fresh install.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m streamlit run app.py
```

On macOS/Linux use `.venv/bin/python` instead. Choose **Offline evidence walkthrough** and click **Investigate metric change**; no API key is needed for this mode.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m datatrace.evaluate --mode offline
```

For a paid Meta evaluation after setup, run `python -m datatrace.evaluate --mode meta --output artifacts/meta-evaluation.json` with the installed environment's Python. The same-model/no-tools baseline, held-out AI evaluation, and monetary cost estimates remain pending.

## Planned workflow

1. Supply previous/current SQL, previous/current data snapshots, and the metric definition.
2. A Meta model proposes hypotheses and selects diagnostic tools.
3. The in-memory SQLite runner executes bounded, read-only investigations against synthetic data.
4. Each conclusion cites executed queries and observed results.
5. A proposed SQL correction is checked in an isolated environment against metric invariants and regression checks.
6. Valid business changes are preserved; ambiguous definitions trigger a clarification request.

## Scope

- **Current stack:** Python, SQLite, Streamlit, Meta Model API. DuckDB remains planned.
- **Initial incidents:** duplicate joins, dropped records, incorrect date filters.
- **Demo cases:** broken calculation, real business growth, insufficient evidence.
- **Evaluation:** 20 synthetic incidents and a same-model baseline without execution tools.
- **No production database connections or automatic production changes in the prototype.**

## Meta API setup

The project owner has confirmed that a Meta Model API account exists. Credit application, billing readiness, API-key availability, and a successful project API call remain unverified.

Copy `.env.example` to a local `.env` and fill it privately. `.env` is ignored by Git. Never put a real API key in source code, issues, screenshots, or demo recordings. Restart the app, select Live Meta investigator, and explicitly run it. This sends the bundled synthetic incident to Meta and uses billable inference.

The default endpoint is `https://api.meta.ai/v1`, key environment variable `MODEL_API_KEY`, and model `muse-spark-1.3`. The transport uses the [official Responses tool-calling pattern](https://dev.meta.ai/docs/tool-calling), matched call IDs, and previous-response context. It restricts credentials to the official endpoint and blocks redirects. Two local tools are available: `query_snapshot` and `verify_correction`. Model-selected tools are capped at 12 calls and SQL queries at two seconds/200,000 VM steps. Tokens and request counts are recorded; costs are not invented.

Each final diagnosis must reference executed evidence. Repairs are checked independently against complete per-order values rather than only the old metric total. SQLite authorization denies writes, attachments, metadata reads, recursive CTEs, and functions outside an allowlist. This is a local synthetic-data prototype, not an OS sandbox or a production database service. Evidence references alone do not prove every sentence in a model explanation is correct.

## Project documents

- [Verified hackathon brief](docs/HACKATHON_BRIEF.md)
- [Project specification](docs/PROJECT_SPEC.md)
- [Evaluation plan](docs/EVALUATION_PLAN.md)
- [Submission checklist](docs/SUBMISSION_CHECKLIST.md)
- [Build plan and current status](docs/BUILD_PLAN.md)
- [Official resource links](docs/RESOURCES.md)

## Competition requirements

Public repository, meaningful Meta model use, event-built contributions, accessible three-minute demo video, and one submission per project. Submit by **November 4, 2026, 6:00 PM Pacific / 9:00 PM Eastern**. Verify the latest organizer updates before submitting.

Source: [Participant guide](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/details), reviewed October 28, 2026 Pacific.

## Ownership and dependencies

Follow the licenses of all third-party dependencies and datasets. A project distribution license has not yet been selected. Public repository visibility alone does not grant an open-source license. Use synthetic data for the submitted prototype.
