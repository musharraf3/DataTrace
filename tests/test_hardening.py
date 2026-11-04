"""Regression tests for issues found in the Nov 3 stress test."""

import pytest

from datatrace.cases import make_case
from datatrace.inputs import InputError, load_csv
from datatrace.runner import QueryRejected, QueryRunner

HEADER = b"order_id,customer_id,order_date,status,kind,revenue_cents\n"


@pytest.mark.parametrize("body, message", [
    (b"1,1,2026-11-01,paid,sale,1.5\n", "line 2: revenue_cents must be a whole number"),
    (b"1,1,2026-11-01,PAID,sale,1\n", "row 1: status must be paid"),
    (b"1,1,2026-11-01,paid,sale,1,extra\n", "line 2: expected 6"),
    (b"1,1,2026-11-01,paid,sale,1\n1,2,2026-11-02,paid,sale,3\n", "row 2: order_id 1 appears more than once"),
])
def test_csv_errors_name_the_line_and_field(body, message):
    with pytest.raises(InputError, match=message):
        load_csv(HEADER + body, "orders")


def test_csv_header_error_is_not_swallowed():
    with pytest.raises(InputError, match="CSV header must be"):
        load_csv(b"order_id;customer_id\n1;1\n", "orders")


@pytest.mark.parametrize("sql", [
    "SELECT substr(order_date, 1, 7) AS month, SUM(revenue_cents) FROM orders GROUP BY 1",
    "SELECT strftime('%d', order_date), COUNT(*) FROM orders GROUP BY 1",
    "SELECT lower(status), length(kind), iif(revenue_cents > 0, 1, 0) FROM orders",
    "SELECT group_concat(region) FROM customers",
])
def test_safe_date_and_text_functions_are_allowed(sql):
    runner = QueryRunner(make_case().snapshots["current"])
    try:
        assert runner.query(sql)["rows"]
    finally:
        runner.close()


@pytest.mark.parametrize("sql", ["SELECT printf('%s', 1)", "SELECT zeroblob(100)", "SELECT random()"])
def test_non_allowlisted_functions_stay_blocked(sql):
    runner = QueryRunner(make_case().snapshots["current"])
    try:
        with pytest.raises(QueryRejected):
            runner.query(sql)
    finally:
        runner.close()


def test_model_text_is_escaped_before_html_rendering():
    from datatrace.ui import _html, _md
    assert _html('<img src=x onerror="alert(1)">') == "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"
    assert _md("grew $115,080 to $304,397") == r"grew \$115,080 to \$304,397"


def test_exported_report_includes_root_cause_brief_steps_and_cost():
    import json
    from pathlib import Path
    from datatrace.reporting import list_price_usd, markdown_report
    recorded = Path(__file__).resolve().parents[1] / "examples" / "recorded" / "realistic-crm_migration.json"
    report = json.loads(recorded.read_text(encoding="utf-8"))["report"]
    md = markdown_report(report)
    for text in ["**Root cause:**", "## Brief for leadership", "## How the agent investigated", "list-price cost"]:
        assert text in md
    assert 0 < list_price_usd(report) < 1


def test_healthcare_domain_speaks_claims_vocabulary_and_verifies():
    from datatrace.healthcare import make_claims_case
    from datatrace.investigator import Investigation, offline_walkthrough
    case = make_claims_case("eligibility_spans")
    context = case.public_context()
    assert set(context["schema"]) == {"claims", "eligibility"} and "denied" in context["vocabulary"]["status"]
    assert "claim_id, paid_cents" in context["sql_dialect"] and "orders" not in case.current_sql
    report = offline_walkthrough(case)
    assert report["classification"] == "mixed_change" and report["validation"]["verified"]
    assert "FROM claims" in report["correction_sql"]
    session = Investigation(case)
    try:
        with pytest.raises(QueryRejected):
            session.query("current", "SELECT * FROM orders")  # Revenue tables do not exist in this domain.
        assert session.query("current", "SELECT COUNT(*) FROM claims WHERE kind = 'reversal'")["rows"][0][0] > 0
    finally:
        session.close()


def test_healthcare_csv_round_trip_uses_domain_headers():
    from datatrace.healthcare import make_claims_case
    from datatrace.inputs import snapshot_csv
    case = make_claims_case("runout_growth")
    text = snapshot_csv(case, "current", "orders")
    assert text.startswith("claim_id,member_id,service_date,status,kind,paid_cents")
    assert ",reversal," in text
    assert load_csv(text.encode(), "orders", "healthcare") == case.snapshots["current"]["orders"]


def test_healthcare_split_offline_regression():
    from datatrace.healthcare import healthcare_cases
    from datatrace.investigator import offline_walkthrough
    for case in healthcare_cases():
        assert offline_walkthrough(case)["classification"] == case.expected_classification


def test_intake_defines_refund_policy_direction():
    # "net of reversals" once drafted as "exclude"; the prompt and schema now pin the meaning.
    from datatrace.intake import INTAKE_PROMPT, INTAKE_SCHEMA
    assert '"include" when they are netted' in INTAKE_PROMPT and "net of reversals" in INTAKE_PROMPT
    assert "netted" in INTAKE_SCHEMA["properties"]["refund_policy"]["description"]
