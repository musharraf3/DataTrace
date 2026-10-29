"""Streamlit UI for the first DataTrace milestone."""

import json
import os

import streamlit as st
from dotenv import load_dotenv

from datatrace.cases import make_case
from datatrace.investigator import offline_walkthrough
from datatrace.meta import MetaAPIError, investigate_meta
from datatrace.runner import QueryRejected

load_dotenv()
st.set_page_config(page_title="DataTrace | Metric investigator", page_icon="🔎", layout="wide")
st.markdown("""<style>
.stApp {background:#f5f7fb; color:#18243a}
h1,h2,h3 {color:#14213b!important}
div[data-testid="stMetric"] {background:white;padding:20px;border:1px solid #e2e8f0;border-radius:12px}
.stButton>button[kind="primary"] {background:#214ed3;border:0;border-radius:8px}
</style>""", unsafe_allow_html=True)
st.caption("DATATRACE  /  METRIC INVESTIGATION")
st.title("Did the business change—or did the calculation break?")
st.write("Follow the SQL, test the explanation, and preserve the changes that are real.")

with st.sidebar:
    st.header("Investigation setup")
    scenario = st.selectbox("Synthetic incident", ["Revenue incident 01", "Revenue incident 02", "Revenue incident 03"])
    variant = st.selectbox("Data variant", [1, 2, 3, 4])
    mode = st.radio("Investigation mode", ["Offline evidence walkthrough", "Live Meta investigator"])
    st.caption("Offline mode runs scripted diagnostics. Live mode sends this synthetic incident to Meta Model API and uses billable inference.")
    st.caption("SQL runner: isolated, in-memory SQLite. DuckDB migration is planned.")
    key_ready = bool(os.environ.get("MODEL_API_KEY", "").strip())
    st.info("Meta key detected locally." if key_ready else "Set MODEL_API_KEY in .env to enable live Meta mode.")

family = {"Revenue incident 01": "duplicate_join", "Revenue incident 02": "growth", "Revenue incident 03": "ambiguous"}[scenario]
case = make_case(family, variant - 1)
context_key = f"{case.case_id}:{mode}"
with st.expander("Metric definition and input SQL", expanded=True):
    st.json(case.contract)
    before, after = st.columns(2)
    before.caption("Previous SQL")
    before.code(case.previous_sql, language="sql")
    after.caption("Current SQL")
    after.code(case.current_sql, language="sql")

if st.button("Investigate metric change", type="primary", disabled=mode.startswith("Live") and not key_ready):
    try:
        with st.spinner("Executing evidence queries and checking the metric contract…"):
            report = investigate_meta(case) if mode.startswith("Live") else offline_walkthrough(case)
        st.session_state["result"] = (context_key, report)
    except (MetaAPIError, QueryRejected, ValueError) as exc:
        st.session_state.pop("result", None)
        st.error(str(exc))

saved = st.session_state.get("result")
if saved and saved[0] == context_key:
    report = saved[1]
    replay = report["replay"]
    old_total, current_total = replay[0]["revenue_cents"] / 100, replay[3]["revenue_cents"] / 100
    a, b, c = st.columns(3)
    a.metric("Previous reported revenue", f"${old_total:,.2f}")
    b.metric("Current reported revenue", f"${current_total:,.2f}", f"${current_total - old_total:+,.2f}")
    c.metric("Executed evidence items", len(report["evidence"]))
    st.subheader(report["classification"].replace("_", " ").title())
    st.write(report["summary"])
    st.caption(report["limitations"])
    st.subheader("Separate code changes from data changes")
    st.dataframe(replay, use_container_width=True, hide_index=True)
    if report.get("correction_sql"):
        st.subheader("Candidate correction")
        st.code(report["correction_sql"], language="sql")
    validation = report.get("validation")
    if validation:
        (st.success if validation["verified"] else st.warning)(validation["reason"])
        with st.expander("Independent validation details"):
            st.json(validation)
    st.subheader("Executed evidence")
    for evidence in report["evidence"]:
        with st.expander(f"{evidence['evidence_id']} · {evidence['snapshot']} snapshot · {len(evidence['rows'])} rows"):
            st.code(evidence["sql"], language="sql")
            st.dataframe([dict(zip(evidence["columns"], row)) for row in evidence["rows"]], use_container_width=True)
            if evidence["truncated"]:
                st.warning("Results truncated. Do not infer complete coverage from this sample.")
    if report.get("trace"):
        with st.expander("Meta tool trace and usage"):
            st.json({"usage": report["usage"], "trace": report["trace"]})
    st.download_button("Download investigation evidence", json.dumps(report, indent=2),
                       file_name="datatrace-investigation.json", mime="application/json")
else:
    st.info("Choose a synthetic incident and run an investigation to inspect its evidence.")

st.divider()
st.caption("Meta Global AI Developer Hackathon 2026 · Synthetic data only · Prototype; no production database connection")
