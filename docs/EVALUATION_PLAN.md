# Evaluation plan

The 20 synthetic fixtures and offline regression runner are implemented. Offline results measure scripted logic, not AI accuracy. Live AI evaluation, the same-model/no-tools comparison, and held-out evaluation remain pending.

## Proposed 20-case set

| Category | Count |
| --- | --- |
| Duplicate-join defects | 4 |
| Dropped-record defects | 4 |
| Date-filter defects | 4 |
| Genuine business changes, no defect | 4 |
| Ambiguous incidents requiring clarification | 4 |
| Total | 20 |

Include mixed code/data movement within defect cases, and use materially different data distributions rather than only renaming the same example. Keep demo/tuning cases separate from held-out evaluation cases and disclose both groups.

## Ground truth

Each case contains synthetic tables and seeds, prior/current SQL, the user-visible metric contract, a hidden diagnosis label, expected affected records, independent oracle queries, invariant checks, and repair-needed status. Do not give the agent case names, hidden labels, generator defect parameters, oracle SQL, or target answers. Track case-set and code versions.

## Comparison

1. Tool-assisted Meta investigator.
2. Same Meta model without execution tools.

Give both the same user-visible incident information. Document any practical differences in context and budgets. Record exact model ID, prompt version, reasoning settings, token/tool limits, and run date. Use a documented shared output schema and scoring rubric. Report stochastic reruns separately if budget permits.

## Measurements

- Diagnosis classification and defect-location accuracy.
- Evidence correctness: claimed values match independently reproduced queries.
- Repair correctness among repair-needed cases, checked against hidden contract/oracle tests.
- Inappropriate repair rate on real-growth/ambiguous cases; disclose denominator.
- Correct clarification rate and quality of requested missing information.
- Regression-check pass rates, including unaffected controls.
- Elapsed time, model and tool calls, input/output tokens.
- Estimated monetary cost from recorded usage and dated provider pricing; clearly mark unavailable pricing.

Keep raw counts alongside percentages. Do not claim representative production accuracy from this small author-generated synthetic set. Record failures, execution errors, and timeouts rather than silently dropping cases.

## Independent verification

Metric contract/oracle checks must be authored independently of a candidate correction. Never score a repair solely because its metric matches the old snapshot. Genuine growth should remain visible after any valid correction.

## Planned output

`artifacts/evaluation/<run-id>/` will contain a versioned manifest, per-case outcomes, model/tool traces without credentials, usage, and aggregate metrics. This directory is ignored initially to prevent accidental commits; select and scrub reproducible evaluation evidence for the final public submission.
