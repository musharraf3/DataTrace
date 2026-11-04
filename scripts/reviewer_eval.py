"""Does the muse-wonder-1.0 reviewer actually catch bad diagnoses? (billable, about $3)

Takes correct agent diagnoses from artifacts/bench-realistic.json, plants one known error per variant,
keeps unmodified copies as controls, and asks the reviewer about each. Writes results/reviewer_eval.json.
"""

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from datatrace.evaluate import split_cases  # noqa: E402
from datatrace.investigator import Investigation  # noqa: E402
from datatrace.meta import MetaClient, review_diagnosis  # noqa: E402


def _plant(kind, final, case):
    final = dict(final)
    if kind == "wrong_amount":
        # Inflate every dollar figure in the explanation by 40%.
        final["summary"] = re.sub(r"\$([\d,]+(?:\.\d+)?)", lambda m: "$" + f"{float(m.group(1).replace(',', '')) * 1.4:,.0f}",
                                  final["summary"])
    elif kind == "wrong_classification":
        final["classification"] = "genuine_change"
        final["summary"] = "All of the movement is genuine late-month growth; the calculation is correct and needs no change."
        final["root_cause"] = None
        final["correction_sql"] = None
    elif kind == "unverified_fix":
        final["correction_sql"] = case.current_sql  # The broken query itself, presented as the fix.
    elif kind == "fabricated_claim":
        final["summary"] += (" A timezone shift also moved 312 Nov 30 orders into December, which explains a further "
                             "$9,400 of the difference.")
    return final


def _job(args):
    client, case, report, kind = args
    session = Investigation(case)
    try:
        session.evidence = list(report["evidence"])
        replay = report["replay"]
        reconciliation = session.reconcile(session.replay())
        session.evidence = list(report["evidence"])  # Keep only the agent's evidence IDs.
        final = {k: report.get(k) for k in ["classification", "summary", "root_cause", "evidence_ids"]}
        final["classification"] = report["model_classification"]
        final["summary"] = report["model_summary"]
        final["correction_sql"] = report.get("model_correction_sql")
        if kind != "control":
            final = _plant(kind, final, case)
        validation = session.verify(final["correction_sql"]) if final.get("correction_sql") else None
        verdict = review_diagnosis(client, case, final, session, replay, reconciliation, validation)
        return {"case_id": case.case_id, "variant": kind, "verdict": verdict["verdict"],
                "concerns": verdict["concerns"], "usage": verdict["usage"]}
    except Exception as exc:
        return {"case_id": case.case_id, "variant": kind, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    finally:
        session.close()


def main():
    load_dotenv(ROOT / ".env")
    client = MetaClient()
    cases = {c.case_id: c for c in split_cases("realistic")}
    bench = json.loads((ROOT / "artifacts" / "bench-realistic.json").read_text(encoding="utf-8"))
    seen, jobs = set(), []
    for row in bench["meta"]["cases"]:
        report = row.get("report") or {}
        if (not row.get("correct") or report.get("status") != "complete" or row["case_id"] in seen
                or cases[row["case_id"]].contract["refund_policy"] is None):
            continue
        seen.add(row["case_id"])
        kinds = ["control", "wrong_amount", "fabricated_claim"]
        if report.get("model_classification") != "genuine_change":
            kinds += ["wrong_classification", "unverified_fix"]
        jobs += [(client, cases[row["case_id"]], report, kind) for kind in kinds]
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(_job, jobs))
    summary = {}
    for row in results:
        bucket = summary.setdefault(row["variant"], {"n": 0, "challenged": 0, "errors": 0})
        bucket["n"] += 1
        bucket["errors"] += "error" in row
        bucket["challenged"] += row.get("verdict") == "challenged"
    planted = [r for r in results if r["variant"] != "control" and "error" not in r]
    controls = [r for r in results if r["variant"] == "control" and "error" not in r]
    out = {"model": client.review_model, "summary": summary,
           "planted_caught": sum(r["verdict"] == "challenged" for r in planted), "planted_total": len(planted),
           "controls_passed": sum(r["verdict"] == "supported" for r in controls), "controls_total": len(controls),
           "method": ("Correctly classified muse-spark-1.3 diagnoses from the realistic benchmark; each variant plants "
                      "exactly one known error. 'Unmodified' are the agent's own diagnoses as written, which can still "
                      "contain unsupported details. The reviewer sees only evidence, contract checks and the diagnosis; "
                      "two deterministic rules (failed fix verification, genuine-change claim with a reconciled error) "
                      "are always blocking."),
           "results": results}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "reviewer_eval.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    main()
