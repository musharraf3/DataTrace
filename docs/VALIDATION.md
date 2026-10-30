# Application validation — October 29, 2026

## Completed locally

- Python 3.11.5; Streamlit 1.34.0; pytest 7.4.0.
- `python -m pytest -q`: **78 passed in 4.45 seconds**, including the evaluator failure-denominator test.
- `python -m datatrace.evaluate --mode offline`: **20/20 development cases**, 12/12 independently verified needed repairs, 0/8 inappropriate repairs.
- `python -m datatrace.evaluate --mode offline --split stress`: **20/20 stress cases**, 12/12 independently verified needed repairs, 0/8 inappropriate repairs. Both sets are deterministic regressions, not AI accuracy results.
- `python -m datatrace sample`, `investigate`, and `verify`: exercised through CLI regression tests and a real local report export.
- `python -m compileall -q src app.py run.py`: passed.
- `git diff --check`: passed before commit.
- Streamlit AppTest verifies reports, candidate verification, stale-result removal after incident/SQL changes, and disabled live mode without a key.
- Tests cover JSON/CSV round trips, schema/date/ID/contract rejection, more-than-100-row metrics, same-total row mistakes, writes/external I/O/metadata/recursive SQL rejection, row/VM limits, growth preservation, missing definitions, model consistency guards, fabricated references, malformed provider responses, unknown tools, call budgets, baseline isolation, pricing validation, credential destinations, CLI consent, and evaluation failure denominators.

## Environment-specific setup

Python was available through an existing Anaconda installation. A project-local virtual environment with access to existing installed packages was used. The editable package installed successfully after selecting a project-local temporary directory to avoid an old setuptools issue with braces in the sandbox temporary path. Fresh-network installation is documented in README but was not tested: package downloads fail in this environment.

## Still unverified

- Authenticated Meta inference, provider billing/credits, model availability, live model quality, and provider costs. Model-loop tests use mock responses; no inference accuracy is claimed.
- Browser rendering against a live local server: socket access is blocked by the execution environment (WinError 10013). The browser preview returned connection refused. Streamlit AppTest runs in process and passed; a real browser check remains pending.
- Remote publication: the supplied GitHub URL returned 404 through the connected GitHub app and in a signed-out browser. Local origin is set to `https://github.com/musharraf3/DataTrace.git`; no remote code was overwritten.
- Actual live model/baseline comparison results. The comparison tooling is implemented; no model result is fabricated.
- DuckDB backend is deferred. SQLite is the supported local backend in this version.
- Container build and fresh-network install have not been verified. Docker CLI is installed, but the Docker Desktop Linux engine pipe was unavailable, so no container build was attempted.

The supported local application scope is implemented. Do not present it as a completed hackathon submission, authenticated provider deployment, or production system. The demo video, agreements, publication, and final submission remain separate steps.
