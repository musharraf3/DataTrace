# Completion plan

Scope: a complete local hackathon application for investigating a supported
order-level revenue metric. This scope does not promise arbitrary warehouse
schemas or autonomous production edits.

1. Validate incident bundles and four CSV snapshots, dates, IDs, amounts, and contracts.
2. Support custom SQL and explicit metric definitions; export reusable incident templates.
3. Run bounded read-only investigations and verify complete per-order results.
4. Supply all five demo families, manual candidate checks, and shareable reports.
5. Implement a same-model no-tools baseline, reproducible evaluation splits,
   raw per-case reports, usage/latency and configurable cost estimates.
6. Harden the Meta client against malformed responses, oversized inputs, and
   unbounded tool loops; keep live claims distinct from mocked validation.
7. Test custom-input round trips, adversarial SQL, repairs, agents, CLI and UI.
8. Provide setup scripts, container instructions, demo narrative, and final checklist.
9. Commit and publish when the supplied GitHub repository becomes accessible.

Completion evidence belongs in VALIDATION.md. Live inference, a real browser
check, remote publication, and the final video/submission are recorded as
pending until independently verified. Credentials must stay in local .env.

## Completion state

Items 1–8 are implemented and locally validated within the supported schema.
The local UI is exercised with Streamlit AppTest because browser/server
sockets are restricted in this environment. Item 9 is blocked by repository
access: the supplied GitHub URL returns 404 through the connected app.
Live model quality remains unmeasured; transport and orchestration have mock
tests. See VALIDATION.md for the exact test counts and external limits.
