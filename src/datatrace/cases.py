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

    def public_context(self):
        return {
            "incident": self.description,
            "metric_contract": self.contract,
            "previous_sql": self.previous_sql,
            "current_sql": self.current_sql,
            "schema": {
                "orders": ["order_id INTEGER", "customer_id INTEGER", "order_date TEXT",
                           "status TEXT", "kind TEXT", "revenue_cents INTEGER"],
                "customers": ["customer_id INTEGER", "region TEXT"],
            },
            "snapshots": ["previous", "current"],
            "sql_dialect": "SQLite; metric queries return order_id, revenue_cents",
        }


def canonical_sql(contract):
    if contract["refund_policy"] is None:
        raise ValueError("Refund treatment is missing from the metric definition.")
    # Only fixed, application-owned ISO dates are used here, never a user SQL fragment.
    start, end = contract["start"], contract["end_exclusive"]
    refund = " AND kind <> 'refund'" if contract["refund_policy"] == "exclude" else ""
    return ("SELECT order_id, revenue_cents FROM orders "
            f"WHERE status = 'paid' AND order_date >= '{start}' "
            f"AND order_date < '{end}'{refund}")


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
