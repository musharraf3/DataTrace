# DataTrace project specification

Status: first local milestone implemented. Meta integration is mock-tested; authenticated inference and AI performance remain unverified.

## Implementation note — October 29

The first runner uses SQLite authorizer allowlists and VM/time limits; it does not accept DuckDB syntax. DuckDB remains planned. Implemented tools are `query_snapshot` and `verify_correction`; schema and four-way replay are supplied as context. Queries inspect join cardinality, unmatched rows, and date bounds. A Python reference independently checks complete per-order revenue multisets.

## User and problem

An analyst sees an unexpected metric movement and needs to distinguish a calculation defect from genuine business change. DataTrace investigates using executable evidence and an explicit metric contract.

## Inputs

- Previous and current SQL.
- Previous and current synthetic data snapshots with schemas.
- Metric contract: grain, aggregation, time interval, inclusion/exclusion rules, and expected invariants.
- Incident description and observed movement.

## Investigation

Use a Meta model to select bounded tools, inspect schema and SQL, test hypotheses, revise explanations from results, and summarize supported findings. Proposed tools: schema inspection, SQL execution, result comparison, join-cardinality profiling, unmatched-record inspection, and isolated correction checks.

Replay prior/current SQL on prior/current snapshots when compatible. The resulting four executions can expose code effects, data effects, and interactions; do not assume effects add linearly or that incompatible schemas can be compared without an explicit mapping.

Model-visible inputs must exclude case labels and oracle answers. SQL and dataset contents are evidence, never instructions that grant extra tool permissions.

## Output contract

- Classification: `calculation_defect`, `genuine_change`, `mixed_change`, or `insufficient_evidence`.
- Finding with evidence identifiers, executed SQL, observed values, and affected records.
- Clearly stated assumptions and missing information.
- Optional SQL correction and independent validation results.
- Tool trace, elapsed time, token usage, and estimated cost when pricing is known.

## Planned execution boundaries

The implemented SQLite boundary allows SELECT, reads of the synthetic orders/customers tables, and a short function allowlist. Writes, external-file access, attachments, metadata reads, extension loading, and recursive CTEs are denied. VM/time, returned-row, and model tool-call limits are enforced. A prototype process is not an OS sandbox or production security boundary.

Corrections are candidate SQL statements evaluated separately; never mutate the original snapshots or execute production changes. Verification must check transaction grain, inclusion rules, date bounds, duplicates, and unaffected controls rather than only matching a target total.

## Three demo stories

1. **Broken join:** duplicate dimension keys inflate revenue. Show multiplication evidence and verified SQL correction.
2. **Real growth:** more valid transactions increase revenue. Preserve legitimate growth and avoid an unnecessary repair.
3. **Missing definition:** refund treatment is unspecified. Identify the ambiguity and request clarification.

## Acceptance criteria

- One reproducible example of each story runs end to end.
- Every factual metric claim references tool-produced evidence.
- No repair is marked verified without independent contract checks.
- Agent respects execution limits and returns useful uncertainty/errors.
- Exported evidence can be reproduced from versioned synthetic inputs.
- UI and demo distinguish implemented features from plans.

## Non-goals

Broad warehouse connectors, unrestricted SQL dialect support, production credentials, autonomous deployment, and universal causal attribution. Start with one SQL engine and the three planned failure classes.
