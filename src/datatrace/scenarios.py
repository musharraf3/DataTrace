"""Realistic, seeded e-commerce incidents at analyst scale (thousands of orders).

Story: a finance dashboard reports *Paid November revenue*. The previous
snapshot was refreshed on Nov 24; the current one on the morning of Dec 1,
after Black Friday (Nov 27) and Cyber Monday (Nov 30). Some revenue growth is
real. Each scenario adds (or does not add) one realistic reporting defect.

Gold labels live only on the Incident object and never enter model context.
"""

import random
from datetime import date, timedelta

from .cases import Incident, canonical_sql

REGIONS = ["North America", "EMEA", "APAC", "LATAM"]

SCENARIOS = {
    "crm_migration": {
        "title": "Black Friday + CRM migration",
        "expected": "mixed_change",
        "change_note": "Current SQL joins the migrated CRM customers table to add a region breakdown.",
    },
    "cutoff_change": {
        "title": "Month-end cutoff edit",
        "expected": "mixed_change",
        "change_note": "Current SQL was edited to 'include the last day of the month'.",
    },
    "status_filter": {
        "title": "Pending orders counted as paid",
        "expected": "mixed_change",
        "change_note": "Current SQL was edited so that orders awaiting payment capture show up sooner.",
    },
    "holiday_growth": {
        "title": "Genuine holiday surge",
        "expected": "genuine_change",
        "change_note": "No SQL change was deployed between refreshes.",
    },
    "refund_policy": {
        "title": "Refund treatment undefined",
        "expected": "insufficient_evidence",
        "change_note": "Current SQL was simplified; nobody wrote down how refunds should be treated.",
    },
}

CONTRACT = {"name": "Paid November revenue", "grain": "one row per order_id",
            "unit": "integer USD cents", "start": "2026-11-01", "end_exclusive": "2026-12-01",
            "status": "paid", "refund_policy": "exclude",
            "customer_coverage": "all orders, including unmatched customers"}


def _amount(rng):
    # Long-tailed basket sizes: mostly $25–$250, some large B2B baskets.
    cents = int(rng.lognormvariate(8.9, 0.75))
    return max(899, min(cents, 450000))


def _daily_volume(day, rng):
    base = 95
    if day == date(2026, 11, 27):      # Black Friday
        base = 360
    elif day == date(2026, 11, 30):    # Cyber Monday
        base = 300
    elif day in {date(2026, 11, 28), date(2026, 11, 29)}:
        base = 190
    elif day == date(2026, 11, 26):    # Thanksgiving
        base = 70
    return max(10, int(rng.gauss(base, base * 0.08)))


def _build(seed, scale=1):
    rng = random.Random(seed)
    customers = [(cid, rng.choice(REGIONS)) for cid in range(1, 1400 * scale + 1)]
    orders = []
    order_id = 100000
    day = date(2026, 10, 27)
    while day <= date(2026, 12, 1):
        for _ in range(_daily_volume(day, rng) * scale):
            order_id += 1
            customer = rng.randint(1, 1460 * scale)  # ~4% of orders come from customers not yet synced to CRM
            roll = rng.random()
            status = "paid" if roll < 0.88 else "pending" if roll < 0.95 else "cancelled"
            orders.append([order_id, customer, day.isoformat(), status, "sale", _amount(rng)])
        day += timedelta(days=1)
    # Refunds: separate rows with negative revenue, booked a few days after the sale.
    refunds = []
    for row in rng.sample(orders, len(orders) // 28):
        if row[3] != "paid":
            continue
        refund_day = date.fromisoformat(row[2]) + timedelta(days=rng.randint(1, 6))
        if refund_day > date(2026, 12, 1):
            continue
        order_id += 1
        refunds.append([order_id, row[1], refund_day.isoformat(), "paid", "refund", -int(row[5] * rng.choice([1, 1, 0.5]))])
    orders = sorted(orders + refunds, key=lambda row: row[0])
    return rng, customers, orders


def _snapshot(orders, customers, as_of, rng=None, settle=False):
    visible = []
    for row in orders:
        if row[2] > as_of:
            continue
        row = list(row)
        visible.append(tuple(row))
    return {"orders": visible, "customers": [tuple(c) for c in customers]}


def make_realistic_case(kind="crm_migration", seed=2026, scale=1):
    if kind not in SCENARIOS:
        raise ValueError("Unknown realistic scenario.")
    rng, customers, orders = _build(seed, scale)
    previous = _snapshot(orders, [c for c in customers if c[0] <= 1400 * scale], "2026-11-24")
    # By Dec 1 some pending payments from earlier in the month have settled.
    settled = {row[0] for row in orders if row[3] == "pending" and row[2] <= "2026-11-20" and rng.random() < 0.6}
    current_orders = [(*row[:3], "paid" if row[0] in settled else row[3], *row[4:])
                      for row in _snapshot(orders, customers, "2026-12-01")["orders"]]
    current_customers = [tuple(c) for c in customers]
    contract = dict(CONTRACT)
    prior_sql = canonical_sql(contract)
    current_sql = prior_sql

    if kind == "crm_migration":
        # Migration duplicated ~9% of customer records under a new region label
        # and has not yet synced ~60 new customers.
        dupes = rng.sample(current_customers, 126 * scale)
        current_customers += [(cid, region + " (migrated)") for cid, region in dupes]
        current_sql = ("SELECT o.order_id, o.revenue_cents\nFROM orders o\n"
                       "JOIN customers c ON c.customer_id = o.customer_id\n"
                       "WHERE o.status = 'paid'\n  AND o.order_date >= '2026-11-01'\n"
                       "  AND o.order_date < '2026-12-01'\n  AND o.kind <> 'refund'")
    elif kind == "cutoff_change":
        current_sql = prior_sql.replace("order_date < '2026-12-01'", "order_date <= '2026-12-01'")
    elif kind == "status_filter":
        current_sql = prior_sql.replace("status = 'paid'", "status IN ('paid', 'pending')")
    elif kind == "refund_policy":
        current_sql = prior_sql.replace(" AND kind <> 'refund'", "")
        contract["refund_policy"] = None

    snapshots = {"previous": {"orders": previous["orders"], "customers": previous["customers"]},
                 "current": {"orders": current_orders, "customers": current_customers}}
    incident = Incident(f"realistic-{kind}-{seed}" + (f"-x{scale}" if scale > 1 else ""), "", contract, snapshots, prior_sql, current_sql,
                        SCENARIOS[kind]["expected"], "realistic_" + kind)
    incident.description = _description(incident, SCENARIOS[kind]["change_note"])
    return incident


def _description(incident, note):
    from .runner import QueryRunner
    totals = []
    for sql, snap in [(incident.previous_sql, "previous"), (incident.current_sql, "current")]:
        runner = QueryRunner(incident.snapshots[snap])
        try:
            rows = runner.query(sql, max_rows=200000)["rows"]
        finally:
            runner.close()
        totals.append(sum(row[1] for row in rows))
    change = (totals[1] - totals[0]) / totals[0] * 100 if totals[0] else 0
    return (f"Finance dashboard: Paid November revenue moved from ${totals[0] / 100:,.0f} "
            f"(Nov 24 refresh) to ${totals[1] / 100:,.0f} (Dec 1 refresh), {change:+.0f}%. "
            "Black Friday and Cyber Monday were strong, but the CFO review is today and the team "
            f"needs to know how much of this is real. {note}")


def realistic_cases(seeds=(2026, 7)):
    return [make_realistic_case(kind, seed) for seed in seeds for kind in SCENARIOS]


def scale_cases(scale=10, seed=2026):
    """Warehouse-scale variants (~40k orders) where raw rows no longer fit a model's context."""
    return [make_realistic_case(kind, seed, scale) for kind in SCENARIOS]
