from dataclasses import replace

import pytest

from datatrace.cases import all_cases, canonical_sql, make_case
from datatrace.evaluate import evaluate
from datatrace.investigator import Investigation, offline_walkthrough
from datatrace.runner import QueryRejected, QueryRunner


def test_duplicate_join_is_exposed_and_repair_preserves_real_growth():
    case = make_case("duplicate_join", 1)
    report = offline_walkthrough(case)
    assert report["classification"] == "mixed_change"
    assert report["replay"][0]["revenue_cents"] == 120000
    assert report["replay"][1]["revenue_cents"] == 130000
    assert report["replay"][3]["revenue_cents"] == 170000
    assert report["validation"]["verified"]
    assert report["validation"]["actual_revenue_cents"] == 130000
    reconciliation = report["reconciliation"]
    assert reconciliation["underlying_change_cents"] == 10000
    assert reconciliation["current_error_cents"] == 40000
    assert reconciliation["affected_order_count"] == 1
    affected = reconciliation["affected_orders"][0]
    assert affected["reported_rows"] == 2 and affected["expected_rows"] == 1
    assert affected["difference_cents"] == 40000


def test_genuine_growth_does_not_trigger_a_repair():
    report = offline_walkthrough(make_case("growth"))
    assert report["classification"] == "genuine_change"
    assert report["correction_sql"] is None
    assert report["replay"][3]["revenue_cents"] == 75000


def test_ambiguous_definition_requires_clarification():
    report = offline_walkthrough(make_case("ambiguous"))
    assert report["classification"] == "insufficient_evidence"
    assert report["correction_sql"] is None
    assert "refund" in report["summary"].lower()
    assert report["reconciliation"] is None


def test_same_total_with_wrong_per_order_values_fails_verification():
    session = Investigation(make_case("growth"))
    try:
        candidate = ("SELECT 1 AS order_id, 75000 AS revenue_cents")
        result = session.verify(candidate)
        assert result["actual_revenue_cents"] == result["expected_revenue_cents"]
        assert not result["verified"]
        assert result["missing_rows"] and result["unexpected_rows"]
    finally:
        session.close()


def test_original_bug_is_not_verified_and_corrected_rows_are():
    case = make_case("duplicate_join")
    session = Investigation(case)
    try:
        assert not session.verify(case.current_sql)["verified"]
        assert session.verify(canonical_sql(case.contract))["verified"]
        assert len({e["evidence_id"] for e in session.evidence}) == len(session.evidence)
    finally:
        session.close()


def test_ambiguous_contract_cannot_be_verified_by_a_candidate():
    session = Investigation(make_case("ambiguous"))
    try:
        assert not session.verify("SELECT order_id, revenue_cents FROM orders")["verified"]
    finally:
        session.close()


@pytest.mark.parametrize("sql", [
    "DROP TABLE orders", "DELETE FROM orders", "UPDATE orders SET revenue_cents = 0",
    "INSERT INTO orders VALUES (9,1,'2026-10-01','paid','sale',1)",
    "ATTACH DATABASE ':memory:' AS other", "PRAGMA database_list", "VACUUM",
    "SELECT load_extension('bad.dll')", "SELECT readfile('private.txt')",
    "SELECT * FROM sqlite_master", "SELECT 1; SELECT 2",
    "WITH RECURSIVE t(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM t) SELECT * FROM t",
    "SELECT randomblob(1000000000)",
])
def test_query_boundary_rejects_writes_external_io_and_recursive_work(sql):
    runner = QueryRunner(make_case().snapshots["current"])
    try:
        with pytest.raises(QueryRejected):
            runner.query(sql)
        assert runner.query("SELECT COUNT(*) FROM orders")["rows"] == [[5]]
    finally:
        runner.close()


def test_results_are_capped_and_incomplete_metrics_cannot_be_replayed():
    case = make_case()
    runner = QueryRunner(case.snapshots["current"], max_rows=2)
    try:
        result = runner.query("SELECT * FROM orders")
        assert len(result["rows"]) == 2 and result["truncated"]
    finally:
        runner.close()
    session = Investigation(replace(case, current_sql="SELECT COUNT(*) FROM orders"))
    try:
        with pytest.raises(QueryRejected):
            session.replay()
    finally:
        session.close()


def test_vm_budget_interrupts_expensive_allowed_select():
    runner = QueryRunner(make_case().snapshots["current"], max_steps=100)
    try:
        with pytest.raises(QueryRejected, match="interrupted"):
            runner.query("SELECT COUNT(*) FROM orders a CROSS JOIN orders b CROSS JOIN orders c CROSS JOIN orders d")
    finally:
        runner.close()


def test_model_context_excludes_labels_case_identifiers_and_family():
    context = make_case().public_context()
    assert not {"expected_classification", "family", "case_id", "snapshots_data"} & context.keys()


def test_twenty_case_fixture_regression_is_labeled_honestly():
    result = evaluate()
    assert len(all_cases()) == 20
    assert result["total"] == result["correct"] == 20
    assert result["errors"] == 0
    assert all(not row["inappropriate_repair"] for row in result["cases"])
    assert "not AI accuracy" in result["claim"]
