import json
from copy import deepcopy

import pytest

from datatrace.cases import canonical_sql, make_case
from datatrace.inputs import InputError, bundle_dict, fingerprint, load_bundle, load_csv, snapshot_csv, validate_incident
from datatrace.investigator import offline_walkthrough


def test_bundle_round_trip_drops_gold_labels_and_preserves_incident():
    source = make_case("duplicate_join", 1)
    bundle = bundle_dict(source)
    assert "family" not in bundle and "expected_classification" not in bundle
    copy = load_bundle(json.dumps(bundle))
    assert fingerprint(copy) == fingerprint(source)
    assert copy.expected_classification == "unlabeled"
    assert offline_walkthrough(copy)["validation"]["verified"]


@pytest.mark.parametrize("table", ["orders", "customers"])
@pytest.mark.parametrize("snapshot", ["previous", "current"])
def test_csv_round_trip(table, snapshot):
    case = make_case()
    rows = load_csv(snapshot_csv(case, snapshot, table).encode(), table)
    assert rows == case.snapshots[snapshot][table]


@pytest.mark.parametrize("edit", [
    lambda data: data["contract"].update(start="2026-02-30"),
    lambda data: data["contract"].update(end_exclusive="2026-01-01"),
    lambda data: data["contract"].update(status="paid' OR 1=1 --"),
    lambda data: data["contract"].update(refund_policy="guess"),
    lambda data: data["contract"].update(grain="per customer"),
    lambda data: data["snapshots"]["current"]["orders"].append(data["snapshots"]["current"]["orders"][0]),
    lambda data: data["snapshots"]["current"]["orders"].__setitem__(0, [True, 1, "2026-10-01", "paid", "sale", 3]),
    lambda data: data.update(current_sql=""),
])
def test_invalid_contracts_and_source_rows_are_rejected(edit):
    data = deepcopy(bundle_dict(make_case()))
    edit(data)
    with pytest.raises(InputError):
        load_bundle(json.dumps(data))


def test_large_or_malformed_input_is_rejected():
    for raw in [b"x" * (1024 * 1024 + 1), b"{", b"null", b"[]"]:
        with pytest.raises(InputError):
            load_bundle(raw)
    with pytest.raises(InputError):
        load_csv(b"wrong,header\n1,2", "orders")


def test_custom_contract_status_and_refunds_are_honored():
    case = make_case()
    case.contract["status"] = "pending"
    case.contract["refund_policy"] = "include"
    case.current_sql = case.previous_sql = canonical_sql(case.contract)
    report = offline_walkthrough(validate_incident(case))
    assert report["replay"][3]["revenue_cents"] == 9000
    assert report["validation"]["verified"]


def test_more_than_one_hundred_rows_are_verified_completely():
    case = make_case("growth")
    for snapshot in case.snapshots.values():
        snapshot["orders"] += [(1000 + i, 1, "2026-10-10", "paid", "sale", 1) for i in range(150)]
    report = offline_walkthrough(case)
    assert report["replay"][0]["row_count"] == 153
    assert report["validation"]["verified"]
    assert report["evidence"][0]["truncated"]
    assert len(report["evidence"][0]["rows"]) == 100


def test_equal_totals_but_changed_orders_still_count_as_data_movement():
    case = make_case("duplicate_join")
    orders = case.snapshots["current"]["orders"]
    orders[0] = (*orders[0][:5], orders[0][5] + 100)
    orders[2] = (*orders[2][:5], orders[2][5] - 100)
    report = offline_walkthrough(case)
    assert report["classification"] == "mixed_change"
