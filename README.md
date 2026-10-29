# DataTrace

**Explain why a business metric changed—and test the explanation.**

DataTrace is a planned AI investigator for unexpected changes in SQL-based business metrics. It distinguishes calculation defects, genuine data changes, and incidents that need more evidence.

Built for the **Meta Global AI Developer Hackathon 2026**, Indie Developer track, **Build for Your World** theme.

## Status

Repository initialization and project planning. The investigation agent, Streamlit interface, synthetic cases, and evaluation runner are not implemented yet. No performance or accuracy results are claimed.

## Planned workflow

1. Supply previous/current SQL, previous/current data snapshots, and the metric definition.
2. A Meta model proposes hypotheses and selects diagnostic tools.
3. DuckDB executes bounded, read-only investigations against synthetic data.
4. Each conclusion cites executed queries and observed results.
5. A proposed SQL correction is checked in an isolated environment against metric invariants and regression checks.
6. Valid business changes are preserved; ambiguous definitions trigger a clarification request.

## Scope

- **Stack:** Python, DuckDB, Streamlit, Meta Model API.
- **Initial incidents:** duplicate joins, dropped records, incorrect date filters.
- **Demo cases:** broken calculation, real business growth, insufficient evidence.
- **Evaluation:** 20 synthetic incidents and a same-model baseline without execution tools.
- **No production database connections or automatic production changes in the prototype.**

## Meta API setup

The project owner has confirmed that a Meta Model API account exists. Credit application, billing readiness, API-key availability, and a successful project API call remain unverified.

Copy `.env.example` to a local `.env` and fill it privately when implementation begins. `.env` is ignored by Git. Never put a real API key in source code, issues, screenshots, or demo recordings.

The official quickstart currently uses an OpenAI-compatible client with `https://api.meta.ai/v1`, the `MODEL_API_KEY` environment variable, and `muse-spark-1.3`. These are initial configuration defaults, subject to an authenticated availability check. No model call has been made by this scaffold.

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
