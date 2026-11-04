"""Reproducible synthetic incidents. Gold labels never enter model context."""

from copy import deepcopy
from dataclasses import dataclass


@dataclass
class Incident:
    case_id: str
    description: str
    contract: dict
    snapshots: dict
    previous_sql: str
    current_sql: str
    expected_classification: str
    family: str
    domain: str = "revenue"

    def public_context(self):
        from .domains import get
        d = get(self.domain)
        contract = dict(self.contract)
        contract["status"] = d.status(contract["status"])
        contract["grain"] = f"one row per {d.key}"
        contract["customer_coverage"] = f"all {d.items}, including unmatched {d.member_noun}s"
        return {
            "incident": self.description,
            "domain": d.name,
            "metric_contract": contract,
            "previous_sql": self.previous_sql,
            "current_sql": self.current_sql,
            "schema": {
                d.fact: [f"{d.key} INTEGER", f"{d.member} INTEGER", f"{d.date} TEXT",
                         "status TEXT", "kind TEXT", f"{d.value} INTEGER"],
                d.dim: [f"{d.member} INTEGER", f"{d.attr} TEXT"],
            },
            "vocabulary": {"status": sorted(d.status_map.values()), "kind": sorted(d.kind_map.values()),
                           "refund_policy": f"whether {d.reversal_noun} (kind='{d.kind('refund')}') are included"},
            "snapshots": ["previous", "current"],
            "sql_dialect": f"SQLite; metric queries return {d.key}, {d.value} rows (integer cents)",
        }


def canonical_sql(contract, domain=None):
    from .domains import get
    from .inputs import validate_contract
    d = domain if hasattr(domain, "fact") else get(domain)
    contract = validate_contract(contract)
    if contract["refund_policy"] is None:
        raise ValueError("Refund treatment is missing from the metric definition.")
    # Contract validation admits ISO dates and enumerated statuses only.
    start, end = contract["start"], contract["end_exclusive"]
    refund = f" AND kind <> '{d.kind('refund')}'" if contract["refund_policy"] == "exclude" else ""
    return (f"SELECT {d.key}, {d.value} FROM {d.fact} "
            f"WHERE status = '{d.status(contract['status'])}' AND {d.date} >= '{start}' "
            f"AND {d.date} < '{end}'{refund}")


def make_case(family="duplicate_join", variant=0):
    if family not in {"duplicate_join", "dropped_records", "date_filter", "growth", "ambiguous"}:
        raise ValueError("Unknown synthetic incident family.")
    if variant not in range(4):
        raise ValueError("Variant must be between 0 and 3.")
    scale = variant + 1
    orders = [
        (1, 1, "2026-10-05", "paid", "sale", 10000 * scale),
        (2, 2, "2026-10-12", "paid", "sale", 20000 * scale),
        (3, 3, "2026-10-18", "paid", "sale", 30000 * scale),
        (4, 1, "2026-11-01", "paid", "sale", 4000 * scale),
        (5, 2, "2026-10-20", "pending", "sale", 9000 * scale),
    ]
    previous = {"orders": orders, "customers": [(1, "West"), (2, "East"), (3, "North")]}
    current = deepcopy(previous)
    contract = {"name": "Paid October revenue", "grain": "one row per order_id",
                "unit": "integer USD cents", "start": "2026-10-01",
                "end_exclusive": "2026-11-01", "status": "paid",
                "refund_policy": "exclude", "customer_coverage": "all orders, including unmatched customers"}
    prior = canonical_sql(contract)
    now = prior
    if family == "duplicate_join":
        current["customers"].append((2, "East"))
        now = prior.replace("FROM orders", "FROM orders JOIN customers USING (customer_id)")
    elif family == "dropped_records":
        current["customers"] = current["customers"][:2]
        now = prior.replace("FROM orders", "FROM orders JOIN customers USING (customer_id)")
    elif family == "date_filter":
        now = prior.replace("order_date <", "order_date <=")
    elif family == "growth":
        current["orders"].append((6, 1, "2026-10-25", "paid", "sale", 15000 * scale))
    else:
        current["orders"].append((6, 2, "2026-10-25", "paid", "refund", -5000 * scale))
        now = prior.replace(" AND kind <> 'refund'", "")
        contract["refund_policy"] = None
    # Some defective cases include legitimate growth; a repair must preserve it.
    if family in {"duplicate_join", "dropped_records", "date_filter"} and variant % 2:
        current["orders"].append((6, 1, "2026-10-25", "paid", "sale", 5000 * scale))
    expected = ("insufficient_evidence" if family == "ambiguous" else
                "genuine_change" if family == "growth" else
                "mixed_change" if variant % 2 else "calculation_defect")
    family_index = ["duplicate_join", "dropped_records", "date_filter", "growth", "ambiguous"].index(family)
    return Incident(f"incident-{family_index * 4 + variant + 1:02d}",
                    "Paid October revenue changed unexpectedly. Compare the SQL and snapshots; "
                    "establish whether the movement is supported by the metric definition.",
                    contract, {"previous": previous, "current": current}, prior, now, expected, family)


def all_cases():
    return [make_case(family, variant) for family in
            ["duplicate_join", "dropped_records", "date_filter", "growth", "ambiguous"]
            for variant in range(4)]


def heldout_cases(seed=236):
    """A versioned stress split with new transactions/distributions, not production validation."""
    import random
    rng = random.Random(seed)
    output = []
    for case in all_cases():
        case.case_id = "stress-" + case.case_id
        # The same order ID has a stable new value across snapshots. Add entirely
        # new included/excluded rows to expose cancellation and boundary mistakes.
        values = {row[0]: rng.randint(100, 80000) for row in case.snapshots["previous"]["orders"]}
        for snapshot in case.snapshots.values():
            snapshot["orders"] = [(*row[:5], -abs(values.get(row[0], row[5])) if row[4] == "refund"
                                    else values.get(row[0], row[5])) for row in snapshot["orders"]]
            snapshot["orders"] += [
                (101, 1, "2026-09-30", "paid", "sale", 13500),
                (102, 1, "2026-10-01", "paid", "sale", 1900),
                (103, 1, "2026-10-31", "paid", "sale", 27300),
                (104, 1, "2026-10-19", "cancelled", "sale", 91000),
            ]
        output.append(case)
    return output
