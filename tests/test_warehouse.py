import json

import pytest

duckdb = pytest.importorskip("duckdb")

from datatrace import warehouse  # noqa: E402
from datatrace.cli import main  # noqa: E402
from datatrace.healthcare import make_claims_case  # noqa: E402
from datatrace.inputs import InputError, bundle_dict  # noqa: E402
from datatrace.investigator import offline_walkthrough  # noqa: E402


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    path = tmp_path_factory.mktemp("wh") / "claims.duckdb"
    return path, warehouse.write_demo(path)


def _snapshots(incident):
    return json.loads(json.dumps(bundle_dict(incident)["snapshots"]))


def test_warehouse_snapshots_match_the_json_incident(demo):
    path, spec = demo
    loaded = warehouse.load_incident(path, spec)
    original = make_claims_case("eligibility_spans")
    assert _snapshots(loaded) == _snapshots(original)
    assert loaded.domain == "healthcare" and loaded.current_sql == original.current_sql
    report = offline_walkthrough(loaded)
    assert report["classification"] == "mixed_change"
    assert report["reconciliation"]["current_error_cents"] == 64940000
    assert report["validation"]["verified"]


def test_dollar_amounts_must_be_whole_cents(tmp_path, demo):
    _, spec = demo
    path = tmp_path / "frac.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("CREATE TABLE c (clm_id BIGINT, bene_key BIGINT, clm_from_dt DATE, clm_status_cd VARCHAR, "
                       "clm_adj_cd VARCHAR, clm_pmt_amt DECIMAL(14, 3))")
    connection.execute("INSERT INTO c VALUES (1, 1, '2009-11-02', 'P', 'O', 10.005)")
    connection.execute("CREATE TABLE e (bene_key BIGINT, plan_name VARCHAR)")
    connection.close()
    bad = {**spec, "previous": {"facts": "c", "members": "e"}, "current": {"facts": "c", "members": "e"}}
    with pytest.raises(InputError, match="fractions of a cent"):
        warehouse.load_incident(path, bad)


def test_unmapped_codes_and_missing_columns_are_named(demo):
    path, spec = demo
    with pytest.raises(InputError, match="status code 'P' is not mapped"):
        warehouse.load_incident(path, {**spec, "values": {"kind": spec["values"]["kind"]}})
    with pytest.raises(InputError, match="no column"):
        warehouse.load_incident(path, {**spec, "columns": {**spec["columns"], "plan": "plan_code"}})


@pytest.mark.parametrize("name", ['claims; DROP TABLE x', 'a"b', "a.b.c.d", "1abc", "read_csv('x')", ""])
def test_table_and_column_names_cannot_inject_sql(demo, name):
    path, spec = demo
    with pytest.raises(InputError, match="plain identifier"):
        warehouse.load_incident(path, {**spec, "previous": {**spec["previous"], "facts": name}})
    with pytest.raises(InputError, match="plain identifier"):
        warehouse.load_incident(path, {**spec, "columns": {**spec["columns"], "claim_id": name}})


def test_connection_is_read_only_without_file_or_network_access(demo):
    path, _ = demo
    connection = warehouse.connect(path)
    try:
        for statement in ["CREATE TABLE z (a INT)", "SELECT * FROM read_csv('x.csv')", "COPY (SELECT 1) TO 'o.csv'",
                          "ATTACH 'other.duckdb'", "INSTALL httpfs", "SET enable_external_access = true"]:
            with pytest.raises(duckdb.Error):
                connection.execute(statement)
    finally:
        connection.close()


def test_views_that_read_files_are_blocked(tmp_path, demo):
    _, spec = demo
    (tmp_path / "secret.csv").write_text("clm_id\n1\n", encoding="utf-8")
    path = tmp_path / "view.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute(f"CREATE VIEW leak AS SELECT * FROM read_csv('{(tmp_path / 'secret.csv').as_posix()}')")
    connection.close()
    with pytest.raises(InputError, match="not found or cannot be read"):
        warehouse.load_incident(path, {**spec, "previous": {"facts": "leak", "members": "leak"}})


def test_row_cap_is_enforced(tmp_path, demo, monkeypatch):
    path, spec = demo
    monkeypatch.setattr(warehouse, "MAX_ROWS", 100)
    with pytest.raises(InputError, match="more than 100 rows"):
        warehouse.load_incident(path, spec)


def test_spec_rejects_unknown_fields_and_missing_files(tmp_path, demo):
    path, spec = demo
    with pytest.raises(InputError, match="Unknown warehouse spec field"):
        warehouse.load_spec(json.dumps({**spec, "sql_hook": "x"}))
    with pytest.raises(InputError, match="not found"):
        warehouse.load_incident(tmp_path / "missing.duckdb", spec)


def test_cli_builds_a_bundle_the_investigator_accepts(tmp_path, capsys):
    spec, db, out = tmp_path / "spec.json", tmp_path / "w.duckdb", tmp_path / "incident.json"
    main(["warehouse", str(spec), "--db", str(db), "--write-demo", "--output", str(out)])
    assert "2,808 current healthcare fact rows" in capsys.readouterr().out
    main(["investigate", str(out), "--output-dir", str(tmp_path / "report")])
    assert json.loads((tmp_path / "report" / "report.json").read_text())["classification"] == "mixed_change"
