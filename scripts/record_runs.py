"""Capture real Meta agent runs for the app's 'Recorded live run' mode (billable).

Usage: python scripts/record_runs.py [--only realistic-crm_migration]
Writes examples/recorded/<kind>-<name>.json. Resume tokens are stripped.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from datatrace.cases import make_case  # noqa: E402
from datatrace.meta import MetaClient, investigate_meta  # noqa: E402
from datatrace.healthcare import SCENARIOS as CLAIMS, make_claims_case  # noqa: E402
from datatrace.scenarios import SCENARIOS, make_realistic_case  # noqa: E402

CHOICES = [("synpuf", name) for name in CLAIMS] + [("realistic", name) for name in SCENARIOS] + [
    ("classic", name) for name in ["duplicate_join", "growth", "ambiguous", "dropped_records", "date_filter"]]


def _public(report):
    return {key: value for key, value in report.items() if key != "resume_state"}


def record(choice):
    kind, name = choice
    case = (make_claims_case(name) if kind == "synpuf" else
            make_realistic_case(name) if kind == "realistic" else make_case(name, 1))
    client = MetaClient()
    report = investigate_meta(case, client=client, review=True)
    output = {"recorded_with": {"agent": client.model, "reviewer": client.review_model, "effort": client.effort},
              "report": _public(report)}
    if report.get("status") == "needs_clarification":
        answer = "include" if case.domain == "healthcare" else "exclude"  # Net paid is the claims convention.
        clarified = replace(case, contract={**case.contract, "refund_policy": answer})
        resumed = investigate_meta(clarified, client=client, review=True, resume=report["resume_state"], answer=answer)
        output.update(paused=_public(report), resumed=_public(resumed), report=_public(resumed))
    final = output["report"]
    destination = ROOT / "examples" / "recorded" / f"{kind}-{name}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=1), encoding="utf-8")
    return f"{kind}-{name}: expected={case.expected_classification} got={final['classification']} " \
           f"review={(final.get('review') or {}).get('verdict')} secs={final['elapsed_seconds']}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    choices = [c for c in CHOICES if not args.only or "-".join(c) in args.only]
    with ThreadPoolExecutor(5) as pool:
        for line in pool.map(lambda c: _safe(c), choices):
            print(line, flush=True)


def _safe(choice):
    try:
        return record(choice)
    except Exception as exc:  # Keep other recordings going.
        return f"{'-'.join(choice)}: FAILED {type(exc).__name__}: {exc}"


if __name__ == "__main__":
    main()
