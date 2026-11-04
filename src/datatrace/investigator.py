"""Evidence collection and independent, per-order repair verification."""

from collections import Counter

from .cases import canonical_sql
from .runner import QueryRejected, QueryRunner


class Investigation:
    def __init__(self, incident):
        from .inputs import validate_incident
        self.incident = validate_incident(incident)
        self.runners = {}
        try:
            for name, data in incident.snapshots.items():
                self.runners[name] = QueryRunner(data)
        except Exception:
            self.close()
            raise
        self.evidence = []
        self.metric_rows = {}

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
                evidence = self.runners[snapshot].query(sql, max_rows=200000)
                if evidence["columns"] != ["order_id", "revenue_cents"] or evidence["truncated"]:
                    raise QueryRejected("Replay metric must return complete order_id, revenue_cents rows.")
                if any(type(row[0]) is not int or type(row[1]) is not int for row in evidence["rows"]):
                    raise QueryRejected("Metric order IDs and amounts must be integer values.")
                complete = evidence["rows"]
                self.metric_rows[(version, snapshot)] = Counter(tuple(row) for row in complete)
                total = sum(row[1] for row in complete)
                evidence.update({"evidence_id": f"E{len(self.evidence) + 1}", "snapshot": snapshot,
                                 "total_row_count": len(complete), "revenue_cents": total,
                                 "rows": complete[:100], "truncated": len(complete) > 100})
                self.evidence.append(evidence)
                records.append({"sql_version": version, "snapshot": snapshot,
                                "revenue_cents": total,
                                "row_count": len(complete),
                                "evidence_id": evidence["evidence_id"]})
        return records

    def verify(self, sql, *, snapshot="current"):
        """Compare a candidate to a Python reference from the explicit contract.

        Checks the complete order/value multiset, not just the metric total.
        Returns useful errors; never treats a model's 'verified' claim as proof.
        """
        contract = self.incident.contract
        if snapshot not in self.runners:
            raise QueryRejected("Unknown snapshot.")
        if contract["refund_policy"] is None:
            return {"verified": False, "reason": "Clarify refund treatment before verifying a repair."}
        expected = self._contract_rows(snapshot)
        try:
            result = self.runners[snapshot].query(sql, max_rows=200000)
        except QueryRejected as exc:
            return {"verified": False, "reason": str(exc)}
        result.update({"evidence_id": f"E{len(self.evidence) + 1}", "snapshot": snapshot})
        complete = result["rows"]
        public_result = {**result, "rows": complete[:100], "total_row_count": len(complete),
                         "truncated": result["truncated"] or len(complete) > 100}
        self.evidence.append(public_result)
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
                "missing_row_count": sum((expected - actual).values()),
                "unexpected_row_count": sum((actual - expected).values()),
                "missing_rows": [list(row) for row in list((expected - actual).elements())[:100]],
                "unexpected_rows": [list(row) for row in list((actual - expected).elements())[:100]],
                "reason": "Complete order/value multiset matches the metric contract." if actual == expected
                          else "Candidate violates order coverage, uniqueness, or per-order revenue."}

    def _contract_rows(self, snapshot):
        contract = self.incident.contract
        return Counter(
            (order_id, cents)
            for order_id, _, date, status, kind, cents in self.incident.snapshots[snapshot]["orders"]
            if status == contract["status"] and contract["start"] <= date < contract["end_exclusive"]
            and (kind != "refund" or contract["refund_policy"] == "include")
        )

    def reconcile(self, replay):
        """Explain reported movement using the independent order-level contract."""
        if self.incident.contract["refund_policy"] is None:
            return None
        previous, current = self._contract_rows("previous"), self._contract_rows("current")
        actual = self.metric_rows[("current", "current")]
        affected_ids = {order_id for order_id, _ in (actual - current) | (current - actual)}
        affected = {order_id: {"order_id": order_id, "reported_cents": 0, "expected_cents": 0,
                               "reported_rows": 0, "expected_rows": 0} for order_id in affected_ids}
        for rows, label in [(actual, "reported"), (current, "expected")]:
            for (order_id, cents), count in rows.items():
                if order_id in affected:
                    affected[order_id][f"{label}_cents"] += cents * count
                    affected[order_id][f"{label}_rows"] += count
        for order in affected.values():
            order["difference_cents"] = order["reported_cents"] - order["expected_cents"]
        ranked = sorted(affected.values(), key=lambda row: (-abs(row["difference_cents"]), row["order_id"]))
        previous_expected = sum(cents * count for (_, cents), count in previous.items())
        current_expected = sum(cents * count for (_, cents), count in current.items())
        return {
            "previous_expected_cents": previous_expected,
            "current_expected_cents": current_expected,
            "underlying_change_cents": current_expected - previous_expected,
            "previous_error_cents": replay[0]["revenue_cents"] - previous_expected,
            "current_error_cents": replay[3]["revenue_cents"] - current_expected,
            "current_evidence_id": replay[3]["evidence_id"],
            "affected_order_count": len(ranked),
            "affected_orders": ranked[:100],
        }


def offline_walkthrough(incident):
    """Scripted diagnostics for offline use; this is not an LLM evaluation."""
    import time
    from .reporting import enrich_report
    started = time.monotonic()
    session = Investigation(incident)
    try:
        replay = session.replay()
        reconciliation = session.reconcile(replay)
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
            data_changed = session._contract_rows("previous") != session._contract_rows("current")
            if not validation["verified"]:
                classification = "mixed_change" if data_changed else "calculation_defect"
                summary = "The current calculation violates the metric contract. Inspect the replay and per-order differences."
                correction = canonical_sql(incident.contract)
                validation = session.verify(correction)
            else:
                classification = "genuine_change"
                summary = "The current calculation matches the metric contract. Preserve the legitimate data-driven movement."
                correction = None
        report = {"mode": "offline_scripted", "classification": classification, "summary": summary,
                "replay": replay, "reconciliation": reconciliation, "evidence": session.evidence, "correction_sql": correction,
                "validation": validation, "usage": {},
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "limitations": "Deterministic contract diagnostics; no AI or production accuracy claim."}
        report["evidence_ids"] = [item["evidence_id"] for item in session.evidence]
        return enrich_report(report, incident)
    finally:
        session.close()
