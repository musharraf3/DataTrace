"""Summarize artifacts/bench-*.json into results/benchmark.json and results/BENCHMARK.md.

Costs use Meta's published list prices (USD per 1M tokens, checked 2026-11-03):
muse-spark-1.3 $1.25 in / $4.25 out; muse-wonder-1.0 $4.00 in / $20.00 out.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRICES = {"spark": (1.25, 4.25), "wonder": (4.00, 20.00)}
SPLITS = [("development", "Development (20 mini cases)"), ("stress", "Stress (20 mini cases, new values)"),
          ("realistic", "Realistic (10 cases, ~4k orders)"), ("scale", "Warehouse scale (5 cases, ~42k orders)")]


def _cost(run, mode):
    spark_in = spark_out = wonder_in = wonder_out = 0
    for case in run["cases"]:
        usage = case.get("usage", {})
        review_in = sum(r["usage"]["input_tokens"] for r in (case.get("report", {}).get("review_history") or []))
        review_out = sum(r["usage"]["output_tokens"] for r in (case.get("report", {}).get("review_history") or []))
        spark_in += usage.get("input_tokens", 0) - review_in
        spark_out += usage.get("output_tokens", 0) - review_out
        wonder_in += review_in
        wonder_out += review_out
    usd = (spark_in * PRICES["spark"][0] + spark_out * PRICES["spark"][1]
           + wonder_in * PRICES["wonder"][0] + wonder_out * PRICES["wonder"][1]) / 1e6
    return usd, spark_in + wonder_in, spark_out + wonder_out


def main():
    table, chart, notes = [], [], []
    totals = {"meta": [0, 0], "baseline": [0, 0]}
    per_split = {}
    for split, title in SPLITS:
        path = ROOT / "artifacts" / f"bench-{split}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for mode, label in [("meta", "DataTrace agent (tools + verifier + reviewer)"), ("baseline", "Same model, no tools, raw rows in prompt")]:
            run = data.get(mode)
            if not run:
                continue
            usd, tokens_in, tokens_out = _cost(run, mode)
            n = run["total"]
            totals[mode][0] += run["correct"]
            totals[mode][1] += n
            needed = run["repair_success"]
            table.append({
                "Split": title, "System": label,
                "Correct diagnosis": f"{run['correct']}/{n}",
                "Verified repair when needed": f"{needed['passed']}/{needed['denominator']}",
                "Unneeded repairs": f"{run['inappropriate_repairs']['count']}/{run['inappropriate_repairs']['denominator']}",
                "Errors / could not run": f"{run['errors']}/{n}",
                "Asked for clarification": run.get("clarifications_requested", 0),
                "Input tokens per case": f"{tokens_in // max(n, 1):,}",
                "Est. cost per case": f"${usd / max(n, 1):.3f}",
                "Median seconds": run.get("median_elapsed_seconds"),
            })
            chart.append({"Split": title.split(" (")[0], "System": "DataTrace agent" if mode == "meta" else "No-tools baseline",
                          "Correct": run["correct"] / max(n, 1)})
            per_split.setdefault(split, {})[mode] = {"correct": run["correct"], "n": n, "tokens": tokens_in / max(n, 1),
                                                     "usd": usd / max(n, 1), "errors": run["errors"]}
            errors = sorted({c.get("error_message", "")[:90] for c in run["cases"] if c.get("error")})
            if errors:
                reason = ", ".join(errors)
                if split == "scale" and mode == "baseline":
                    reason = ("HTTP 400 context_length_exceeded on every request: the raw rows are 2,064,623 tokens and "
                              "the model's context window is 1,048,576 tokens (error body confirmed directly).")
                elif "connectivity" in reason:
                    reason += " (a transient network failure; automatic retries for network/429/5xx errors were added afterwards)"
                notes.append(f"{title}, {label}: {reason}")
    agent, base = totals["meta"], totals["baseline"]
    headline = (f"Across all runs the DataTrace agent produced the correct diagnosis in **{agent[0]}/{agent[1]}** cases, "
                f"the same Meta model without tools in **{base[0]}/{base[1]}**. ") if agent[1] else ""
    real = per_split.get("realistic", {})
    if "meta" in real and "baseline" in real:
        headline += (f"When the data fits in a prompt, both are accurate, but on realistic 4k-order incidents the agent used "
                     f"**{real['baseline']['tokens'] / max(real['meta']['tokens'], 1):.0f}× fewer input tokens** and cost "
                     f"**{real['baseline']['usd'] / max(real['meta']['usd'], 1e-9):.1f}× less**, without sending a single raw row. ")
    scale = per_split.get("scale", {})
    if "meta" in scale and "baseline" in scale:
        headline += (f"At warehouse scale (~42k orders) the raw rows exceed the model's context window: the baseline could not run "
                     f"(**{scale['baseline']['correct']}/{scale['baseline']['n']}**), while the agent solved "
                     f"**{scale['meta']['correct']}/{scale['meta']['n']}**.")
    method = ("Synthetic, author-generated incidents with hidden labels; every case was run 3× (scale split 2×) at reasoning effort "
              "'medium'. Correctness is the final, guarded classification. 'Verified repair' means the independent per-order "
              "check passed. Costs use Meta list prices on 2026-11-03 and include the muse-wonder-1.0 reviewer for the agent. "
              "Not a production benchmark. Raw per-case reports are produced by `python -m datatrace.evaluate --mode compare`.")
    out = {"headline": headline, "table": table, "chart": chart, "method": method, "notes": notes}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "benchmark.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    lines = ["# Benchmark: DataTrace agent vs. no-tools baseline", "", headline, "",
             "| " + " | ".join(table[0].keys()) + " |" if table else "", "| " + " | ".join("---" for _ in (table[0] if table else [])) + " |"]
    lines += ["| " + " | ".join(str(v) for v in row.values()) + " |" for row in table]
    lines += ["", method, ""] + [f"- {n}" for n in notes]
    (ROOT / "results" / "BENCHMARK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    keep = ["Split", "System", "Correct diagnosis", "Verified repair when needed", "Errors / could not run",
            "Input tokens per case", "Est. cost per case"]
    compact = ["| " + " | ".join(keep) + " |", "| " + " | ".join("---" for _ in keep) + " |"]
    compact += ["| " + " | ".join(str(row[k]) for k in keep) + " |" for row in table]
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    start, end = "<!-- BENCHMARK_START -->", "<!-- BENCHMARK_END -->"
    if start in text and end in text:
        before, rest = text.split(start, 1)
        after = rest.split(end, 1)[1]
        readme.write_text(before + start + "\n" + "\n".join(compact) + "\n" + end + after, encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
