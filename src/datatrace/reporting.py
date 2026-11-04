"""Portable reports with provenance, readable Markdown and explicit uncertainty."""

import copy
import json
import math
import hashlib
import platform
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from .inputs import fingerprint
from . import __version__


def source_fingerprint():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def estimate_cost(usage, input_rate=None, output_rate=None):
    if input_rate is None or output_rate is None:
        return None
    if any(not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate < 0
           for rate in [input_rate, output_rate]):
        raise ValueError("Token prices must be finite nonnegative USD per million tokens.")
    return {"estimated_usd": round((usage.get("input_tokens", 0) * input_rate +
                                    usage.get("output_tokens", 0) * output_rate) / 1000000, 8),
            "input_usd_per_million": input_rate, "output_usd_per_million": output_rate,
            "basis": "User-configured rates; excludes cache discounts, taxes, and other fees."}


# Meta list prices, USD per 1M tokens (dev.meta.ai pricing page, checked 2026-11-03).
LIST_PRICES = {"muse-spark-1.3": (1.25, 4.25), "muse-wonder-1.0": (4.00, 20.00)}


def list_price_usd(report):
    """Approximate list-price cost of a live run: agent tokens at Spark rates, review tokens at Wonder rates."""
    usage = report.get("usage") or {}
    if not usage.get("input_tokens"):
        return None
    reviews = report.get("review_history") or []
    review_in = sum(r.get("usage", {}).get("input_tokens", 0) for r in reviews)
    review_out = sum(r.get("usage", {}).get("output_tokens", 0) for r in reviews)
    spark_in, spark_out = LIST_PRICES["muse-spark-1.3"]
    wonder_in, wonder_out = LIST_PRICES["muse-wonder-1.0"]
    return round(((usage["input_tokens"] - review_in) * spark_in + (usage.get("output_tokens", 0) - review_out) * spark_out
                  + review_in * wonder_in + review_out * wonder_out) / 1e6, 4)


def enrich_report(report, incident):
    output = copy.deepcopy(report)
    output["report_version"] = 1
    output["generated_at"] = datetime.now(timezone.utc).isoformat()
    output["input_sha256"] = fingerprint(incident)
    output["metric_contract"] = incident.contract.copy()
    output["domain"] = getattr(incident, "domain", "revenue")
    output["sql_engine"] = "SQLite"
    output["application_version"] = __version__
    output["source_sha256"] = source_fingerprint()
    output["runtime"] = {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version}
    output["validation_scope"] = "Complete order/value multiset under the supplied metric contract."
    output["diagnosis_source"] = ("Meta model interpretation" if output["mode"] == "meta_live" else
                                  "Model baseline without execution tools" if output["mode"] == "meta_baseline" else
                                  "Deterministic contract diagnostics")
    return output


def markdown_report(report):
    lines = ["# DataTrace investigation", "", f"Mode: {report['mode']}",
             f"Generated: {report.get('generated_at', 'not recorded')}",
             f"Input SHA-256: {report.get('input_sha256', 'not recorded')}", "",
             "## Finding", "", report["classification"].replace("_", " ").title(), "",
             report["summary"]]
    if report.get("root_cause"):
        lines.extend(["", f"**Root cause:** {report['root_cause']}"])
    review = report.get("review")
    if review:
        lines.extend(["", "## Brief for leadership", "", review.get("stakeholder_brief", ""), "",
                      f"Independent review by {review.get('model')}: **{review.get('verdict')}**"
                      + (" (agent revised once after a challenge)" if len(report.get("review_history") or []) > 1 else "")])
        for concern in review.get("concerns", []):
            lines.append(f"- {concern}")
    reconciliation = report.get("reconciliation")
    if reconciliation:
        lines.extend(["", "## Revenue reconciliation", "",
            f"- Underlying change: {reconciliation['underlying_change_cents'] / 100:+,.2f} USD",
            f"- Prior reporting error: {reconciliation['previous_error_cents'] / 100:+,.2f} USD",
            f"- Current reporting error: {reconciliation['current_error_cents'] / 100:+,.2f} USD",
            f"- Affected orders: {reconciliation['affected_order_count']} in {reconciliation['current_evidence_id']}",
        ])
    lines.extend(["", "## SQL and data replay", "",
                  "| SQL version | Snapshot | Revenue (USD) | Rows | Evidence |",
                  "| --- | --- | ---: | ---: | --- |"])
    for row in report.get("replay", []):
        lines.append(f"| {row['sql_version']} | {row['snapshot']} | {row['revenue_cents']/100:,.2f} | "
                     f"{row['row_count']} | {row['evidence_id']} |")
    if report.get("correction_sql"):
        # Prefix code fences in untrusted SQL so they cannot terminate our fence.
        sql = report["correction_sql"].replace("```", "` ` `")
        lines.extend(["", "## Candidate SQL", "", "```sql", sql, "```"])
    if report.get("validation"):
        validation = report["validation"]
        lines.extend(["", "## Independent check", "", f"Verified: {validation['verified']}",
                      "", validation["reason"]])
    steps = [e for e in report.get("events") or [] if e.get("type") == "tool_call"]
    if steps:
        lines.extend(["", "## How the agent investigated", ""])
        results = {e.get("call_id"): e.get("result") or {} for e in report.get("events") or [] if e.get("type") == "tool_result"}
        for number, step in enumerate(steps, 1):
            result = results.get(step.get("call_id"), {})
            outcome = result.get("evidence_id") or ("rejected: " + str(result.get("error"))[:80] if "error" in result else "")
            label = {"query_snapshot": "Query", "verify_correction": "Verify fix",
                     "request_clarification": "Asked the analyst"}.get(step.get("tool"), step.get("tool"))
            detail = step.get("purpose") or step.get("question") or ""
            lines.append(f"{number}. **{label}**: {detail}" + (f" ({outcome})" if outcome else ""))
    cost = list_price_usd(report)
    lines.extend(["", "## Usage", "",
                  f"Elapsed: {report.get('elapsed_seconds', 0):.0f}s" + (f" · estimated list-price cost ${cost:.3f}" if cost else ""),
                  "", "```json", json.dumps(report.get("usage", {}), indent=2), "```",
                  "", "## Limits", "", report.get("limitations", "Not recorded."), "",
                  "The JSON report contains executed SQL, evidence rows, and tool traces."])
    return "\n".join(lines) + "\n"
