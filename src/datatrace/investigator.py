"""Evidence collection and independent, per-order repair verification."""

from collections import Counter

from .cases import canonical_sql
from .rates import canonical_denominator_sql, decompose, expected_member_months
from .runner import QueryRejected, QueryRunner


class Investigation:
    def __init__(self, incident):
        from .inputs import validate_incident
        from .domains import get
        self.incident = validate_incident(incident)
        self.domain = get(getattr(self.incident, "domain", "revenue"))
        self.runners = {}
        try:
            for name, data in incident.snapshots.items():
                self.runners[name] = QueryRunner(data, domain=self.domain)
        except Exception:
            self.close()
            raise
        self.evidence = []
        self.metric_rows = {}
        self.denominator_rows = {}

    @property
    def is_rate(self):
        return "rate" in self.incident.contract

    def close(self):
        for runner in self.runners.values():
            runner.close()

    def query(self, snapshot, sql):
        if snapshot not in self.runners:
            raise QueryRejected("Snapshot must be previous or current.")
        key = (snapshot, " ".join(str(sql).split()))
        for item in self.evidence:  # Identical query: return the same executed evidence.
            if item.get("snapshot") == snapshot and " ".join(str(item.get("sql", "")).split()) == key[1]                     and "total_row_count" not in item:
                return {**item, "cached": True}
        result = self.runners[snapshot].query(sql)
        result.update({"evidence_id": f"E{len(self.evidence) + 1}", "snapshot": snapshot})
        self.evidence.append(result)
        return result

    def replay(self):
        records = []
        for version, sql in [("previous", self.incident.previous_sql), ("current", self.incident.current_sql)]:
            for snapshot in ["previous", "current"]:
                evidence = self.runners[snapshot].query(sql, max_rows=200000)
                d = self.domain
                if evidence["columns"] != [d.key, d.value] or evidence["truncated"]:
                    raise QueryRejected(f"Replay metric must return complete {d.key}, {d.value} rows.")
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
        if result["columns"] != [self.domain.key, self.domain.value] or result["truncated"]:
            return {"verified": False, "reason": f"Expected complete {self.domain.key}, {self.domain.value} rows.",
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
                "reason": f"Complete {self.domain.item}/value multiset matches the metric contract." if actual == expected
                          else f"Candidate violates {self.domain.item} coverage, uniqueness, or per-{self.domain.item} amounts."}

    def replay_denominator(self):
        """Four-way replay of the denominator SQL (rate metrics only): member months per version/snapshot."""
        if not self.is_rate:
            return None
        d, records = self.domain, []
        for version, sql in [("previous", self.incident.previous_denominator_sql),
                             ("current", self.incident.current_denominator_sql)]:
            for snapshot in ["previous", "current"]:
                evidence = self.runners[snapshot].query(sql, max_rows=200000)
                if evidence["columns"] != [d.member, d.month] or evidence["truncated"]:
                    raise QueryRejected(f"Denominator SQL must return complete {d.member}, {d.month} rows.")
                if any(type(row[0]) is not int or not isinstance(row[1], str) for row in evidence["rows"]):
                    raise QueryRejected(f"Denominator {d.member} must be integers and {d.month} text (YYYY-MM).")
                complete = evidence["rows"]
                self.denominator_rows[(version, snapshot)] = Counter(tuple(row) for row in complete)
                evidence.update({"evidence_id": f"E{len(self.evidence) + 1}", "snapshot": snapshot,
                                 "total_row_count": len(complete), "member_months": len(complete),
                                 "rows": complete[:100], "truncated": len(complete) > 100})
                self.evidence.append(evidence)
                records.append({"sql_version": version, "snapshot": snapshot, "member_months": len(complete),
                                "evidence_id": evidence["evidence_id"]})
        return records

    def verify_denominator(self, sql, *, snapshot="current"):
        """Check candidate denominator SQL: every (member, month) in the window exactly once."""
        d = self.domain
        if not self.is_rate:
            return {"verified": False, "reason": "This metric is not a rate, so it has no denominator."}
        if snapshot not in self.runners:
            raise QueryRejected("Unknown snapshot.")
        expected = expected_member_months(self.incident.snapshots[snapshot], self.incident.contract)
        try:
            result = self.runners[snapshot].query(sql, max_rows=200000)
        except QueryRejected as exc:
            return {"verified": False, "reason": str(exc)}
        result.update({"evidence_id": f"E{len(self.evidence) + 1}", "snapshot": snapshot})
        complete = result["rows"]
        self.evidence.append({**result, "rows": complete[:100], "total_row_count": len(complete),
                              "truncated": result["truncated"] or len(complete) > 100})
        if result["columns"] != [d.member, d.month] or result["truncated"]:
            return {"verified": False, "reason": f"Expected complete {d.member}, {d.month} rows.",
                    "evidence_id": result["evidence_id"]}
        if any(type(row[0]) is not int or not isinstance(row[1], str) for row in complete):
            return {"verified": False, "reason": f"{d.member} must be integers and {d.month} text.",
                    "evidence_id": result["evidence_id"]}
        actual = Counter(tuple(row) for row in complete)
        return {"verified": actual == expected, "evidence_id": result["evidence_id"],
                "expected_member_months": sum(expected.values()), "actual_member_months": len(complete),
                "missing_row_count": sum((expected - actual).values()),
                "unexpected_row_count": sum((actual - expected).values()),
                "missing_rows": [list(row) for row in list((expected - actual).elements())[:100]],
                "unexpected_rows": [list(row) for row in list((actual - expected).elements())[:100]],
                "reason": "Every member month in the window appears exactly once." if actual == expected
                          else "Candidate denominator misses, duplicates or adds member months."}

    def rate_reconcile(self, replay, denominator_replay):
        """Split the rate change into real movement and reporting error, each by numerator and denominator."""
        contract = self.incident.contract
        if not self.is_rate or contract["refund_policy"] is None or denominator_replay is None:
            return None
        kind = contract["rate"]["kind"]
        expected, months = {}, {}
        for snapshot in ["previous", "current"]:
            rows = self._contract_rows(snapshot)
            months[snapshot] = expected_member_months(self.incident.snapshots[snapshot], contract)
            expected[snapshot] = (sum(cents * count for (_, cents), count in rows.items()),
                                  sum(rows.values()), sum(months[snapshot].values()))
        reported = {"previous": (replay[0]["revenue_cents"], replay[0]["row_count"], denominator_replay[0]["member_months"]),
                    "current": (replay[3]["revenue_cents"], replay[3]["row_count"], denominator_replay[3]["member_months"])}
        result = decompose(kind, expected, reported)
        if result is None:
            return None
        actual = self.denominator_rows[("current", "current")]
        affected = sorted(((member, month, actual.get((member, month), 0), months["current"].get((member, month), 0))
                           for member, month in set(actual) | set(months["current"])
                           if actual.get((member, month), 0) != months["current"].get((member, month), 0)),
                          key=lambda row: (-abs(row[2] - row[3]), row[0], row[1]))
        d = self.domain
        result.update({
            "expected_member_months": {s: expected[s][2] for s in expected},
            "reported_member_months": {s: reported[s][2] for s in reported},
            "denominator_evidence_id": denominator_replay[3]["evidence_id"],
            "affected_member_month_count": len(affected),
            "affected_member_months": [{d.member: m, d.month: month, "reported_rows": r, "expected_rows": e}
                                       for m, month, r, e in affected[:100]]})
        return result

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
        d = session.domain
        session.query("current", f"SELECT {d.member}, COUNT(*) AS rows_per_{d.member_noun} FROM {d.dim} "
                      f"GROUP BY {d.member} HAVING COUNT(*) > 1")
        session.query("current", f"SELECT f.{d.key} FROM {d.fact} f LEFT JOIN {d.dim} m "
                      f"ON f.{d.member} = m.{d.member} WHERE m.{d.member} IS NULL")
        if incident.contract["refund_policy"] is None:
            classification = "insufficient_evidence"
            summary = "Refund treatment is unspecified. Clarify whether paid refunds reduce this metric before proposing a repair."
            correction, validation = None, None
        else:
            validation = session.verify(incident.current_sql)
            data_changed = session._contract_rows("previous") != session._contract_rows("current")
            if session.is_rate:
                data_changed = data_changed or (
                    expected_member_months(incident.snapshots["previous"], incident.contract)
                    != expected_member_months(incident.snapshots["current"], incident.contract))
            if not validation["verified"]:
                classification = "mixed_change" if data_changed else "calculation_defect"
                summary = "The current calculation violates the metric contract. Inspect the replay and per-order differences."
                correction = canonical_sql(incident.contract, session.domain)
                validation = session.verify(correction)
            else:
                classification = "genuine_change"
                summary = "The current calculation matches the metric contract. Preserve the legitimate data-driven movement."
                correction = None
        rate_fields = {}
        if session.is_rate:
            denominator_replay = session.replay_denominator()
            rate_fields = {"denominator_replay": denominator_replay,
                           "rate_reconciliation": session.rate_reconcile(replay, denominator_replay),
                           "denominator_correction_sql": None, "denominator_validation": None}
            if incident.contract["refund_policy"] is not None:
                check = session.verify_denominator(incident.current_denominator_sql)
                if not check["verified"]:
                    fixed = canonical_denominator_sql(incident.contract, session.domain)
                    rate_fields.update(denominator_correction_sql=fixed,
                                       denominator_validation=session.verify_denominator(fixed))
                    classification = "mixed_change" if data_changed else "calculation_defect"
                    summary = ("The current denominator violates the member-month contract"
                               + (" and the numerator does too" if correction else "")
                               + ". Inspect the denominator replay and the duplicated or missing member months.")
                else:
                    rate_fields["denominator_validation"] = check
        report = {"mode": "offline_scripted", "classification": classification, "summary": summary,
                "replay": replay, "reconciliation": reconciliation, "evidence": session.evidence, "correction_sql": correction,
                "validation": validation, "usage": {}, **rate_fields,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "limitations": "Deterministic contract diagnostics; no AI or production accuracy claim."}
        report["evidence_ids"] = [item["evidence_id"] for item in session.evidence]
        return enrich_report(report, incident)
    finally:
        session.close()
