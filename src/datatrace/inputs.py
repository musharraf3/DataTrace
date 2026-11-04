"""Strict input boundary for the supported order-revenue incident format."""

import csv
import hashlib
import io
import json
import re
from datetime import date

from .cases import Incident

MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 120000
ORDER_COLUMNS = ["order_id", "customer_id", "order_date", "status", "kind", "revenue_cents"]
CUSTOMER_COLUMNS = ["customer_id", "region"]


class InputError(ValueError):
    pass


def _date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise InputError(f"{label} must be an ISO date (YYYY-MM-DD).")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise InputError(f"{label} is not a real calendar date.") from None
    return value


def validate_contract(contract):
    if not isinstance(contract, dict):
        raise InputError("Metric contract must be an object.")
    result = dict(contract)
    _date(result.get("start"), "Start date")
    _date(result.get("end_exclusive"), "Exclusive end date")
    if result["start"] >= result["end_exclusive"]:
        raise InputError("Exclusive end must be after start.")
    policy = result.get("refund_policy")
    if policy is not None and (not isinstance(policy, str) or policy not in {"include", "exclude"}):
        raise InputError("Refund policy must be include, exclude, or null for unknown.")
    if not isinstance(result.get("status"), str) or result["status"] not in {"paid", "pending", "cancelled"}:
        raise InputError("Status must be paid, pending, or cancelled.")
    if result.get("customer_coverage", "all orders, including unmatched customers") != "all orders, including unmatched customers":
        raise InputError("This version supports all eligible orders, including unmatched customers.")
    if result.get("grain", "one row per order_id") != "one row per order_id":
        raise InputError("Supported metric grain is one row per order_id.")
    if result.get("unit", "integer USD cents") != "integer USD cents":
        raise InputError("Supported metric unit is integer USD cents.")
    if not isinstance(result.get("name", "Revenue"), str) or len(result.get("name", "Revenue")) > 120:
        raise InputError("Metric name must be text of at most 120 characters.")
    return {"name": result.get("name", "Revenue"), "grain": "one row per order_id",
            "unit": "integer USD cents", "start": result["start"],
            "end_exclusive": result["end_exclusive"], "status": result["status"],
            "refund_policy": result.get("refund_policy"),
            "customer_coverage": "all orders, including unmatched customers"}


def _integer(value, label, *, positive=False):
    if type(value) is not int or abs(value) > 10**16 or (positive and value <= 0):
        raise InputError(f"{label} must be an integer within the supported range.")
    return value


def _validate_row(name, columns, row, seen):
    if isinstance(row, dict):
        if set(row) != set(columns):
            raise InputError(f"{name} columns must be {', '.join(columns)}.")
        row = [row[column] for column in columns]
    if not isinstance(row, (list, tuple)) or len(row) != len(columns):
        raise InputError(f"Invalid row shape for {name}.")
    if name == "orders":
        oid, cid, day, status, kind, cents = row
        _integer(oid, "order_id", positive=True)
        _integer(cid, "customer_id", positive=True)
        _integer(cents, "revenue_cents")
        _date(day, "order_date")
        if oid in seen:
            raise InputError(f"order_id {oid} appears more than once; source orders must be unique.")
        seen.add(oid)
        if not isinstance(status, str) or status not in {"paid", "pending", "cancelled"}:
            raise InputError(f"status must be paid, pending, or cancelled (got {str(status)[:20]!r}).")
        if not isinstance(kind, str) or kind not in {"sale", "refund"}:
            raise InputError(f"kind must be sale or refund (got {str(kind)[:20]!r}).")
    else:
        _integer(row[0], "customer_id", positive=True)
        if not isinstance(row[1], str) or len(row[1]) > 80:
            raise InputError("Region must be text of at most 80 characters.")
    return tuple(row)


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != {"orders", "customers"}:
        raise InputError("Each snapshot must contain orders and customers tables.")
    cleaned = {}
    for name, columns in [("orders", ORDER_COLUMNS), ("customers", CUSTOMER_COLUMNS)]:
        rows = snapshot[name]
        if not isinstance(rows, list) or len(rows) > MAX_ROWS:
            raise InputError(f"{name} must be a list with at most {MAX_ROWS} rows.")
        output, seen = [], set()
        for index, row in enumerate(rows, start=1):
            try:
                output.append(_validate_row(name, columns, row, seen))
            except InputError as exc:
                raise InputError(f"{name} row {index}: {exc}") from None
        cleaned[name] = output
    return cleaned


def validate_incident(incident):
    if not isinstance(incident.description, str) or not 1 <= len(incident.description) <= 4000:
        raise InputError("Incident description must contain 1–4,000 characters.")
    incident.contract = validate_contract(incident.contract)
    if not isinstance(incident.snapshots, dict) or set(incident.snapshots) != {"previous", "current"}:
        raise InputError("Provide previous and current snapshots.")
    incident.snapshots = {name: validate_snapshot(data) for name, data in incident.snapshots.items()}
    for sql in [incident.previous_sql, incident.current_sql]:
        if not isinstance(sql, str) or not 1 <= len(sql.strip()) <= 10000:
            raise InputError("Each metric SQL must contain 1–10,000 characters.")
    return incident


def bundle_dict(incident):
    """Export only public inputs, never evaluation labels or hidden family names."""
    return {"format_version": 1, "domain": getattr(incident, "domain", "revenue"), "description": incident.description,
            "contract": incident.contract, "snapshots": incident.snapshots,
            "previous_sql": incident.previous_sql, "current_sql": incident.current_sql}


def fingerprint(incident):
    payload = json.dumps(bundle_dict(incident), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def load_bundle(raw):
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise InputError("Incident JSON must be at most 32 MiB.")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("format_version") != 1:
            raise InputError("Expected incident format_version 1.")
        from .domains import DOMAINS
        domain = data.get("domain", "revenue")
        if domain not in DOMAINS:
            raise InputError(f"Unknown domain {str(domain)[:30]!r}; use one of {', '.join(DOMAINS)}.")
        incident = Incident("custom", data["description"], data["contract"], data["snapshots"],
                            data["previous_sql"], data["current_sql"], "unlabeled", "custom", domain)
        return validate_incident(incident)
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError("Invalid incident JSON. Use the downloadable template and supported schema.") from None


def _domain(domain):
    from .domains import get
    return domain if hasattr(domain, "fact") else get(domain)


def load_csv(raw, table, domain=None):
    """Load a fact ("orders") or dimension ("customers") table written in the domain's own vocabulary."""
    d = _domain(domain)
    if table not in {"orders", "customers"} or not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise InputError("Provide a supported CSV table of at most 32 MiB.")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        columns = d.fact_columns if table == "orders" else d.dim_columns
        internal = ORDER_COLUMNS if table == "orders" else CUSTOMER_COLUMNS
        if reader.fieldnames != columns:
            raise InputError(f"CSV header must be {','.join(columns)}.")
        rows = []
        integer_columns = {d.key, d.member, d.value}
        for line, row in enumerate(reader, start=2):
            if len(rows) >= MAX_ROWS:
                raise InputError(f"CSV has more than {MAX_ROWS:,} rows.")
            if None in row or any(value is None for value in row.values()):
                raise InputError(f"CSV line {line}: expected {len(columns)} comma-separated values.")
            try:
                parsed = {key: int(value) if key in integer_columns else value for key, value in row.items()}
            except ValueError:
                bad = next(k for k in integer_columns if k in row and not str(row[k]).lstrip("-").isdigit())
                raise InputError(f"CSV line {line}: {bad} must be a whole number (got {str(row[bad])[:20]!r}).") from None
            mapped = {name: parsed[shown] for name, shown in zip(internal, columns)}
            if table == "orders":
                mapped["status"] = d.internal_status(mapped["status"])
                mapped["kind"] = d.internal_kind(mapped["kind"])
            rows.append(mapped)
        snapshot = {"orders": rows if table == "orders" else [],
                    "customers": rows if table == "customers" else []}
        return validate_snapshot(snapshot)[table]
    except InputError:
        raise
    except (UnicodeError, ValueError, csv.Error):
        raise InputError("Invalid CSV. Use UTF-8, comma separators, and the template headers.") from None


def snapshot_csv(incident, snapshot, table):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    d = _domain(getattr(incident, "domain", "revenue"))
    writer.writerow(d.fact_columns if table == "orders" else d.dim_columns)
    rows = incident.snapshots[snapshot][table]
    writer.writerows([d.translate_fact(row) for row in rows] if table == "orders" else rows)
    return output.getvalue()
