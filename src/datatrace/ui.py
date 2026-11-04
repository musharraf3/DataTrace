"""Streamlit application: load inputs, investigate, verify, and export evidence."""

import copy
import io
import json
import os
import zipfile
from dataclasses import replace
from datetime import date

import altair as alt
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
    with st.expander("Metric definition and input SQL", expanded=source != "Bundled example"):
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


def _revenue_bridge(previous_cents, current_cents, reconciliation):
    steps = [("Prior reported", 0, previous_cents, "Reported total")]
    prior_expected = reconciliation["previous_expected_cents"]
    current_expected = reconciliation["current_expected_cents"]
    if previous_cents != prior_expected:
        steps.append(("Prior correction", previous_cents, prior_expected, "Reporting adjustment"))
    steps.extend([
        ("Underlying change", prior_expected, current_expected, "Contract-backed movement"),
        ("Current error", current_expected, current_cents, "Reporting adjustment"),
        ("Current reported", 0, current_cents, "Reported total"),
    ])
    frame = pd.DataFrame(steps, columns=["Step", "Start", "End", "Type"])
    frame = frame.assign(Start=frame["Start"] / 100, End=frame["End"] / 100)
    frame["Amount"] = frame["End"] - frame["Start"]
    frame["Label"] = frame["Amount"].map(lambda amount: f"${amount:,.2f}")
    axis = alt.X("Step:N", sort=frame["Step"].tolist(), title=None, axis=alt.Axis(labelAngle=0, labelLimit=140))
    base = alt.Chart(frame).encode(x=axis)
    bars = base.mark_bar(size=54, cornerRadius=3).encode(
        y=alt.Y("Start:Q", title="Revenue (USD)", axis=alt.Axis(format="$,.0f")),
        y2="End:Q",
        color=alt.Color("Type:N", scale=alt.Scale(
            domain=["Reported total", "Contract-backed movement", "Reporting adjustment"],
            range=["#3656ae", "#0f8179", "#c05e29"]), legend=alt.Legend(title=None, orient="bottom")),
        tooltip=["Step:N", alt.Tooltip("Amount:Q", format="$,.2f"),
                 alt.Tooltip("Start:Q", format="$,.2f"), alt.Tooltip("End:Q", format="$,.2f")],
    )
    labels = base.mark_text(dy=-12, fontWeight="bold", color="#17264a").encode(y="End:Q", text="Label:N")
    st.altair_chart((bars + labels).properties(height=235), use_container_width=True)


def _result(case, report, context_key):
    replay = report["replay"]
    previous_cents, current_cents = replay[0]["revenue_cents"], replay[3]["revenue_cents"]
    reconciliation = report.get("reconciliation")
    st.caption("INVESTIGATION BRIEF")
    st.subheader(report["classification"].replace("_", " ").title())
    a, b, c = st.columns(3)
    a.metric("Reported revenue change", f"{(current_cents - previous_cents) / 100:+,.2f} USD")
    if reconciliation is None:
        b.metric("Underlying change", "Undetermined")
        c.metric("Reporting error", "Undetermined")
    else:
        b.metric("Underlying change", f"{reconciliation['underlying_change_cents'] / 100:+,.2f} USD")
        c.metric("Current reporting error", f"{reconciliation['current_error_cents'] / 100:+,.2f} USD")
    finding, evidence_tab, repair_tab, export_tab = st.tabs(["Finding", "Execution evidence", "Verify a correction", "Export report"])
    with finding:
        if reconciliation is None:
            st.info("Set refund treatment in the metric definition and investigate again to reconcile the change.")
        else:
            st.subheader("How the reported number moved")
            _revenue_bridge(previous_cents, current_cents, reconciliation)
            st.caption("Underlying change uses the same order contract for both snapshots. Reporting error compares the query with the contract in each snapshot.")
        st.text(report["summary"])
        for issue in report.get("consistency_issues", []):
            st.warning(issue)
        st.caption(report["diagnosis_source"] + " · " + report["limitations"])
        validation = report.get("validation")
        if validation:
            if validation["verified"] and report.get("correction_sql"):
                st.subheader(f"Verified corrected revenue · ${validation['actual_revenue_cents'] / 100:,.2f}")
            (st.success if validation["verified"] else st.warning)(validation["reason"])
            with st.expander("Independent validation details"):
                st.json(validation)
        if reconciliation and reconciliation["affected_orders"]:
            count = reconciliation["affected_order_count"]
            st.subheader(f"Affected orders ({count:,})")
            st.caption(f"Reported rows from {reconciliation['current_evidence_id']} compared with the order-level contract.")
            orders = pd.DataFrame(reconciliation["affected_orders"])
            for column in ["reported_cents", "expected_cents", "difference_cents"]:
                orders[column] = orders[column].map(lambda value: f"${value / 100:,.2f}")
            st.dataframe(orders.rename(columns={"order_id": "Order", "reported_cents": "Reported USD",
                "expected_cents": "Expected USD", "difference_cents": "Difference USD",
                "reported_rows": "Reported rows", "expected_rows": "Expected rows"}),
                use_container_width=True, hide_index=True)
            if count > len(orders):
                st.caption("Showing the 100 largest differences by absolute value.")
        if report.get("correction_sql"):
            with st.expander("View candidate SQL"):
                st.code(report["correction_sql"], language="sql")
    with evidence_tab:
        st.subheader("Four-way SQL and snapshot replay")
        st.dataframe(replay, use_container_width=True, hide_index=True)
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
    .block-container {padding-top:2.25rem;max-width:1150px}
    .trace-hero {padding:1.7rem 2rem;border-radius:20px;margin-bottom:1.25rem;
      background:linear-gradient(120deg,#101f43,#233c79);color:#fff}
    .trace-hero .trace-brand {font-size:.78rem;font-weight:750;letter-spacing:.16em;color:#b6d3ff}
    .trace-hero h1 {color:#fff!important;margin:.4rem 0;font-size:clamp(1.55rem,4vw,2.7rem);line-height:1.12}
    .trace-hero p {color:#e1ebfc;margin:.65rem 0 0;max-width:65ch}
    h2,h3 {color:#14213b!important}
    div[data-testid="stMetric"] {background:white;padding:16px;border:1px solid #dfe6f4;border-radius:12px}
    div[data-testid="stMetricValue"] {font-size:clamp(1.15rem,2.5vw,1.8rem)}
    div[data-testid="stText"] pre {white-space:pre-wrap;overflow-wrap:anywhere}
    .stButton>button[kind="primary"] {background:#214ed3;border:0;border-radius:8px}
    </style>""", unsafe_allow_html=True)
    st.markdown("""<div class="trace-hero">
    <div class="trace-brand">DATATRACE · REVENUE INVESTIGATIONS</div>
    <h1>Find what moved your revenue.</h1>
    <p>Separate genuine movement from reporting errors, see which orders were affected, and check the correction.</p>
    </div>""", unsafe_allow_html=True)
    with st.sidebar:
        st.header("Investigation setup")
        names = ["Revenue incident 01", "Revenue incident 02", "Revenue incident 03", "Revenue incident 04", "Revenue incident 05"]
        scenario = st.selectbox("Synthetic incident", names)
        variant = st.selectbox("Data variant", [1, 2, 3, 4], index=1)
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
