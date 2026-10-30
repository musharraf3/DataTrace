# Evaluation plan

The 20 development fixtures, 20 reproducible stress cases, offline runner, and same-model/no-tools comparison tooling are implemented. Offline results measure deterministic logic, not AI accuracy. Actual live AI evaluation remains pending. The stress split varies values, new records, and period boundaries but uses the same incident families; it is not independent production validation.

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

Implementation: both arms receive the complete raw supported incident inputs.
The tool-assisted arm additionally receives four executed replay results and
can request adaptive queries/verification; the baseline receives no executed
results and makes one request with no tools. Both apply the same post-answer
missing-definition and contract-conflict guards. Raw model classifications
and proposed corrections are retained separately from the system result.
This compares complete systems with different execution budgets, not a pure
equal-compute reasoning ablation. Provider tokens, latency, and limits make
those differences visible.

Run `python -m datatrace.evaluate --mode compare --allow-paid --limit 1` first.
Add `--split stress` for the second set. Optional input/output token rates
produce an explicit approximate cost; absent rates stay unknown. Error cases
remain in classification and repair denominators. Unknown usage/repair
attempts from failed calls are flagged rather than treated as zero.

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
