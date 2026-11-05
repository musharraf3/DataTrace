"""Load an incident's two snapshots from a DuckDB warehouse.

The agent never queries the warehouse. This connector opens the database file read-only with file,
network and extension access disabled, reads one fact table and one member table per snapshot (tables
or views you name), maps your column names and status codes onto the domain, and hands the rows to the
same strict validation as JSON and CSV input. The investigation then runs on that bounded in-memory
copy exactly as before, so the security model does not change.

Spec (JSON):
    {"format_version": 1, "domain": "healthcare", "description": "...", "contract": {...},
     "previous": {"facts": "snap_20091218.claims", "members": "snap_20091218.eligibility"},
     "current":  {"facts": "snap_20100131.claims", "members": "snap_20100131.eligibility"},
     "columns": {"claim_id": "clm_id", "paid_cents": "clm_pmt_amt", ...},   # domain name -> warehouse column
     "amount_unit": "dollars" | "cents",
     "values": {"status": {"P": "paid"}, "kind": {"O": "claim", "R": "reversal"}},
     "previous_sql": "...", "current_sql": "..."}
Any column or value left out of the mapping is expected to use the domain's own name.
"""

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .cases import Incident
from .domains import DOMAINS
from .inputs import MAX_BYTES, MAX_ROWS, InputError, validate_incident

_PART = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")
SPEC_KEYS = {"format_version", "domain", "description", "contract", "previous", "current", "columns",
             "amount_unit", "values", "previous_sql", "current_sql"}


def _identifier(name, label, parts=1):
    """Quote a table or column name after checking it against a strict identifier pattern."""
    pieces = name.split(".") if isinstance(name, str) else []
    if not 1 <= len(pieces) <= parts or not all(_PART.fullmatch(piece) for piece in pieces):
        raise InputError(f"{label} must be a plain identifier"
                         f"{' (optionally schema.table)' if parts > 1 else ''}, got {str(name)[:60]!r}.")
    return ".".join(f'"{piece}"' for piece in pieces)


def connect(path):
    """Open a DuckDB file read-only, with no file, network or extension access and locked settings."""
    import duckdb
    path = Path(path)
    if not path.is_file():
        raise InputError(f"DuckDB file not found: {path.name}")
    try:
        return duckdb.connect(str(path), read_only=True, config={
            "enable_external_access": False, "autoinstall_known_extensions": False,
            "autoload_known_extensions": False, "lock_configuration": True})
    except duckdb.Error as exc:
        raise InputError(f"Could not open the DuckDB file read-only: {str(exc)[:200]}") from None


def _read(connection, table, columns, label):
    """Fetch named columns from one table, refusing tables over the row cap."""
    import duckdb
    source = _identifier(table, f"{label} table", parts=3)
    quoted = [_identifier(shown, "Column") for shown, _ in columns]
    try:
        available = {column[0] for column in connection.execute(f"SELECT * FROM {source} LIMIT 0").description}
    except duckdb.Error:
        raise InputError(f"{label} table {table!r} was not found or cannot be read.") from None
    missing = [shown for shown, _ in columns if shown not in available]
    if missing:
        raise InputError(f"{label} table {table!r} has no column(s) {', '.join(missing)}.")
    select = ", ".join(expression.format(name) for name, (_, expression) in zip(quoted, columns))
    try:
        rows = connection.execute(f"SELECT {select} FROM {source} LIMIT {MAX_ROWS + 1}").fetchall()
    except duckdb.Error as exc:
        raise InputError(f"{label} table {table!r} could not be converted: {str(exc)[:200]}") from None
    if len(rows) > MAX_ROWS:
        raise InputError(f"{label} table {table!r} has more than {MAX_ROWS:,} rows; narrow it with a view.")
    return rows


def _cents(value, unit, line):
    if value is None:
        raise InputError(f"{line}: amount is empty.")
    try:
        amount = Decimal(value) * (100 if unit == "dollars" else 1)
    except (InvalidOperation, TypeError, ValueError):
        raise InputError(f"{line}: amount is not a number.") from None
    if amount != amount.to_integral_value():
        raise InputError(f"{line}: amount has fractions of a cent.")
    return int(amount)


def _code(value, mapping, vocabulary, label, line):
    shown = mapping.get(str(value), str(value)) if value is not None else None
    if shown not in vocabulary:
        raise InputError(f"{line}: {label} code {str(value)[:20]!r} is not mapped to one of {', '.join(sorted(vocabulary))}.")
    return shown


def load_snapshot(connection, tables, spec, domain):
    if not isinstance(tables, dict) or set(tables) != {"facts", "members"}:
        raise InputError("Each snapshot names a facts table and a members table.")
    d, names = domain, spec.get("columns") or {}
    unit, values = spec.get("amount_unit", "cents"), spec.get("values") or {}
    if not isinstance(names, dict) or not isinstance(values, dict) or unit not in {"cents", "dollars"}:
        raise InputError("columns and values must be objects; amount_unit must be cents or dollars.")
    column = lambda canonical: names.get(canonical, canonical)
    facts = _read(connection, tables["facts"], [
        (column(d.key), "CAST({} AS BIGINT)"), (column(d.member), "CAST({} AS BIGINT)"),
        (column(d.date), "strftime(CAST({} AS DATE), '%Y-%m-%d')"), (column("status"), "CAST({} AS VARCHAR)"),
        (column("kind"), "CAST({} AS VARCHAR)"), (column(d.value), "CAST({} AS DECIMAL(38, 4))")], "Facts")
    members = _read(connection, tables["members"], [
        (column(d.member), "CAST({} AS BIGINT)"), (column(d.attr), "CAST({} AS VARCHAR)")], "Members")
    status_codes, kind_codes = values.get("status") or {}, values.get("kind") or {}
    orders = []
    for index, (key, member, day, status, kind, amount) in enumerate(facts, start=1):
        line = f"{tables['facts']} row {index}"
        status = d.internal_status(_code(status, status_codes, set(d.status_map.values()), "status", line))
        kind = d.internal_kind(_code(kind, kind_codes, set(d.kind_map.values()), "kind", line))
        orders.append([key, member, day, status, kind, _cents(amount, unit, line)])
    return {"orders": orders, "customers": [list(row) for row in members]}


def load_spec(raw):
    if isinstance(raw, (str, bytes)) and len(raw) > MAX_BYTES:
        raise InputError("Warehouse spec is too large.")
    try:
        spec = json.loads(raw)
    except (ValueError, UnicodeError):
        raise InputError("Warehouse spec must be valid JSON.") from None
    if not isinstance(spec, dict) or spec.get("format_version") != 1:
        raise InputError("Expected warehouse spec format_version 1.")
    unknown = set(spec) - SPEC_KEYS
    if unknown:
        raise InputError(f"Unknown warehouse spec field(s): {', '.join(sorted(unknown))}.")
    if spec.get("domain", "revenue") not in DOMAINS:
        raise InputError(f"Unknown domain; use one of {', '.join(DOMAINS)}.")
    return spec


def load_incident(db_path, spec):
    """Read both snapshots from DuckDB and return a validated Incident."""
    if not isinstance(spec, dict):
        spec = load_spec(spec)
    domain = DOMAINS[spec.get("domain", "revenue")]
    connection = connect(db_path)
    try:
        snapshots = {name: load_snapshot(connection, spec.get(name), spec, domain) for name in ["previous", "current"]}
    finally:
        connection.close()
    contract = spec.get("contract")
    description = spec.get("description") or (
        f"{contract.get('name', 'The metric') if isinstance(contract, dict) else 'The metric'} moved between two "
        "warehouse snapshots. Establish how much of the change is real and how much is a reporting error.")
    incident = Incident("warehouse", description, contract, snapshots, spec.get("previous_sql"),
                        spec.get("current_sql"), "unlabeled", "warehouse", domain.name)
    return validate_incident(incident)


DEMO_COLUMNS = {"claim_id": "clm_id", "member_id": "bene_key", "service_date": "clm_from_dt",
                "status": "clm_status_cd", "kind": "clm_adj_cd", "paid_cents": "clm_pmt_amt", "plan": "plan_name"}
DEMO_CODES = {"status": {"P": "paid", "A": "pending", "D": "denied"}, "kind": {"O": "claim", "R": "reversal"}}


def write_demo(db_path, kind="eligibility_spans"):
    """Write a demo claims warehouse (DATE columns, dollar DECIMALs, status codes) and return its spec.

    Built from a CMS DE-SynPUF incident so the warehouse path can be checked against the JSON path."""
    import duckdb
    from .healthcare import MONTHS, make_claims_case
    from .domains import HEALTHCARE as d
    incident = make_claims_case(kind)
    _, _, previous_cut, current_cut = MONTHS["2009-11"]
    status_code = {shown: code for code, shown in DEMO_CODES["status"].items()}
    kind_code = {shown: code for code, shown in DEMO_CODES["kind"].items()}
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    connection = duckdb.connect(str(db_path))
    sides = {}
    try:
        for side, cut in [("previous", previous_cut), ("current", current_cut)]:
            schema = "snap_" + cut.replace("-", "_")
            connection.execute(f"CREATE SCHEMA {schema}")
            connection.execute(f"CREATE TABLE {schema}.claims (clm_id BIGINT, bene_key BIGINT, clm_from_dt DATE, "
                               "clm_status_cd VARCHAR, clm_adj_cd VARCHAR, clm_pmt_amt DECIMAL(14, 2))")
            connection.execute(f"CREATE TABLE {schema}.eligibility (bene_key BIGINT, plan_name VARCHAR)")
            snapshot = incident.snapshots[side]
            connection.executemany(f"INSERT INTO {schema}.claims VALUES (?, ?, ?, ?, ?, ?)", [
                (key, member, day, status_code[d.status(status)], kind_code[d.kind(kind_)], Decimal(cents) / 100)
                for key, member, day, status, kind_, cents in snapshot["orders"]])
            connection.executemany(f"INSERT INTO {schema}.eligibility VALUES (?, ?)", snapshot["customers"])
            sides[side] = {"facts": f"{schema}.claims", "members": f"{schema}.eligibility"}
    finally:
        connection.close()
    return {"format_version": 1, "domain": "healthcare", "description": incident.description,
            "contract": incident.contract, **sides, "columns": DEMO_COLUMNS, "amount_unit": "dollars",
            "values": DEMO_CODES, "previous_sql": incident.previous_sql, "current_sql": incident.current_sql}
