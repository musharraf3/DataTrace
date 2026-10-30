import json
from pathlib import Path

import pytest

from datatrace.cases import all_cases, heldout_cases, make_case
from datatrace.cli import main
from datatrace.evaluate import evaluate
from datatrace.inputs import fingerprint
from datatrace.meta import MetaAPIError, investigate_baseline
from datatrace.reporting import estimate_cost, markdown_report
from datatrace.investigator import offline_walkthrough
from test_meta import FakeMeta, conclusion, response


def test_baseline_receives_raw_inputs_but_no_execution_results():
    fake = FakeMeta([response(final=conclusion(evidence_ids=[]))])
    report = investigate_baseline(make_case(), client=fake)
    payload = json.loads(fake.requests[0]["inputs"])
    assert fake.requests[0]["tools_enabled"] is False
    assert "snapshot_data" in payload
    assert "initial_evidence" not in payload and "initial_replay" not in payload
    assert report["evidence"] == [] and report["usage"]["tool_calls"] == 0


def test_baseline_cannot_fabricate_executed_evidence():
    with pytest.raises(MetaAPIError, match="baseline"):
        investigate_baseline(make_case(), client=FakeMeta([response(final=conclusion())]))


def test_report_contains_provenance_and_portable_markdown():
    case = make_case()
    report = offline_walkthrough(case)
    text = markdown_report(report)
    assert report["input_sha256"] == fingerprint(case)
    assert "Candidate SQL" in text and "Verified: True" in text
    assert "offline_scripted" in text


def test_pricing_is_explicit_and_invalid_rates_fail():
    assert estimate_cost({"input_tokens": 1000, "output_tokens": 1000}) is None
    assert estimate_cost({"input_tokens": 1000, "output_tokens": 1000}, 1, 2)["estimated_usd"] == 0.003
    with pytest.raises(ValueError):
        estimate_cost({}, float("nan"), 1)


def test_stress_cases_have_distinct_reproducible_inputs():
    source, stress = all_cases(), heldout_cases()
    assert len(stress) == 20
    assert [fingerprint(c) for c in stress] == [fingerprint(c) for c in heldout_cases()]
    assert all(fingerprint(a) != fingerprint(b) for a, b in zip(source, stress))
    result = evaluate(split="stress")
    assert result["correct"] == 20 and result["errors"] == 0


def test_cli_sample_investigate_and_verify(tmp_path, capsys):
    sample = tmp_path / "sample.json"
    report_dir = tmp_path / "reports"
    main(["sample", "--output", str(sample)])
    main(["investigate", str(sample), "--output-dir", str(report_dir)])
    report = json.loads((report_dir / "report.json").read_text())
    assert report["validation"]["verified"]
    assert (report_dir / "report.md").is_file()
    sql = tmp_path / "correction.sql"
    sql.write_text(report["correction_sql"])
    main(["verify", str(sample), str(sql)])


def test_cli_paid_mode_requires_explicit_opt_in(tmp_path):
    sample = tmp_path / "sample.json"
    main(["sample", "--output", str(sample)])
    with pytest.raises(SystemExit) as error:
        main(["investigate", str(sample), "--mode", "meta"])
    assert error.value.code == 2


def test_evaluation_failures_stay_in_denominators_and_flag_unknown_usage():
    result = evaluate("meta", client=FakeMeta([]), cases=[make_case(), make_case("growth")])
    assert result["total"] == result["errors"] == 2
    assert result["repair_success"]["denominator"] == 1
    assert result["inappropriate_repairs"]["denominator"] == 1
    assert result["unobserved_repair_attempts_due_to_errors"] == 1
    assert result["usage_incomplete"]
