"""Streamlit application: load inputs, investigate, verify, and export evidence."""

import copy
import io
import json
import os
import zipfile
from dataclasses import replace
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from .cases import make_case
from .inputs import InputError, bundle_dict, fingerprint, load_bundle, load_csv, snapshot_csv, validate_incident
from .investigator import Investigation, offline_walkthrough
from .meta import MetaAPIError, investigate_meta
from .reporting import estimate_cost, markdown_report
from .runner import QueryRejected


def _example_zip(case):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("incident.json", json.dumps(bundle_dict(case), indent=2))
        for snapshot in ["previous", "current"]:
            for table in ["orders", "customers"]:
                archive.writestr(f"{snapshot}_{table}.csv", snapshot_csv(case, snapshot, table))
    return output.getvalue()


def _inputs(case, source):
    if source == "Incident JSON":
        uploaded = st.file_uploader("Incident JSON bundle", type=["json"])
        if uploaded is None:
            st.info("Upload an incident bundle, or download a sample from the sidebar.")
            return None
        case = load_bundle(uploaded.getvalue())
    elif source == "Four CSV snapshots":
        st.caption("Use the exact sample CSV headers. Orders require integer USD cents and unique order IDs; duplicate customer rows are allowed for investigation.")
        snapshots = {}
        ready = True
        left, right = st.columns(2)
        for snapshot, column in [("previous", left), ("current", right)]:
            snapshots[snapshot] = {}
            for table in ["orders", "customers"]:
                upload = column.file_uploader(f"{snapshot.title()} {table} CSV", type=["csv"], key=f"{snapshot}_{table}")
                if upload is None:
                    ready = False
                else:
                    snapshots[snapshot][table] = load_csv(upload.getvalue(), table)
        if not ready:
            st.info("Upload all four snapshots to begin.")
            return None
        case = replace(case, snapshots=snapshots, expected_classification="unlabeled", family="custom")
    seed = fingerprint(case)[:12]
    with st.expander("Metric definition and input SQL", expanded=True):
        description = st.text_area("Incident description", case.description, key=f"description-{seed}", max_chars=4000)
        a, b, c = st.columns(3)
        start = a.date_input("Period starts", date.fromisoformat(case.contract["start"]), key=f"start-{seed}")
        end = b.date_input("Period ends (exclusive)", date.fromisoformat(case.contract["end_exclusive"]), key=f"end-{seed}")
        choices = ["exclude", "include", "unknown"]
        policy = c.selectbox("Refund treatment", choices, index=choices.index(case.contract["refund_policy"] or "unknown"), key=f"policy-{seed}")
        statuses = ["paid", "pending", "cancelled"]
        status = st.selectbox("Eligible order status", statuses, index=statuses.index(case.contract["status"]), key=f"status-{seed}")
        st.caption("Supported contract: one row per eligible order_id, integer USD cents, all eligible orders including unmatched customers. Dates include the start and exclude the end.")
        before, after = st.columns(2)
        previous_sql = before.text_area("Previous SQL", case.previous_sql, height=180, key=f"prior-{seed}", max_chars=10000)
        current_sql = after.text_area("Current SQL", case.current_sql, height=180, key=f"current-{seed}", max_chars=10000)
        contract = {**case.contract, "start": start.isoformat(), "end_exclusive": end.isoformat(),
                    "refund_policy": None if policy == "unknown" else policy, "status": status}
        case = validate_incident(replace(case, description=description, contract=contract,
                                         previous_sql=previous_sql, current_sql=current_sql))
    with st.expander("Inspect input snapshots"):
        for snapshot in ["previous", "current"]:
            left, right = st.columns(2)
            for table, column in [("orders", left), ("customers", right)]:
                headers = ["order_id", "customer_id", "order_date", "status", "kind", "revenue_cents"] if table == "orders" else ["customer_id", "region"]
                column.caption(f"{snapshot.title()} {table} · {len(case.snapshots[snapshot][table])} rows")
                column.dataframe(pd.DataFrame(case.snapshots[snapshot][table], columns=headers).head(100), use_container_width=True, hide_index=True)
    st.download_button("Download current incident JSON", json.dumps(bundle_dict(case), indent=2),
                       file_name="incident.json", mime="application/json")
    return case


def _result(case, report, context_key):
    replay = report["replay"]
    old_total, current_total = replay[0]["revenue_cents"] / 100, replay[3]["revenue_cents"] / 100
    a, b, c = st.columns(3)
    a.metric("Previous reported revenue", f"${old_total:,.2f}")
    b.metric("Current reported revenue", f"${current_total:,.2f}", f"${current_total - old_total:+,.2f}")
    c.metric("Executed evidence items", len(report["evidence"]))
    finding, evidence_tab, repair_tab, export_tab = st.tabs(["Finding", "Execution evidence", "Verify a correction", "Export report"])
    with finding:
        st.subheader(report["classification"].replace("_", " ").title())
        st.text(report["summary"])
        for issue in report.get("consistency_issues", []):
            st.warning(issue)
        st.caption(report["diagnosis_source"] + " · " + report["limitations"])
        st.subheader("Separate code changes from data changes")
        st.dataframe(replay, use_container_width=True, hide_index=True)
        totals = {(row["sql_version"], row["snapshot"]): row["revenue_cents"] / 100 for row in replay}
        old = totals[("previous", "previous")]
        code = totals[("current", "previous")] - old
        data = totals[("previous", "current")] - old
        interaction = totals[("current", "current")] - old - code - data
        st.bar_chart(pd.DataFrame({"USD": [code, data, interaction]}, index=["SQL effect on old data", "Data effect under old SQL", "Interaction"]))
        st.caption("An exact arithmetic replay decomposition. Interaction captures combined effects; this is not proof of real-world causation.")
        if report.get("correction_sql"):
            st.subheader("Candidate correction")
            st.code(report["correction_sql"], language="sql")
        validation = report.get("validation")
        if validation:
            (st.success if validation["verified"] else st.warning)(validation["reason"])
            with st.expander("Independent validation details"):
                st.json(validation)
    with evidence_tab:
        for item in report["evidence"]:
            with st.expander(f"{item['evidence_id']} · {item['snapshot']} snapshot · {item.get('total_row_count', len(item['rows']))} result rows"):
                st.code(item["sql"], language="sql")
                st.dataframe(pd.DataFrame(item["rows"], columns=item["columns"]), use_container_width=True, hide_index=True)
                if item["truncated"]:
                    st.warning("Displayed rows are capped. Replay totals and contract validation use complete bounded results; a sampled diagnostic query cannot prove full coverage.")
        if report.get("trace"):
            with st.expander("Meta tool trace"):
                st.json(report["trace"])
    with repair_tab:
        candidate = st.text_area("Candidate SQL to verify", report.get("correction_sql") or case.current_sql,
                                 height=160, key=f"candidate-{context_key}", max_chars=10000)
        st.caption("Check the complete current-snapshot order/value multiset against the supplied contract. This does not change data or contact Meta.")
        if st.button("Verify candidate SQL"):
            session = Investigation(case)
            try:
                checked = session.verify(candidate)
            finally:
                session.close()
            (st.success if checked["verified"] else st.warning)(checked["reason"])
            st.json(checked)
    with export_tab:
        st.json({"generated_at": report["generated_at"], "input_sha256": report["input_sha256"],
                 "elapsed_seconds": report.get("elapsed_seconds"), "usage": report["usage"],
                 "cost_estimate": report.get("cost_estimate")})
        left, right = st.columns(2)
        left.download_button("Download JSON evidence", json.dumps(report, indent=2), file_name="datatrace-report.json", mime="application/json")
        right.download_button("Download readable report", markdown_report(report), file_name="datatrace-report.md", mime="text/markdown")


def main():
    load_dotenv()
    st.set_page_config(page_title="DataTrace | Metric investigator", page_icon="🔎", layout="wide")
    st.markdown("""<style>
    .stApp {background:#f5f7fb;color:#18243a}
    h1,h2,h3 {color:#14213b!important}
    div[data-testid="stMetric"] {background:white;padding:20px;border:1px solid #e2e8f0;border-radius:12px}
    .stButton>button[kind="primary"] {background:#214ed3;border:0;border-radius:8px}
    </style>""", unsafe_allow_html=True)
    st.caption("DATATRACE / SQL METRIC INVESTIGATION")
    st.title("Did the business change—or did the calculation break?")
    st.write("Replay the SQL, inspect the evidence, and verify a correction before changing a metric.")
    with st.sidebar:
        st.header("Investigation setup")
        names = ["Revenue incident 01", "Revenue incident 02", "Revenue incident 03", "Revenue incident 04", "Revenue incident 05"]
        scenario = st.selectbox("Synthetic incident", names)
        variant = st.selectbox("Data variant", [1, 2, 3, 4])
        mode = st.radio("Investigation mode", ["Offline evidence walkthrough", "Live Meta investigator"])
        source = st.radio("Input source", ["Bundled example", "Incident JSON", "Four CSV snapshots"])
        st.caption("Offline mode runs deterministic contract checks. Live mode uses billable Meta inference. SQL runs locally in memory; no production connection is used.")
        key_ready = bool(os.environ.get("MODEL_API_KEY", "").strip())
        st.info("Meta key detected locally." if key_ready else "Add MODEL_API_KEY to local .env for live mode.")
        consent = st.checkbox("Allow this incident's data to be sent to Meta for this run", value=False) if mode.startswith("Live") else False
        with st.expander("Optional cost estimate"):
            use_prices = st.checkbox("Use my current token prices")
            input_rate = st.number_input("Input USD per million tokens", min_value=0.0, value=0.0, step=0.1)
            output_rate = st.number_input("Output USD per million tokens", min_value=0.0, value=0.0, step=0.1)
            st.caption("Estimates use your rates, exclude discounts/taxes, and are not a spending cap.")
    family = ["duplicate_join", "growth", "ambiguous", "dropped_records", "date_filter"][names.index(scenario)]
    case = make_case(family, variant - 1)
    st.sidebar.download_button("Download example JSON + CSVs", _example_zip(case), file_name="datatrace-input-template.zip", mime="application/zip")
    try:
        case = _inputs(case, source)
    except (InputError, TypeError, ValueError) as exc:
        st.error(str(exc))
        return
    if case is None:
        return
    context_key = fingerprint(case) + ":" + mode
    if st.button("Investigate metric change", type="primary", disabled=mode.startswith("Live") and not (key_ready and consent)):
        try:
            with st.spinner("Executing evidence queries and verifying the metric contract…"):
                report = investigate_meta(case) if mode.startswith("Live") else offline_walkthrough(case)
            st.session_state["result"] = (context_key, report)
            history = st.session_state.get("run_history", [])
            st.session_state["run_history"] = (history + [copy.deepcopy(report)])[-5:]
        except (MetaAPIError, QueryRejected, ValueError) as exc:
            st.session_state.pop("result", None)
            st.error(str(exc))
    saved = st.session_state.get("result")
    if saved and saved[0] == context_key:
        report = copy.deepcopy(saved[1])
        if use_prices and report["mode"] == "meta_live":
            report["cost_estimate"] = estimate_cost(report["usage"], input_rate, output_rate)
        _result(case, report, context_key)
    else:
        st.info("Choose or upload an incident, review its SQL and definition, then investigate.")
    history = st.session_state.get("run_history", [])
    if history:
        st.sidebar.caption(f"{len(history)} recent run(s) retained in this session only.")
        st.sidebar.download_button("Download recent run history", json.dumps(history, indent=2), file_name="datatrace-history.json", mime="application/json")
    st.divider()
    st.caption("Meta Global AI Developer Hackathon 2026 · Local analytical prototype · Execution evidence before explanations")
