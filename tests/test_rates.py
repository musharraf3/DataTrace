import json
from copy import deepcopy

import pytest

from datatrace.cases import make_case
from datatrace.healthcare import RATE_SCENARIOS, make_rate_case
from datatrace.inputs import InputError, bundle_dict, fingerprint, load_bundle, validate_contract
from datatrace.investigator import Investigation, offline_walkthrough
from datatrace.meta import investigate_meta
from datatrace.rates import decompose
from datatrace.reporting import markdown_report
from datatrace.runner import QueryRejected, QueryRunner


@pytest.fixture(scope="module")
def pmpm():
    return make_rate_case("pmpm_coverage_lines")


def _contract(**changes):
    base = {"name": "PMPM", "start": "2009-11-01", "end_exclusive": "2009-12-01", "status": "paid",
            "refund_policy": "include", "rate": {"kind": "pmpm"}}
    return {**base, **changes}


def test_rate_contracts_are_month_aligned_and_typed():
    assert validate_contract(_contract())["rate"] == {"kind": "pmpm"}
    with pytest.raises(InputError, match="month-aligned"):
        validate_contract(_contract(start="2009-11-02"))
    with pytest.raises(InputError, match="Rate must be"):
        validate_contract(_contract(rate={"kind": "ratio"}))
    with pytest.raises(InputError, match="reversals must be excluded"):
        validate_contract(_contract(rate={"kind": "per_1000"}))
    assert "rate" not in validate_contract({k: v for k, v in _contract().items() if k != "rate"})


def test_pmpm_split_shows_a_false_drop_that_is_really_a_rise(pmpm):
    report = offline_walkthrough(pmpm)
    rate = report["rate_reconciliation"]
    assert report["classification"] == "mixed_change"
    assert (rate["previous_reported"], rate["current_reported"], rate["current_expected"]) == (131.31, 97.21, 177.95)
    assert rate["real_change"] == 46.64 and rate["real_change_from_enrollment"] == 0
    assert rate["error_from_denominator"] == -80.74 and rate["error_from_numerator"] == 0
    assert rate["reported_member_months"]["current"] == 17702 and rate["expected_member_months"]["current"] == 9670
    assert rate["affected_member_month_count"] == 8032
    assert report["denominator_validation"]["verified"] and report["validation"]["verified"]
    assert "DISTINCT member_id, month" in report["denominator_correction_sql"]


def test_decomposition_is_exact():
    expected = {"previous": (1000000, 10, 100), "current": (1500000, 15, 110)}
    reported = {"previous": (1000000, 10, 100), "current": (1600000, 16, 180)}
    parts = decompose("pmpm", expected, reported)
    assert parts["real_change"] == round(parts["current_expected"] - parts["previous_expected"], 2)
    assert abs(parts["reporting_error"] - (parts["current_reported"] - parts["current_expected"])) < 0.011
    assert abs(parts["error_from_numerator"] + parts["error_from_denominator"] - parts["reporting_error"]) < 0.011


@pytest.mark.parametrize("kind", list(RATE_SCENARIOS))
def test_every_rate_scenario_is_classified_correctly_offline(kind):
    case = make_rate_case(kind)
    report = offline_walkthrough(case)
    assert report["classification"] == case.expected_classification
    if case.expected_classification == "genuine_change":
        assert report["denominator_correction_sql"] is None and report["rate_reconciliation"]["reporting_error"] == 0


def test_denominator_verifier_rejects_duplicates_wrong_months_and_shapes(pmpm):
    session = Investigation(pmpm)
    try:
        assert not session.verify_denominator(pmpm.current_denominator_sql)["verified"]
        duplicate = session.verify_denominator(pmpm.current_denominator_sql)
        assert duplicate["unexpected_row_count"] == 8032 and duplicate["missing_row_count"] == 0
        wrong_month = session.verify_denominator("SELECT DISTINCT member_id, month FROM member_months WHERE month = '2009-10'")
        assert not wrong_month["verified"] and wrong_month["missing_row_count"] == 9670
        assert not session.verify_denominator("SELECT member_id FROM member_months")["verified"]
        assert not session.verify_denominator("SELECT COUNT(*) FROM member_months")["verified"]
        for good in ["SELECT member_id, month FROM member_months WHERE month = '2009-11' AND coverage = 'medical'",
                     "SELECT member_id, month FROM member_months WHERE month = '2009-11' GROUP BY member_id, month"]:
            assert session.verify_denominator(good)["verified"]
    finally:
        session.close()


def test_rate_bundles_round_trip_and_plain_bundles_are_unchanged(pmpm, tmp_path):
    raw = json.dumps(bundle_dict(pmpm))
    loaded = load_bundle(raw)
    assert loaded.current_denominator_sql == pmpm.current_denominator_sql
    assert fingerprint(loaded) == fingerprint(pmpm)
    assert offline_walkthrough(loaded)["classification"] == "mixed_change"
    plain = bundle_dict(make_case())
    assert "current_denominator_sql" not in plain and "rate" not in plain["contract"]
    assert all("member_months" not in snapshot for snapshot in plain["snapshots"].values())


def test_rate_inputs_are_validated(pmpm):
    bundle = json.loads(json.dumps(bundle_dict(pmpm)))
    missing = deepcopy(bundle)
    del missing["current_denominator_sql"]
    with pytest.raises(InputError, match="denominator SQL"):
        load_bundle(json.dumps(missing))
    no_table = deepcopy(bundle)
    del no_table["snapshots"]["current"]["member_months"]
    with pytest.raises(InputError, match="member_months table"):
        load_bundle(json.dumps(no_table))
    bad_month = deepcopy(bundle)
    bad_month["snapshots"]["current"]["member_months"][0][1] = "2009-13"
    with pytest.raises(InputError, match="YYYY-MM"):
        load_bundle(json.dumps(bad_month))
    stray = json.loads(json.dumps(bundle_dict(make_case())))
    stray["current_denominator_sql"] = stray["previous_denominator_sql"] = "SELECT 1"
    with pytest.raises(InputError, match="only used with a rate"):
        load_bundle(json.dumps(stray))


def test_member_months_table_exists_only_for_rate_snapshots(pmpm):
    plain = QueryRunner(make_case().snapshots["current"])
    try:
        with pytest.raises(QueryRejected):
            plain.query("SELECT * FROM customer_months")
    finally:
        plain.close()
    rate = QueryRunner(pmpm.snapshots["current"], domain="healthcare")
    try:
        assert rate.query("SELECT COUNT(*) FROM member_months")["rows"] == [[17702]]
        with pytest.raises(QueryRejected):
            rate.query("DELETE FROM member_months")
    finally:
        rate.close()


def test_markdown_report_has_the_rate_section(pmpm):
    text = markdown_report(offline_walkthrough(pmpm))
    assert "## Rate reconciliation (cost per member per month)" in text
    assert "-$80.74 PMPM from the denominator" in text and "Candidate denominator SQL" in text


# ------------------------------------------------------------------ agent and reviewer on a rate


def _response(*, calls=None, final=None, response_id="r1"):
    output = calls or [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(final)}]}]
    return {"id": response_id, "status": "completed", "output": output, "usage": {"input_tokens": 10, "output_tokens": 5}}


class FakeMeta:
    model, review_model = "mock-spark", "mock-wonder"

    def __init__(self, replies):
        self.replies, self.requests = iter(replies), []

    def complete(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.replies)


FIX = "SELECT DISTINCT member_id, month FROM member_months WHERE month = '2009-11'"
SUPPORTED = {"concerns": [], "verdict": "supported", "stakeholder_brief": "PMPM rose; the drop is a denominator bug."}


def test_agent_sees_rate_facts_and_verifies_its_denominator(pmpm):
    call = {"type": "function_call", "name": "verify_denominator", "call_id": "c1",
            "arguments": json.dumps({"sql": FIX, "purpose": "One row per member month"})}
    final = {"classification": "mixed_change", "summary": "PMPM rose from $131.31 to $177.95; the drop is a denominator bug.",
             "root_cause": "Pharmacy coverage rows double-count member months.", "evidence_ids": ["E8"],
             "correction_sql": None, "denominator_correction_sql": FIX}
    fake = FakeMeta([_response(calls=[call]), _response(final=final, response_id="r2"), _response(final=SUPPORTED)])
    report = investigate_meta(pmpm, client=fake, review=True)
    first = json.loads(fake.requests[0]["inputs"])
    assert first["rate_reconciliation"]["error_from_denominator"] == -80.74
    assert first["incident"]["rate_metric"]["kind"] == "pmpm" and "member_months" in first["incident"]["schema"]
    assert "snapshot_data" not in first and first["rate_reconciliation"]["denominator_evidence_id"] == "E8"
    assert json.loads(fake.requests[1]["inputs"][0]["output"])["verified"] is True
    assert report["denominator_validation"]["verified"] and report["review"]["verdict"] == "supported"
    assert report["classification"] == "mixed_change" and report["rate_reconciliation"]["real_change"] == 46.64


def test_reviewer_blocks_a_rate_drop_reported_as_genuine(pmpm):
    final = {"classification": "genuine_change", "summary": "Care management cut PMPM by 26%.", "root_cause": None,
             "evidence_ids": ["E8"], "correction_sql": None, "denominator_correction_sql": None}
    revised = {**final, "classification": "mixed_change", "denominator_correction_sql": FIX,
               "summary": "PMPM rose to $177.95; the drop is a denominator bug."}
    fake = FakeMeta([_response(final=final), _response(final=SUPPORTED), _response(final=revised, response_id="r3"),
                     _response(final=SUPPORTED)])
    report = investigate_meta(pmpm, client=fake, review=True)
    first_review = report["review_history"][0]
    assert first_review["verdict"] == "challenged"
    assert any("reporting error of -$80.74 PMPM" in c for c in first_review["concerns"])
    assert report["classification"] == "mixed_change" and report["denominator_validation"]["verified"]


def test_genuine_claim_on_a_broken_denominator_is_overridden_without_review(pmpm):
    final = {"classification": "genuine_change", "summary": "PMPM fell.", "root_cause": None,
             "evidence_ids": ["E8"], "correction_sql": None}
    report = investigate_meta(pmpm, client=FakeMeta([_response(final=final)]))
    assert report["classification"] == "insufficient_evidence"
    assert any("member-month" in issue for issue in report["consistency_issues"])
