"""Healthcare claims incidents built on real-format CMS DE-SynPUF inpatient claims.

What is real (from the public-domain synthetic files): claim IDs, beneficiaries, service dates, paid
amounts, Medicare Advantage (HMO) coverage months and death dates. What is simulated, seeded and
disclosed: claim processing lag (run-out), pending adjudication, claim reversals, the two data
snapshots, and the reporting defect in each incident.

Story: "Paid inpatient claims for the service month" is reported from a claims warehouse. The previous
snapshot was taken mid-run-out, the current one six weeks later, so some growth is genuine run-out.
"""

import json
import random
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from .cases import Incident, canonical_sql
from .domains import HEALTHCARE

EXTRACT = Path(__file__).resolve().parents[2] / "examples" / "synpuf" / "inpatient_extract.json"
ENROLLMENT = EXTRACT.with_name("enrollment_extract.json")

SCENARIOS = {
    "eligibility_spans": {"title": "Eligibility rebuild double-counts members", "expected": "mixed_change",
                          "note": "This month the eligibility table was rebuilt as one row per coverage span, and the "
                                  "report now joins it to break paid claims out by plan."},
    "service_date_cutoff": {"title": "Service-month cutoff edit", "expected": "mixed_change",
                            "note": "The report query was edited to 'include the last day of the month'."},
    "pending_counted": {"title": "Pending claims counted as paid", "expected": "mixed_change",
                        "note": "The report query was edited so claims still in adjudication appear sooner."},
    "runout_growth": {"title": "Genuine claims run-out", "expected": "genuine_change",
                      "note": "No change to the report query was deployed between refreshes."},
    "reversal_policy": {"title": "Reversal treatment undefined", "expected": "insufficient_evidence",
                        "note": "The report query was simplified; nobody documented whether reversals net against paid."},
}

MONTHS = {"2009-11": ("2009-11-01", "2009-12-01", "2009-12-18", "2010-01-31"),
          "2009-05": ("2009-05-01", "2009-06-01", "2009-06-18", "2009-07-31")}


@lru_cache(maxsize=1)
def _extract():
    return json.loads(EXTRACT.read_text(encoding="utf-8"))


def _iso(yyyymmdd):
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def _build(month, seed):
    start, end, prev_cut, curr_cut = MONTHS[month]
    data = _extract()
    rng = random.Random(f"{month}-{seed}")
    lo = (date.fromisoformat(start) - timedelta(days=7)).isoformat()
    hi = (date.fromisoformat(end) + timedelta(days=5)).isoformat()
    claims = [c for c in data["claims"] if lo <= _iso(c["from"]) <= hi]
    benes = data["beneficiaries"]
    member_ids = {bene: index for index, bene in enumerate(sorted({c["bene"] for c in claims}), start=1)}
    facts = _facts(claims, member_ids, rng)

    def snapshot(cut):
        return _snapshot(facts, cut)

    def plan(bene):
        return "Medicare Advantage" if benes[bene]["hmo_months"] == 12 else "Original Medicare"

    previous_elig = [(member_ids[b], plan(b)) for b in sorted(member_ids)]
    span_elig = []
    for bene in sorted(member_ids):
        info = benes[bene]
        if info["death"]:
            continue  # The rebuild filtered out deceased members.
        if 0 < info["hmo_months"] < 12:  # Mid-year coverage switch: two spans, two rows.
            span_elig += [(member_ids[bene], "Original Medicare"), (member_ids[bene], "Medicare Advantage")]
        else:
            span_elig.append((member_ids[bene], plan(bene)))
    return start, end, prev_cut, curr_cut, snapshot(prev_cut), snapshot(curr_cut), previous_elig, span_elig


def _facts(claims, member_ids, rng):
    """Simulated adjudication: processing lag (run-out), zero-paid denials and occasional reversals."""
    facts = []  # (claim_id, member, service_date, processed_date, status, kind, cents)
    for claim in claims:
        thru = date.fromisoformat(_iso(claim["thru"]))
        processed = thru + timedelta(days=int(rng.lognormvariate(2.3, 0.7)))  # median ~10 days of run-out
        status = "cancelled" if claim["paid_cents"] == 0 else "paid"
        facts.append([claim["clm_id"], member_ids[claim["bene"]], _iso(claim["from"]), processed.isoformat(),
                      status, "sale", claim["paid_cents"]])
        if claim["paid_cents"] > 0 and rng.random() < 0.025:  # Simulated full reversal and later re-adjudication
            reversed_on = processed + timedelta(days=rng.randint(10, 35))
            facts.append([claim["clm_id"] * 10 + 1, member_ids[claim["bene"]], _iso(claim["from"]),
                          reversed_on.isoformat(), "paid", "refund", -claim["paid_cents"]])
    return facts


def _snapshot(facts, cut):
    """What the warehouse held on a refresh date: claims processed by then, recent ones still pending."""
    rows = []
    for cid, member, service, processed, status, kind, cents in facts:
        if processed > cut:
            continue
        settled = (date.fromisoformat(cut) - date.fromisoformat(processed)).days >= 6
        rows.append((cid, member, service, status if settled or status != "paid" else "pending", kind, cents))
    return sorted(rows)


def make_claims_case(kind="eligibility_spans", month="2009-11", seed=1):
    if kind not in SCENARIOS or month not in MONTHS:
        raise ValueError("Unknown healthcare scenario or month.")
    start, end, prev_cut, curr_cut, previous, current, previous_elig, span_elig = _build(month, seed)
    d = HEALTHCARE
    label = date.fromisoformat(start).strftime("%B %Y")
    contract = {"name": f"Paid inpatient claims, {label} service month", "grain": "one row per order_id",
                "unit": "integer USD cents", "start": start, "end_exclusive": end, "status": "paid",
                "refund_policy": "include", "customer_coverage": "all orders, including unmatched customers"}
    prior_sql = canonical_sql(contract, d)
    current_sql, current_elig = prior_sql, previous_elig
    if kind == "eligibility_spans":
        current_elig = span_elig
        current_sql = (f"SELECT c.claim_id, c.paid_cents\nFROM claims c\nJOIN eligibility e ON e.member_id = c.member_id\n"
                       f"WHERE c.status = 'paid'\n  AND c.service_date >= '{start}'\n  AND c.service_date < '{end}'")
    elif kind == "service_date_cutoff":
        current_sql = prior_sql.replace(f"service_date < '{end}'", f"service_date <= '{end}'")
    elif kind == "pending_counted":
        current_sql = prior_sql.replace("status = 'paid'", "status IN ('paid', 'pending')")
    elif kind == "reversal_policy":
        current_sql = prior_sql + " AND kind <> 'reversal'"
        contract["refund_policy"] = None
    snapshots = {"previous": {"orders": previous, "customers": previous_elig},
                 "current": {"orders": current, "customers": current_elig}}
    incident = Incident(f"synpuf-{kind}-{month}", "", contract, snapshots, prior_sql, current_sql,
                        SCENARIOS[kind]["expected"], "synpuf_" + kind, "healthcare")
    incident.description = _describe(incident, label, prev_cut, curr_cut, SCENARIOS[kind]["note"])
    return incident


def _describe(incident, label, prev_cut, curr_cut, note):
    from .runner import QueryRunner
    totals = []
    for sql, snap in [(incident.previous_sql, "previous"), (incident.current_sql, "current")]:
        runner = QueryRunner(incident.snapshots[snap], domain="healthcare")
        try:
            totals.append(sum(row[1] for row in runner.query(sql, max_rows=200000)["rows"]))
        finally:
            runner.close()
    change = (totals[1] - totals[0]) / totals[0] * 100 if totals[0] else 0
    return (f"Claims dashboard: paid inpatient claims for the {label} service month moved from "
            f"${totals[0] / 100:,.0f} (refresh of {prev_cut}) to ${totals[1] / 100:,.0f} (refresh of {curr_cut}), "
            f"{change:+.0f}%. Some run-out is expected as late claims are adjudicated, but the finance and "
            f"actuarial leads need to know how much of this is real before the monthly cost review. {note} "
            "Data: CMS DE-SynPUF inpatient claims (public, synthetic) with simulated processing lag.")


def healthcare_cases():
    return [make_claims_case(kind, month) for month in MONTHS for kind in SCENARIOS]


# ------------------------------------------------------------------ rate metrics (PMPM, per 1,000)

RATE_SCENARIOS = {
    "pmpm_coverage_lines": {
        "title": "Enrollment rebuilt with one row per coverage line", "expected": "mixed_change", "kind": "pmpm",
        "note": "This month the enrollment table was rebuilt with one row per member, month and coverage line "
                "(medical, pharmacy). The denominator query did not change. Care management would like to report "
                "the drop as a program win."},
    "utilization_coverage_lines": {
        "title": "Admissions per 1,000 after the enrollment rebuild", "expected": "mixed_change", "kind": "per_1000",
        "note": "This month the enrollment table was rebuilt with one row per member, month and coverage line "
                "(medical, pharmacy). The denominator query did not change."},
    "pmpm_runout_growth": {
        "title": "Genuine PMPM run-out", "expected": "genuine_change", "kind": "pmpm",
        "note": "No change to the report or the enrollment table was deployed between refreshes."},
}


@lru_cache(maxsize=1)
def _enrollment():
    return json.loads(ENROLLMENT.read_text(encoding="utf-8"))


def _enrolled(row, month_start):
    """Enrolled for the month: full-year Part A coverage, alive on the first of the month.

    The 2009 summary gives coverage month counts, not which months, so members with partial Part A
    coverage are left out of the population rather than guessed."""
    _, part_a, _, _, death = row
    return part_a == 12 and (death is None or death >= month_start.replace("-", ""))


def make_rate_case(kind="pmpm_coverage_lines", month="2009-11", seed=1):
    """Inpatient PMPM or admissions per 1,000 for one state's whole 2009 Medicare population.

    Real (DE-SynPUF): the population, Part A/Part D/HMO coverage, death dates, claims and paid amounts.
    Simulated and disclosed: processing lag, reversals, the snapshots and the enrollment rebuild."""
    if kind not in RATE_SCENARIOS or month not in MONTHS:
        raise ValueError("Unknown rate scenario or month.")
    scenario = RATE_SCENARIOS[kind]
    start, end, prev_cut, curr_cut = MONTHS[month]
    roster = _enrollment()
    population = {row[0]: row for row in roster["beneficiaries"] if _enrolled(row, start)}
    lo = (date.fromisoformat(start) - timedelta(days=7)).isoformat()
    hi = (date.fromisoformat(end) + timedelta(days=5)).isoformat()
    claims = [c for c in _extract()["claims"] if lo <= _iso(c["from"]) <= hi and c["bene"] in population]
    member_ids = {bene: index for index, bene in enumerate(sorted(population), start=1)}
    facts = _facts(claims, member_ids, random.Random(f"rate-{month}-{seed}"))
    plan = {bene: "Medicare Advantage" if row[3] == 12 else "Original Medicare" for bene, row in population.items()}
    eligibility = [(member_ids[b], plan[b]) for b in sorted(population)]
    label_month = month  # YYYY-MM
    medical = [(member_ids[b], label_month, "medical") for b in sorted(population)]
    rebuilt = sorted(medical + [(member_ids[b], label_month, "pharmacy") for b in sorted(population)
                                if population[b][2] == 12])
    current_months = medical if kind == "pmpm_runout_growth" else rebuilt
    d = HEALTHCARE
    label = date.fromisoformat(start).strftime("%B %Y")
    rate_kind = scenario["kind"]
    contract = {"name": (f"Inpatient PMPM, {label} service month" if rate_kind == "pmpm" else
                         f"Inpatient admissions per 1,000, {label} service month"),
                "grain": "one row per order_id", "unit": "integer USD cents", "start": start, "end_exclusive": end,
                "status": "paid", "refund_policy": "include" if rate_kind == "pmpm" else "exclude",
                "customer_coverage": "all orders, including unmatched customers", "rate": {"kind": rate_kind}}
    numerator_sql = canonical_sql(contract, d)
    denominator_sql = f"SELECT member_id, month\nFROM member_months\nWHERE month = '{label_month}'"
    snapshots = {"previous": {"orders": _snapshot(facts, prev_cut), "customers": eligibility, "member_months": medical},
                 "current": {"orders": _snapshot(facts, curr_cut), "customers": eligibility,
                             "member_months": current_months}}
    incident = Incident(f"synpuf-{kind}-{month}", "Rate incident.", contract, snapshots, numerator_sql, numerator_sql,
                        scenario["expected"], "synpuf_" + kind, "healthcare", denominator_sql, denominator_sql)
    incident.description = _describe_rate(incident, label, prev_cut, curr_cut, scenario["note"], len(population))
    return incident


def _describe_rate(incident, label, prev_cut, curr_cut, note, members):
    from .investigator import Investigation
    from .rates import label as show
    session = Investigation(incident)
    try:
        replay, denominator = session.replay(), session.replay_denominator()
    finally:
        session.close()
    kind = incident.contract["rate"]["kind"]
    values = []
    for numerator, months in [(replay[0], denominator[0]), (replay[3], denominator[3])]:
        value = (numerator["revenue_cents"] / 100 if kind == "pmpm" else numerator["row_count"] * 12000) / months["member_months"]
        values.append(value)
    change = (values[1] - values[0]) / values[0] * 100 if values[0] else 0
    what = "inpatient cost per member per month (PMPM)" if kind == "pmpm" else "inpatient admissions per 1,000 member-years"
    return (f"Medical economics dashboard: {what} for the {label} service month moved from {show(values[0], kind)} "
            f"(refresh of {prev_cut}) to {show(values[1], kind)} (refresh of {curr_cut}), {change:+.0f}%. "
            f"Late claims are still being adjudicated, so some movement is expected. The population is every "
            f"2009 Medicare beneficiary in California with full-year Part A coverage ({members:,} members). {note} "
            "Data: CMS DE-SynPUF claims and beneficiary summary (public, synthetic) with simulated processing lag.")


def rate_cases():
    return [make_rate_case(kind) for kind in RATE_SCENARIOS]
