"""Reproducible evaluation. Offline mode measures scripted fixtures, not AI quality.

Live modes compare the tool-using Meta agent against the same model without
tools (it receives the raw rows instead). Every failure stays in the denominator.
"""

import argparse
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .cases import all_cases, heldout_cases
from .investigator import offline_walkthrough
from .meta import MetaClient, investigate_meta, investigate_baseline
from .reporting import estimate_cost

SPLITS = ["development", "stress", "realistic"]


def split_cases(split):
    from .scenarios import realistic_cases
    if split == "development":
        return all_cases()
    if split == "stress":
        return heldout_cases()
    if split == "realistic":
        return realistic_cases()
    raise ValueError("Unknown evaluation split.")


def _run_case(case, mode, client, review):
    started = time.monotonic()
    try:
        report = (offline_walkthrough(case) if mode == "offline" else
                  investigate_meta(case, client=client, review=review) if mode == "meta" else
                  investigate_baseline(case, client=client))
        repair = report.get("correction_sql") is not None
        attempted = report.get("model_correction_sql", report.get("correction_sql")) is not None
        paused = report.get("status") == "needs_clarification"
        raw = "insufficient_evidence" if paused else report.get("model_classification")
        return {"case_id": case.case_id, "family": case.family, "expected": case.expected_classification,
                "actual": report["classification"], "correct": report["classification"] == case.expected_classification,
                "repair_proposed": repair,
                "raw_model_classification": raw if mode != "offline" else None,
                "raw_model_correct": raw == case.expected_classification if mode != "offline" else None,
                "clarification_requested": paused,
                "inappropriate_repair": attempted and case.family.endswith(("growth", "ambiguous", "refund_policy")),
                "repair_verified": (report.get("validation") or {}).get("verified", False),
                "repair_needed": case.expected_classification in {"calculation_defect", "mixed_change"},
                "review_verdict": (report.get("review") or {}).get("verdict"),
                "revised_after_review": len(report.get("review_history") or []) > 1,
                "elapsed_seconds": report.get("elapsed_seconds", 0),
                "usage": report.get("usage", {}), "report": report}
    except Exception as exc:
        return {"case_id": case.case_id, "family": case.family, "expected": case.expected_classification,
                "repair_needed": case.expected_classification in {"calculation_defect", "mixed_change"},
                "correct": False, "error": type(exc).__name__,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "error_message": str(exc)[:200], "usage_incomplete": mode != "offline"}


def evaluate(mode="offline", *, client=None, split="development", cases=None,
             input_rate=None, output_rate=None, review=False, workers=1, repeat=1):
    if mode not in {"offline", "meta", "baseline"}:
        raise ValueError("Mode must be offline, meta, or baseline.")
    if split not in SPLITS:
        raise ValueError("Unknown evaluation split.")
    selected = cases if cases is not None else split_cases(split)
    estimate_cost({}, input_rate, output_rate)  # Validate explicit rates before any paid request.
    if mode != "offline":
        client = client or MetaClient()  # Fail before the run if account configuration is missing.
    jobs = [case for _ in range(repeat) for case in selected]
    if workers > 1:
        with ThreadPoolExecutor(workers) as pool:
            results = list(pool.map(lambda case: _run_case(case, mode, client, review), jobs))
    else:
        results = [_run_case(case, mode, client, review) for case in jobs]
    for index, row in enumerate(results):
        row["repeat"] = index // max(1, len(selected))
    usage = {key: sum(row.get("usage", {}).get(key, 0) for row in results)
             for key in ["input_tokens", "output_tokens", "model_requests", "tool_calls"]}
    needed = [row for row in results if row.get("repair_needed")]
    unneeded = [row for row in results if row.get("expected") in {"genuine_change", "insufficient_evidence"}]
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                                  timeout=3, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                                    capture_output=True, text=True, timeout=3, check=True).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        revision, dirty = "not available", None
    timed = sorted(row.get("elapsed_seconds", 0) for row in results if "error" not in row)
    return {"mode": mode, "claim": "Synthetic fixture regression only; not AI accuracy." if mode == "offline"
            else "Author-generated synthetic cases; not production performance.",
            "dataset_version": "revenue-v3", "split": split, "repeat": repeat, "review": review,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "code_revision": revision, "working_tree_dirty": dirty,
            "source_sha256": next((row["report"]["source_sha256"] for row in results if "report" in row), None),
            "model": getattr(client, "model", None),
            "review_model": getattr(client, "review_model", None) if review else None,
            "total": len(results), "correct": sum(r["correct"] for r in results),
            "raw_model_correct": sum(bool(r.get("raw_model_correct")) for r in results) if mode != "offline" else None,
            "errors": sum("error" in r for r in results), "usage": usage,
            "cost_estimate": estimate_cost(usage, input_rate, output_rate) if mode != "offline" else None,
            "usage_incomplete": any(row.get("usage_incomplete", False) for row in results),
            "repair_success": {"passed": sum(row.get("repair_verified", False) for row in needed), "denominator": len(needed)},
            "inappropriate_repairs": {"count": sum(row.get("inappropriate_repair", False) for row in unneeded), "denominator": len(unneeded)},
            "unobserved_repair_attempts_due_to_errors": sum("error" in row for row in unneeded),
            "clarifications_requested": sum(row.get("clarification_requested", False) for row in results),
            "reviews_challenged": sum(row.get("review_verdict") == "challenged" for row in results),
            "median_elapsed_seconds": timed[len(timed) // 2] if timed else None,
            "elapsed_seconds": round(sum(row.get("elapsed_seconds", 0) for row in results), 3), "cases": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["offline", "meta", "baseline", "compare"], default="offline")
    parser.add_argument("--split", choices=SPLITS, default="development")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--review", action="store_true", help="Add the independent Muse Wonder reviewer.")
    parser.add_argument("--allow-paid", action="store_true", help="Explicitly allow billable Meta requests.")
    parser.add_argument("--input-rate", type=float, help="USD per million input tokens; supply current account pricing.")
    parser.add_argument("--output-rate", type=float, help="USD per million output tokens.")
    parser.add_argument("--output", default="artifacts/offline-evaluation.json")
    args = parser.parse_args()
    if not 1 <= args.limit <= 50 or not 1 <= args.repeat <= 5 or not 1 <= args.workers <= 12:
        parser.error("--limit 1–50, --repeat 1–5, --workers 1–12")
    if args.mode != "offline" and not args.allow_paid:
        parser.error("Meta modes require --allow-paid; they incur inference charges.")
    if args.mode != "offline":
        from dotenv import load_dotenv
        load_dotenv()
    cases = split_cases(args.split)[:args.limit]
    modes = ["meta", "baseline"] if args.mode == "compare" else [args.mode]
    runs = {mode: evaluate(mode, split=args.split, cases=cases, input_rate=args.input_rate,
                           output_rate=args.output_rate, review=args.review and mode == "meta",
                           workers=args.workers, repeat=args.repeat) for mode in modes}
    result = runs if args.mode == "compare" else runs[args.mode]
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    summaries = {mode: {key: value for key, value in run.items() if key != "cases"} for mode, run in runs.items()}
    print(json.dumps(summaries, indent=2))
    if any(run["errors"] for run in runs.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
