"""Evidence collection and independent, per-order repair verification."""

from collections import Counter

from .cases import canonical_sql
from .runner import QueryRejected, QueryRunner


class Investigation:
    def __init__(self, incident):
        self.incident = incident
        self.runners = {name: QueryRunner(data) for name, data in incident.snapshots.items()}
        self.evidence = []

    def close(self):
        for runner in self.runners.values():
            runner.close()

    def query(self, snapshot, sql):
        if snapshot not in self.runners:
            raise QueryRejected("Snapshot must be previous or current.")
        result = self.runners[snapshot].query(sql)
        result.update({"evidence_id": f"E{len(self.evidence) + 1}", "snapshot": snapshot})
        self.evidence.append(result)
        return result

    def replay(self):
        records = []
        for version, sql in [("previous", self.incident.previous_sql), ("current", self.incident.current_sql)]:
            for snapshot in ["previous", "current"]:
                evidence = self.query(snapshot, sql)
                if evidence["columns"] != ["order_id", "revenue_cents"] or evidence["truncated"]:
                    raise QueryRejected("Replay metric must return complete order_id, revenue_cents rows.")
                if any(type(row[1]) is not int for row in evidence["rows"]):
                    raise QueryRejected("Metric amounts must be integer cents.")
                records.append({"sql_version": version, "snapshot": snapshot,
                                "revenue_cents": sum(row[1] for row in evidence["rows"]),
                                "row_count": len(evidence["rows"]),
                                "evidence_id": evidence["evidence_id"]})
        return records

    def verify(self, sql):
        """Compare a candidate to a Python reference from the explicit contract.

        Checks the complete order/value multiset, not just the metric total.
        Returns useful errors; never treats a model's 'verified' claim as proof.
        """
        contract = self.incident.contract
        if contract["refund_policy"] is None:
            return {"verified": False, "reason": "Clarify refund treatment before verifying a repair."}
        expected = Counter()
        for order_id, customer_id, date, status, kind, cents in self.incident.snapshots["current"]["orders"]:
            if (status == contract["status"] and contract["start"] <= date < contract["end_exclusive"]
                    and (kind != "refund" or contract["refund_policy"] == "include")):
                expected[(order_id, cents)] += 1
        try:
            result = self.runners["current"].query(sql, max_rows=10000)
        except QueryRejected as exc:
            return {"verified": False, "reason": str(exc)}
        result.update({"evidence_id": f"E{len(self.evidence) + 1}", "snapshot": "current"})
        self.evidence.append(result)
        if result["columns"] != ["order_id", "revenue_cents"] or result["truncated"]:
            return {"verified": False, "reason": "Expected complete order_id, revenue_cents rows.",
                    "evidence_id": result["evidence_id"]}
        if any(len(row) != 2 or type(row[0]) is not int or type(row[1]) is not int for row in result["rows"]):
            return {"verified": False, "reason": "Order IDs and revenue must be integer values.",
                    "evidence_id": result["evidence_id"]}
        actual = Counter(tuple(row) for row in result["rows"])
        return {"verified": actual == expected, "evidence_id": result["evidence_id"],
                "expected_revenue_cents": sum(cents * count for (_, cents), count in expected.items()),
                "actual_revenue_cents": sum(row[1] for row in result["rows"]),
                "missing_rows": [list(row) for row in (expected - actual).elements()],
                "unexpected_rows": [list(row) for row in (actual - expected).elements()],
                "reason": "Complete order/value multiset matches the metric contract." if actual == expected
                          else "Candidate violates order coverage, uniqueness, or per-order revenue."}


def offline_walkthrough(incident):
    """Scripted diagnostics for offline use; this is not an LLM evaluation."""
    session = Investigation(incident)
    try:
        replay = session.replay()
        session.query("current", "SELECT customer_id, COUNT(*) AS rows_per_customer FROM customers "
                      "GROUP BY customer_id HAVING COUNT(*) > 1")
        session.query("current", "SELECT o.order_id FROM orders o LEFT JOIN customers c "
                      "ON o.customer_id = c.customer_id WHERE c.customer_id IS NULL")
        if incident.contract["refund_policy"] is None:
            classification = "insufficient_evidence"
            summary = "Refund treatment is unspecified. Clarify whether paid refunds reduce this metric before proposing a repair."
            correction, validation = None, None
        else:
            validation = session.verify(incident.current_sql)
            code_changed = any(replay[i]["revenue_cents"] != replay[i + 2]["revenue_cents"] for i in range(2))
            data_changed = replay[0]["revenue_cents"] != replay[1]["revenue_cents"]
            if not validation["verified"]:
                classification = "mixed_change" if code_changed and data_changed else "calculation_defect"
                summary = "The current calculation violates the metric contract. Inspect the replay and per-order differences."
                correction = canonical_sql(incident.contract)
                validation = session.verify(correction)
            else:
                classification = "genuine_change"
                summary = "The current calculation matches the metric contract. Preserve the legitimate data-driven movement."
                correction = None
        return {"mode": "offline_scripted", "classification": classification, "summary": summary,
                "replay": replay, "evidence": session.evidence, "correction_sql": correction,
                "validation": validation, "usage": {},
                "limitations": "Scripted diagnostics on bundled synthetic cases; no AI or production accuracy claim."}
    finally:
        session.close()
