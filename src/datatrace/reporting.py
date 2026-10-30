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


def enrich_report(report, incident):
    output = copy.deepcopy(report)
    output["report_version"] = 1
    output["generated_at"] = datetime.now(timezone.utc).isoformat()
    output["input_sha256"] = fingerprint(incident)
    output["metric_contract"] = incident.contract.copy()
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
             report["summary"], "", "## SQL and data replay", "",
             "| SQL version | Snapshot | Revenue (USD) | Rows | Evidence |",
             "| --- | --- | ---: | ---: | --- |"]
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
    lines.extend(["", "## Usage", "", "```json", json.dumps(report.get("usage", {}), indent=2), "```",
                  "", "## Limits", "", report.get("limitations", "Not recorded."), "",
                  "The JSON report contains executed SQL, evidence rows, and tool traces."])
    return "\n".join(lines) + "\n"
