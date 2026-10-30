# Submission draft

Review after authenticated Meta validation. This is a local draft, not a
submitted entry. Replace pending URLs and report only observed live results.

## Team/project

- Project: DataTrace
- Track: Indie Developer
- Theme: Build for Your World
- Repository requested by owner: https://github.com/musharraf3/DataTrace
- Repository access/publication: unverified, connected tool returns 404.
- Video/live product: pending.
- Contributors: list every actual contributor; do not infer team membership.

## Project description

DataTrace helps analysts investigate unexpected changes in SQL-based revenue
metrics. Users provide previous/current SQL, data snapshots, and a metric
definition. The system replays the calculations, exposes affected orders, and
checks proposed corrections against an independent order-level reference.

The application distinguishes broken calculations, genuine business changes,
mixed incidents, and missing definitions. It preserves valid growth rather
than treating the old number as the repair target. A local interface supports
JSON/CSV imports, editable SQL, candidate verification, and portable execution
reports. The supported prototype uses an explicit order-revenue schema and
in-memory SQLite, with bounded read-only execution.

## Meta product use

The implemented integration uses Meta Model API's Responses interface. The
model can call query_snapshot and verify_correction in a bounded local tool
loop, review returned evidence, revise hypotheses, and provide a diagnosis
referencing actual execution IDs. The default configuration selects
muse-spark-1.3; account-level availability and a live acceptance run must be
confirmed before describing it as a demonstrated deployment.

## Why Meta matters

The intended model role is interpreting incident context and SQL, selecting
diagnostic queries, and revising an investigation from evidence. Local code
enforces the metric contract and independently checks repairs. This combines
model-driven investigation with reproducible execution rather than relying on
an unsupported explanation alone.

## Evaluation

The repository includes 20 development cases, 20 separately generated stress
cases, and tooling for a same-model/no-tools comparison. Offline checks are
deterministic regressions, not AI accuracy. Add actual Meta diagnosis counts,
repair attempts, validation results, elapsed time, and usage only after the
paid model evaluation runs. Preserve failures and denominators.

## Product/partner feedback

Complete from actual authenticated use. Do not invent API experience or
partner integration: the current implementation uses the Meta-hosted API
transport and no partner inference service.

## Agreement and submission

Review the official waiver and promotional-use checkbox personally. Final
video publication, agreement acceptance, and project submission remain
separate actions. The code package and draft do not imply those are complete.
