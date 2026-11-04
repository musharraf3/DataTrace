import json

import pytest

from datatrace.cases import make_case
from datatrace.meta import MetaAPIError, MetaClient, investigate_meta


def response(*, calls=None, final=None, response_id="response-1"):
    output = calls or [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(final)}]}]
    return {"id": response_id, "status": "completed", "output": output,
            "usage": {"input_tokens": 10, "output_tokens": 5}}


def conclusion(**changes):
    value = {"classification": "calculation_defect", "summary": "Join multiplication changes the reported metric.",
             "evidence_ids": ["E1", "E4"], "correction_sql": None}
    return {**value, **changes}


class FakeMeta:
    model = "mock-meta"

    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def complete(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.replies)


def test_tool_loop_returns_results_and_links_response_context():
    call = {"type": "function_call", "name": "query_snapshot", "call_id": "call1",
            "arguments": json.dumps({"snapshot": "current", "sql": "SELECT COUNT(*) FROM customers"})}
    fake = FakeMeta([response(calls=[call]), response(final=conclusion(evidence_ids=["E5"]))])
    report = investigate_meta(make_case(), client=fake)
    assert report["usage"] == {"input_tokens": 20, "output_tokens": 10, "model_requests": 2, "tool_calls": 1}
    assert fake.requests[1]["previous_response_id"] == "response-1"
    assert fake.requests[1]["inputs"][0]["call_id"] == "call1"
    assert json.loads(fake.requests[1]["inputs"][0]["output"])["rows"] == [[4]]
    assert "expected_classification" not in fake.requests[0]["inputs"]


def test_unknown_tools_are_returned_as_errors_without_execution():
    call = {"type": "function_call", "name": "shell", "call_id": "call1", "arguments": '{}'}
    fake = FakeMeta([response(calls=[call]), response(final=conclusion())])
    report = investigate_meta(make_case(), client=fake)
    assert "error" in report["trace"][0]["result"]
    assert report["usage"]["tool_calls"] == 1


def test_model_cannot_fabricate_evidence_references():
    with pytest.raises(MetaAPIError, match="evidence"):
        investigate_meta(make_case(), client=FakeMeta([response(final=conclusion(evidence_ids=["E999"]))]))


def test_model_cannot_self_certify_a_wrong_repair():
    final = conclusion(correction_sql="SELECT 1 AS order_id, 60000 AS revenue_cents", verified=True)
    report = investigate_meta(make_case(), client=FakeMeta([response(final=final)]))
    assert not report["validation"]["verified"]


def test_missing_contract_blocks_repair_even_when_model_proposes_one():
    final = conclusion(correction_sql="SELECT order_id, revenue_cents FROM orders")
    report = investigate_meta(make_case("ambiguous"), client=FakeMeta([response(final=final)]))
    assert report["classification"] == "insufficient_evidence"
    assert report["correction_sql"] is None
    assert not report["validation"]["verified"]


def _calls(n, prefix="c"):
    return [{"type": "function_call", "name": "query_snapshot", "call_id": f"{prefix}{i}",
             "arguments": json.dumps({"snapshot": "current", "sql": f"SELECT {i}"})} for i in range(n)]


def test_tool_budget_refuses_extra_calls_then_forces_a_tool_free_final_turn():
    fake = FakeMeta([response(calls=_calls(3)), response(final=conclusion(evidence_ids=["E5"]))])
    report = investigate_meta(make_case(), client=fake, max_tool_calls=2)
    assert report["usage"]["tool_calls"] == 2
    assert "budget exhausted" in report["trace"][2]["result"]["error"]
    assert fake.requests[1]["tools_enabled"] is False and "budget is exhausted" in fake.requests[1]["instructions"]
    assert json.loads(fake.requests[1]["inputs"][0]["output"])["tool_budget_remaining"] == 1


def test_tool_budget_cannot_be_bypassed_after_the_final_turn():
    fake = FakeMeta([response(calls=_calls(3)), response(calls=_calls(1, "d"), response_id="r2")])
    with pytest.raises(MetaAPIError, match="budget"):
        investigate_meta(make_case(), client=fake, max_tool_calls=2)
    assert len(fake.requests) == 2


def test_identical_queries_reuse_the_same_evidence():
    from datatrace.investigator import Investigation
    session = Investigation(make_case())
    try:
        first = session.query("current", "SELECT COUNT(*) FROM orders")
        again = session.query("current", "SELECT  COUNT(*)\n FROM orders")
        assert again["evidence_id"] == first["evidence_id"] and again["cached"]
        assert len(session.evidence) == 1
    finally:
        session.close()


@pytest.mark.parametrize("final", [None, [], conclusion(classification="made_up"), conclusion(summary=""),
                                  conclusion(evidence_ids=[]), conclusion(correction_sql=42)])
def test_malformed_final_diagnosis_is_not_accepted(final):
    with pytest.raises(MetaAPIError):
        investigate_meta(make_case(), client=FakeMeta([response(final=final)]))


def test_missing_key_fails_before_any_request(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(MetaAPIError, match="MODEL_API_KEY"):
        MetaClient()


def test_key_cannot_be_sent_to_an_unapproved_host(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "test-placeholder")
    monkeypatch.setenv("META_BASE_URL", "https://unapproved.example/v1")
    with pytest.raises(MetaAPIError, match="only sends credentials"):
        MetaClient()
