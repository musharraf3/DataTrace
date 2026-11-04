import io
import json

import pytest

from datatrace.cases import make_case
from datatrace.meta import MetaAPIError, MetaClient, investigate_meta, investigate_baseline
from test_meta import FakeMeta, conclusion, response


def test_transport_uses_official_endpoint_and_no_tools_for_baseline(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "test-placeholder")
    monkeypatch.delenv("META_BASE_URL", raising=False)
    seen = []
    class Opener:
        def open(self, request, timeout):
            seen.append((request, timeout))
            return io.BytesIO(json.dumps(response(final=conclusion(evidence_ids=[]))).encode())
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
    MetaClient().complete(inputs="test", tools_enabled=False)
    request, timeout = seen[0]
    body = json.loads(request.data)
    assert request.full_url == "https://api.meta.ai/v1/responses"
    assert timeout == 180 and "tools" not in body and not body["store"]
    assert request.get_header("Authorization") == "Bearer test-placeholder"


@pytest.mark.parametrize("payload", [b"null", b"[]", b"not json"])
def test_malformed_transport_json_has_a_controlled_error(monkeypatch, payload):
    monkeypatch.setenv("MODEL_API_KEY", "test-placeholder")
    class Opener:
        def open(self, *args, **kwargs):
            return io.BytesIO(payload)
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
    with pytest.raises(MetaAPIError):
        MetaClient().complete(inputs="test")


def test_context_size_is_rejected_before_any_network_call(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "test-placeholder")
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: pytest.fail("Must reject before network"))
    with pytest.raises(MetaAPIError, match="too large"):
        MetaClient().complete(inputs="x" * 2500001)


def test_model_business_claim_cannot_override_a_failed_contract_check():
    fake = FakeMeta([response(final=conclusion(classification="genuine_change"))])
    report = investigate_meta(make_case(), client=fake)
    assert report["model_classification"] == "genuine_change"
    assert report["classification"] == "insufficient_evidence"
    assert report["consistency_issues"]


def test_baseline_has_the_same_missing_definition_guard():
    fake = FakeMeta([response(final=conclusion(evidence_ids=[], correction_sql="SELECT 1"))])
    report = investigate_baseline(make_case("ambiguous"), client=fake)
    assert report["classification"] == "insufficient_evidence"
    assert report["correction_sql"] is None
    assert report["model_correction_sql"] == "SELECT 1"


@pytest.mark.parametrize("bad_response", [None, {"output": None}, {"output": [42]},
                                          {"output": [{"type": "message", "content": None}]}])
def test_malformed_provider_output_never_crashes_with_type_errors(bad_response):
    with pytest.raises(MetaAPIError):
        investigate_meta(make_case(), client=FakeMeta([bad_response]))
