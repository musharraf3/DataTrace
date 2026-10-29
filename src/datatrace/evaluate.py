"""Reproducible evaluation. Offline mode measures scripted fixtures, not AI quality."""

import argparse
import json
from pathlib import Path

from .cases import all_cases
from .investigator import offline_walkthrough
from .meta import investigate_meta


def evaluate(mode="offline", *, client=None):
    if mode not in {"offline", "meta"}:
        raise ValueError("Mode must be offline or meta.")
    results = []
    for case in all_cases():
        try:
            report = offline_walkthrough(case) if mode == "offline" else investigate_meta(case, client=client)
            repair = report.get("correction_sql") is not None
            results.append({"case_id": case.case_id, "expected": case.expected_classification,
                            "actual": report["classification"], "correct": report["classification"] == case.expected_classification,
                            "repair_proposed": repair,
                            "inappropriate_repair": repair and case.family in {"growth", "ambiguous"},
                            "repair_verified": (report.get("validation") or {}).get("verified", False),
                            "usage": report.get("usage", {})})
        except Exception as exc:
            results.append({"case_id": case.case_id, "correct": False, "error": type(exc).__name__})
    return {"mode": mode, "claim": "Synthetic fixture regression only; not AI accuracy." if mode == "offline"
            else "Author-generated synthetic cases; not production performance.",
            "total": len(results), "correct": sum(r["correct"] for r in results),
            "errors": sum("error" in r for r in results), "cases": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["offline", "meta"], default="offline")
    parser.add_argument("--output", default="artifacts/offline-evaluation.json")
    args = parser.parse_args()
    if args.mode == "meta":
        from dotenv import load_dotenv
        load_dotenv()
    result = evaluate(args.mode)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, indent=2))
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
