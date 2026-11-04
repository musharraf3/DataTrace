"""Streamlit application: describe a metric surprise, watch the Meta agent investigate, act on verified evidence."""

import copy
import html
import io
import json
import os
import tempfile
import time
import zipfile
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from .cases import make_case
from .inputs import InputError, bundle_dict, fingerprint, load_bundle, load_csv, snapshot_csv, validate_incident
from .investigator import Investigation, offline_walkthrough
from .meta import MetaAPIError, MetaClient, investigate_meta
from .openweight import make_agent_client
from .reporting import list_price_usd, markdown_report
from .runner import QueryRejected
from .domains import get as get_domain
from .healthcare import make_claims_case
from .scenarios import make_realistic_case

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
RECORDED = EXAMPLES / "recorded"
RESULTS = ROOT / "results"

LIVE, RECORDED_MODE, OFFLINE = "Live Meta agent", "Recorded live run", "Verifier only (no AI)"

SCENARIO_CHOICES = [
    ("★ Medicare claims: eligibility rebuild · CMS DE-SynPUF", ("synpuf", "eligibility_spans")),
    ("Claims: service-month cutoff edit · CMS DE-SynPUF", ("synpuf", "service_date_cutoff")),
    ("Claims: pending counted as paid · CMS DE-SynPUF", ("synpuf", "pending_counted")),
    ("Claims: genuine run-out · CMS DE-SynPUF", ("synpuf", "runout_growth")),
    ("Claims: reversal treatment undefined · CMS DE-SynPUF", ("synpuf", "reversal_policy")),
    ("★ Retail: Black Friday + CRM migration · 4,122 orders", ("realistic", "crm_migration")),
    ("Month-end cutoff edit · 4,122 orders", ("realistic", "cutoff_change")),
    ("Pending orders counted as paid · 4,122 orders", ("realistic", "status_filter")),
    ("Genuine holiday surge · 4,122 orders", ("realistic", "holiday_growth")),
    ("Refund treatment undefined · 4,122 orders", ("realistic", "refund_policy")),
    ("Mini: duplicate join · 6 orders", ("classic", "duplicate_join")),
    ("Mini: genuine growth · 6 orders", ("classic", "growth")),
    ("Mini: missing refund rule · 6 orders", ("classic", "ambiguous")),
    ("Mini: dropped records · 6 orders", ("classic", "dropped_records")),
    ("Mini: inclusive end date · 6 orders", ("classic", "date_filter")),
]

LABELS = {"calculation_defect": ("Calculation defect", "#b42318"),
          "genuine_change": ("Genuine business change", "#067647"),
          "mixed_change": ("Real growth + reporting defect", "#b54708"),
          "insufficient_evidence": ("Needs clarification", "#475467")}


# ---------------------------------------------------------------- safety helpers

def _html(text):
    """Escape model- or user-written text before it goes into an HTML block."""
    return html.escape(str(text or ""), quote=True)


def _md(text):
    """Model text in Markdown: neutralise $ (LaTeX) without changing meaning."""
    return str(text or "").replace("$", "\\$")



def _load_secrets():
    if os.environ.get("DATATRACE_SKIP_DOTENV") != "1":
        from dotenv import load_dotenv
        load_dotenv()
    # Touching st.secrets without a secrets.toml makes Streamlit render an error element,
    # so only read it when a secrets file actually exists (Streamlit Cloud provides one).
    try:
        if not st.secrets.load_if_toml_exists():
            return
        for name in ["MODEL_API_KEY", "DATATRACE_PUBLIC_DEMO", "DATATRACE_DAILY_LIVE_LIMIT"]:
            if name in st.secrets and not os.environ.get(name):
                os.environ[name] = str(st.secrets[name])
    except Exception:  # A malformed secrets file must not take the app down.
        pass


def _public_demo():
    return os.environ.get("DATATRACE_PUBLIC_DEMO") == "1"


def _ledger():
    path = Path(tempfile.gettempdir()) / "datatrace-daily-usage.json"
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        data = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        data = {}
    if data.get("date") != today:
        data = {"date": today, "count": 0}
    return path, data


def _budget_ok(kind):
    """Per-visitor and per-day caps protect the hosted demo's API credits."""
    if not _public_demo():
        return True, ""
    session_cap = {"investigation": 3, "intake": 6}[kind]
    if st.session_state.setdefault("usage_counts", {}).get(kind, 0) >= session_cap:
        return False, f"This public demo allows {session_cap} live {kind} runs per visitor. 'Recorded live run' replays real runs for free."
    _, data = _ledger()
    if data["count"] >= int(os.environ.get("DATATRACE_DAILY_LIVE_LIMIT", "60")):
        return False, "Today's shared live-run budget for the public demo is used up. Recorded runs remain available."
    return True, ""


def _record_use(kind):
    counts = st.session_state.setdefault("usage_counts", {})
    counts[kind] = counts.get(kind, 0) + 1
    if _public_demo():
        path, data = _ledger()
        data["count"] += 1
        try:
            path.write_text(json.dumps(data))
        except OSError:
            pass


# ---------------------------------------------------------------- inputs

def _example_zip(case):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("incident.json", json.dumps(bundle_dict(case), indent=2))
        for snapshot in ["previous", "current"]:
            for table in ["orders", "customers"]:
                archive.writestr(f"{snapshot}_{table}.csv", snapshot_csv(case, snapshot, table))
    return output.getvalue()


@st.cache_data(show_spinner=False)
def _cached_case(kind, name):
    if kind == "synpuf":
        return make_claims_case(name)
    return make_realistic_case(name) if kind == "realistic" else make_case(name, 1)


def _base_case(choice):
    return copy.deepcopy(_cached_case(*choice))


def _inputs(case, source):
    if source == "Incident JSON":
        uploaded = st.file_uploader("Incident JSON bundle", type=["json"])
        if uploaded is None:
            st.info("Upload an incident bundle, or download a template from the sidebar.")
            return None
        case = load_bundle(uploaded.getvalue())
    elif source == "Four CSV snapshots":
        dom = get_domain(case.domain)
        st.caption(f"Use the template CSV headers ({', '.join(dom.fact_columns)} and {', '.join(dom.dim_columns)}). "
                   f"Amounts are integer USD cents and {dom.key} values are unique; duplicate {dom.member} rows are allowed so the agent can detect them.")
        snapshots, ready = {}, True
        left, right = st.columns(2)
        for snapshot, column in [("previous", left), ("current", right)]:
            snapshots[snapshot] = {}
            for table in ["orders", "customers"]:
                shown = dom.fact if table == "orders" else dom.dim
                upload = column.file_uploader(f"{snapshot.title()} {shown} CSV", type=["csv"], key=f"{snapshot}_{table}")
                if upload is None:
                    ready = False
                else:
                    snapshots[snapshot][table] = load_csv(upload.getvalue(), table, dom)
        if not ready:
            st.info("Upload all four snapshots to begin.")
            return None
        case = replace(case, snapshots=snapshots, expected_classification="unlabeled", family="custom")
    seed = fingerprint(case)[:12]
    with st.expander("② Metric definition and SQL (editable)", expanded=source != "Bundled example"):
        description = st.text_area("Incident description", case.description, key=f"description-{seed}", max_chars=4000)
        a, b, c, d = st.columns(4)
        start = a.date_input("Period starts", date.fromisoformat(case.contract["start"]), key=f"start-{seed}")
        end = b.date_input("Period ends (exclusive)", date.fromisoformat(case.contract["end_exclusive"]), key=f"end-{seed}")
        choices = ["exclude", "include", "unknown"]
        policy = c.selectbox("Refund treatment", choices, index=choices.index(case.contract["refund_policy"] or "unknown"), key=f"policy-{seed}")
        statuses = ["paid", "pending", "cancelled"]
        status = d.selectbox("Eligible order status", statuses, index=statuses.index(case.contract["status"]), key=f"status-{seed}")
        dom = get_domain(case.domain)
        st.caption(f"Supported contract: one row per eligible {dom.key}, integer USD cents, all eligible {dom.items} "
                   f"including unmatched {dom.member_noun}s. Start inclusive, end exclusive. Refund treatment covers {dom.reversal_noun}.")
        before, after = st.columns(2)
        previous_sql = before.text_area("Previous SQL", case.previous_sql, height=170, key=f"prior-{seed}", max_chars=10000)
        current_sql = after.text_area("Current SQL", case.current_sql, height=170, key=f"current-{seed}", max_chars=10000)
        contract = {**case.contract, "start": start.isoformat(), "end_exclusive": end.isoformat(),
                    "refund_policy": None if policy == "unknown" else policy, "status": status}
        case = validate_incident(replace(case, description=description, contract=contract,
                                         previous_sql=previous_sql, current_sql=current_sql))
    with st.expander("Inspect input snapshots"):
        for snapshot in ["previous", "current"]:
            left, right = st.columns(2)
            dom = get_domain(case.domain)
            for table, column in [("orders", left), ("customers", right)]:
                headers = dom.fact_columns if table == "orders" else dom.dim_columns
                rows = case.snapshots[snapshot][table][:100]
                rows = [dom.translate_fact(r) for r in rows] if table == "orders" else rows
                shown = dom.fact if table == "orders" else dom.dim
                column.caption(f"{snapshot.title()} {shown} · {len(case.snapshots[snapshot][table]):,} rows (first 100 shown)")
                column.dataframe(pd.DataFrame(rows, columns=headers),
                                 width="stretch", hide_index=True, height=180)
    return case


# ---------------------------------------------------------------- intake (voice / screenshot / text)

def _intake(key_ready, scenario_key):
    with st.expander("① Start from what you saw: voice note, dashboard screenshot, or message", expanded=False):
        st.caption("Muse Voice Transcribe turns a voice note into text; Muse Spark reads the message and screenshot and drafts the metric definition for you to confirm.")
        if not key_ready:
            st.info("Live intake needs MODEL_API_KEY. A sample voice note and screenshot are in examples/.")
            return
        col_a, col_b = st.columns(2)
        audio = None
        with col_a:
            if hasattr(st, "audio_input"):
                recorded = st.audio_input("Record a voice note", key="voice")
                audio = recorded.getvalue() if recorded else None
            uploaded = st.file_uploader("…or upload a WAV voice note", type=["wav"], key="voice_upload")
            if uploaded:
                audio = uploaded.getvalue()
            claims = scenario_key.startswith("synpuf")
            if st.checkbox("Use the sample voice note from " + ("actuarial" if claims else "finance"), key="sample_voice"):
                audio = (EXAMPLES / ("claims_voice_note.wav" if claims else "voice_note.wav")).read_bytes()
                st.audio(audio, format="audio/wav")
        with col_b:
            shot = st.file_uploader("Dashboard screenshot", type=["png", "jpg", "jpeg"], key="shot")
            image, image_type = (shot.getvalue(), shot.type) if shot else (None, "image/png")
            if st.checkbox("Use the sample dashboard screenshot", key="sample_shot"):
                shot_name = "claims_dashboard_screenshot.png" if scenario_key.startswith("synpuf") else "dashboard_screenshot.png"
                image, image_type = (EXAMPLES / shot_name).read_bytes(), "image/png"
            if image:
                st.image(image, width="stretch")
        message = st.text_area("Message (optional)", key="intake_message", height=80,
                               placeholder="e.g. Paid November revenue jumped 68% after this morning's refresh. Is it real?")
        if st.button("Draft the investigation with Meta", key="draft"):
            ok, why = _budget_ok("intake")
            if not ok:
                st.warning(why)
                return
            try:
                from .intake import draft_contract
                client = MetaClient()
                with st.spinner("Transcribing and reading with Meta models…"):
                    transcript = client.transcribe(audio) if audio else ""
                    draft = draft_contract(text="\n".join(x for x in [transcript, message] if x), image_bytes=image,
                                           image_type=image_type, client=client)
                _record_use("intake")
                st.session_state["intake"] = {"scenario": scenario_key, "transcript": transcript, "draft": draft}
            except MetaAPIError as exc:
                st.error(str(exc))
        saved = st.session_state.get("intake")
        if saved and saved["scenario"] == scenario_key:
            if saved["transcript"]:
                st.markdown(f"**🎙️ Transcript · muse-voice-transcribe-1.0**\n\n> {saved['transcript']}")
            draft = saved["draft"]
            st.markdown("**🧠 Draft from muse-spark-1.3**")
            st.json({k: v for k, v in draft.items() if k not in {"usage", "model"}}, expanded=True)
            if st.button("Use this description and definition", key="apply_draft"):
                st.session_state.setdefault("overrides", {})[scenario_key] = {"description": draft["description"], "draft": draft}
                st.rerun()


# ---------------------------------------------------------------- live event rendering

def _event(container, event):
    kind = event["type"]
    stamp = f"`{event.get('t', 0):5.1f}s`"
    with container:
        if kind == "start":
            st.markdown(f"{stamp} 🧭 **Replayed both SQL versions on both snapshots** · agent `{event.get('model')}` · raw rows stay local")
            replay = pd.DataFrame(event.get("replay", []))
            if not replay.empty:
                replay["amount_usd"] = replay["revenue_cents"].map(lambda c: f"${c / 100:,.2f}")
                st.dataframe(replay[["sql_version", "snapshot", "amount_usd", "row_count", "evidence_id"]],
                             hide_index=True, width="stretch")
        elif kind == "thinking":
            st.caption(f"💭 {_md(event['text'][:400])}")
        elif kind == "tool_call":
            tool = event.get("tool")
            if tool == "query_snapshot":
                st.markdown(f"{stamp} 🔍 **Hypothesis:** {_md(event.get('purpose')) or 'diagnostic query'} · *{event.get('snapshot')} snapshot*")
                if event.get("sql"):
                    st.code(event["sql"], language="sql")
            elif tool == "verify_correction":
                st.markdown(f"{stamp} 🧪 **Testing a correction:** {_md(event.get('purpose'))}")
                if event.get("sql"):
                    st.code(event["sql"], language="sql")
            elif tool == "request_clarification":
                st.markdown(f"{stamp} ❓ **Asking the analyst** instead of guessing")
            else:
                st.markdown(f"{stamp} ⛔ Unknown tool requested: `{tool}` (refused)")
        elif kind == "tool_result":
            result = event.get("result") or {}
            if "error" in result:
                st.markdown(f"↳ ⚠️ rejected: {_md(result['error'])}")
            elif "verified" in result:
                (st.success if result["verified"] else st.warning)(f"↳ {result.get('evidence_id', '')} · {result.get('reason', '')}")
            elif "rows" in result:
                truncated = " (truncated)" if result.get("truncated") else ""
                st.markdown(f"↳ **{result.get('evidence_id')}** · {result.get('total_row_count', len(result['rows']))} row(s){truncated}")
                if result["rows"]:
                    st.dataframe(pd.DataFrame(result["rows"], columns=result["columns"]), hide_index=True, width="stretch")
        elif kind == "diagnosis":
            label = LABELS.get(event["classification"], (event["classification"], "#475467"))[0]
            st.markdown(f"{stamp} 🧾 **Agent diagnosis: {label}**. {_md(event.get('root_cause'))}")
        elif kind == "verified":
            (st.success if event["verified"] else st.warning)(f"{stamp} Independent per-order check: {event['reason']}")
        elif kind == "review_start":
            st.markdown(f"{stamp} 🛡️ **Independent review by `{event.get('model')}`**: a second Meta model checks the diagnosis against the evidence…")
        elif kind == "review":
            if event["verdict"] == "supported":
                st.success(f"{stamp} Reviewer verdict: supported")
            else:
                st.warning(f"{stamp} Reviewer challenged the diagnosis: " + _md("; ".join(event.get("concerns", []))))
        elif kind == "revision":
            st.markdown(f"{stamp} ↩️ **Agent is revising** to address the reviewer's concerns")
        elif kind == "clarification":
            st.info(f"{stamp} ❓ {_md(event['question'])}")
        elif kind == "clarified":
            st.markdown(f"{stamp} ✅ **Analyst answered:** {event['answer']} · investigation resumes")


def _render_timeline(events):
    container = st.container()
    for event in events:
        _event(container, event)


# ---------------------------------------------------------------- results

def _usd(cents):
    return f"${cents / 100:,.2f}"


def _revenue_bridge(previous_cents, current_cents, reconciliation, money_label="Revenue (USD)"):
    steps = [("Prior reported", 0, previous_cents, "Reported total")]
    prior_expected = reconciliation["previous_expected_cents"]
    current_expected = reconciliation["current_expected_cents"]
    if previous_cents != prior_expected:
        steps.append(("Prior correction", previous_cents, prior_expected, "Reporting error"))
    steps.extend([
        ("Real change", prior_expected, current_expected, "Genuine movement"),
        ("Reporting error", current_expected, current_cents, "Reporting error"),
        ("Current reported", 0, current_cents, "Reported total"),
    ])
    frame = pd.DataFrame(steps, columns=["Step", "Start", "End", "Type"])
    frame = frame.assign(Start=frame["Start"] / 100, End=frame["End"] / 100)
    frame["Amount"] = frame["End"] - frame["Start"]
    frame["Label"] = frame["Amount"].map(lambda amount: f"${amount:,.0f}")
    axis = alt.X("Step:N", sort=frame["Step"].tolist(), title=None, axis=alt.Axis(labelAngle=0, labelLimit=140))
    base = alt.Chart(frame).encode(x=axis)
    bars = base.mark_bar(size=58, cornerRadius=3).encode(
        y=alt.Y("Start:Q", title=money_label, axis=alt.Axis(format="$,.0f")), y2="End:Q",
        color=alt.Color("Type:N", scale=alt.Scale(domain=["Reported total", "Genuine movement", "Reporting error"],
                                                  range=["#3656ae", "#0f8179", "#c05e29"]),
                        legend=alt.Legend(title=None, orient="bottom")),
        tooltip=["Step:N", alt.Tooltip("Amount:Q", format="$,.2f")])
    labels = base.mark_text(dy=-10, fontWeight="bold", color="#17264a").encode(y="End:Q", text="Label:N")
    st.altair_chart((bars + labels).properties(height=260), width="stretch")


def _verdict_card(report):
    label, color = LABELS.get(report["classification"], (report["classification"], "#475467"))
    reconciliation = report.get("reconciliation")
    replay = report["replay"]
    headline = ""
    if reconciliation and replay:
        moved = replay[3]["revenue_cents"] - replay[0]["revenue_cents"]
        headline = (f"Reported {get_domain(report.get('domain')).metric_noun} moved <b>{_usd(moved)}</b>: <b>{_usd(reconciliation['underlying_change_cents'])}</b> is real, "
                    f"<b>{_usd(reconciliation['current_error_cents'])}</b> is a reporting error.")
    review = report.get("review")
    review_html = ""
    if review:
        text = f"🛡️ Independently reviewed by {_html(review['model'])}: {_html(review['verdict'])}"
        if len(report.get("review_history") or []) > 1:
            text += " · agent revised once after a challenge"
        review_html = f"<div class='trace-pill'>{text}</div>"
    if report.get("clarified"):
        review_html += "<div class='trace-pill'>🙋 Resumed after the analyst's answer</div>"
    cost = list_price_usd(report)
    if cost and report["mode"] == "meta_live":
        review_html += f"<div class='trace-pill'>⏱ {report.get('elapsed_seconds', 0):.0f}s · ≈${cost:.2f} · {report['usage'].get('tool_calls', 0)} queries</div>"
    source = {"meta_live": "Meta agent · " + _html(report.get("model")),
              "offline_scripted": "Deterministic checks (no AI)"}.get(report["mode"], report["mode"])
    st.markdown(f"""<div class="verdict" style="border-left:6px solid {color}">
      <div class="verdict-kicker">VERDICT · {source}</div>
      <div class="verdict-title" style="color:{color}">{label}</div>
      <div class="verdict-line">{headline}</div>
      {review_html}</div>""", unsafe_allow_html=True)


def _result(case, report, context_key):
    dom = get_domain(report.get("domain") or case.domain)
    replay = report["replay"]
    previous_cents, current_cents = replay[0]["revenue_cents"], replay[3]["revenue_cents"]
    reconciliation = report.get("reconciliation")
    if report.get("fallback_reason"):
        st.warning("The live Meta agent could not finish (" + report["fallback_reason"][:200] +
                   "). Showing the deterministic contract checks instead; no AI diagnosis is included.")
    _verdict_card(report)
    if report["mode"] == "offline_scripted":
        st.info("**Verifier only.** This deterministic check can tell you *that* the number breaks the metric contract and "
                "by how much. It cannot tell you *why* (which join, which customers or members, which filter), cannot "
                "repair your SQL while keeping its intent, and cannot ask you about a missing definition. Switch to the "
                "**Meta agent** for the investigation; this verifier is the referee that checks the agent's fix.")
    validation = report.get("validation") or {}
    a, b, c, d = st.columns(4)
    a.metric("Reported change", f"{(current_cents - previous_cents) / 100:+,.0f} USD")
    if reconciliation is None:
        b.metric("Real change", "Needs definition")
        c.metric("Reporting error", "Needs definition")
    else:
        b.metric("Real change", f"{reconciliation['underlying_change_cents'] / 100:+,.0f} USD")
        c.metric("Reporting error", f"{reconciliation['current_error_cents'] / 100:+,.0f} USD")
    if validation.get("verified") and report.get("correction_sql"):
        d.metric(f"Verified corrected {dom.metric_noun}", f"${validation['actual_revenue_cents'] / 100:,.0f}")
    elif reconciliation and reconciliation["current_error_cents"] == 0 and not reconciliation["affected_order_count"]:
        d.metric("Reported number", "Correct ✓")
    else:
        d.metric(f"Corrected {dom.metric_noun}", "Not verified")
    review = report.get("review") or {}
    if review.get("verdict") == "challenged":
        open_items = [c for c in review.get("concerns", []) if c.startswith("Blocking")] or review.get("concerns", [])
        st.warning("**The independent reviewer still has an open concern** after the agent's revision. "
                   "Treat the explanation below as provisional; the dollar reconciliation and fix check are deterministic.\n\n"
                   + "\n".join(f"- {_md(c)}" for c in open_items[:3]))
    brief = review.get("stakeholder_brief")
    if brief:
        st.markdown(f"<div class='brief'><b>📨 Brief for leadership</b> · drafted by the reviewer<br>{_html(brief)}</div>", unsafe_allow_html=True)
    tabs = st.tabs(["Finding", "Agent timeline", f"Affected {dom.items}", "Execution evidence", "Verify a correction", "Export"])
    with tabs[0]:
        if reconciliation is None:
            st.info("Refund treatment is undefined, so no number can be called right or wrong yet.")
        else:
            _revenue_bridge(previous_cents, current_cents, reconciliation, dom.money_label)
            st.caption(f"Real change applies the same {dom.item}-level contract to both snapshots. Reporting error compares the query with that contract.")
        if report.get("root_cause"):
            st.markdown(f"**Root cause:** {_md(report['root_cause'])}")
        st.markdown(_md(report["summary"]))
        for issue in report.get("consistency_issues", []):
            st.warning(issue)
        if validation:
            (st.success if validation.get("verified") else st.warning)(validation.get("reason", ""))
        if report.get("correction_sql"):
            st.markdown("**Verified correction**" if validation.get("verified") else "**Candidate correction**")
            st.code(report["correction_sql"], language="sql")
        st.caption(report["diagnosis_source"] + " · " + report["limitations"])
    with tabs[1]:
        if report.get("events"):
            usage = report.get("usage", {})
            cost = list_price_usd(report)
            st.caption(f"{usage.get('model_requests', 0)} agent requests · {usage.get('tool_calls', 0)} tool calls · "
                       f"{usage.get('input_tokens', 0) + usage.get('output_tokens', 0):,} tokens · {report.get('elapsed_seconds', 0):.0f}s"
                       + (f" · ≈${cost:.2f} at Meta list prices" if cost else ""))
            _render_timeline(report["events"])
        else:
            st.info("Offline mode runs fixed checks. Switch to the Meta agent to see an AI investigation timeline.")
    with tabs[2]:
        if reconciliation and reconciliation["affected_orders"]:
            count = reconciliation["affected_order_count"]
            st.subheader(f"Affected {dom.items} ({count:,})")
            st.caption(f"Reported rows from {reconciliation['current_evidence_id']} compared with the order-level contract.")
            orders = pd.DataFrame(reconciliation["affected_orders"])
            for column in ["reported_cents", "expected_cents", "difference_cents"]:
                orders[column] = orders[column].map(lambda value: f"${value / 100:,.2f}")
            st.dataframe(orders.rename(columns={"order_id": dom.item.title(), "reported_cents": "Reported USD",
                "expected_cents": "Expected USD", "difference_cents": "Difference USD",
                "reported_rows": "Reported rows", "expected_rows": "Expected rows"}),
                width="stretch", hide_index=True)
            if count > len(orders):
                st.caption("Showing the 100 largest differences by absolute value.")
        else:
            st.info("No order differs from the metric contract." if reconciliation else "Define refund treatment first.")
    with tabs[3]:
        st.subheader("Four-way SQL and snapshot replay")
        st.dataframe(replay, width="stretch", hide_index=True)
        for item in report["evidence"]:
            with st.expander(f"{item['evidence_id']} · {item['snapshot']} snapshot · {item.get('total_row_count', len(item['rows']))} result rows"):
                st.code(item["sql"], language="sql")
                st.dataframe(pd.DataFrame(item["rows"], columns=item["columns"]), width="stretch", hide_index=True)
                if item["truncated"]:
                    st.caption("Displayed rows are capped; replay totals and validation use complete results.")
    with tabs[4]:
        candidate = st.text_area("Candidate SQL to verify", report.get("correction_sql") or case.current_sql,
                                 height=160, key=f"candidate-{context_key}", max_chars=10000)
        st.caption("Checks the complete current-snapshot order/value multiset against the contract. Local only; never contacts Meta.")
        if st.button("Verify candidate SQL"):
            session = Investigation(case)
            try:
                checked = session.verify(candidate)
            finally:
                session.close()
            (st.success if checked["verified"] else st.warning)(checked["reason"])
            st.json(checked, expanded=False)
    with tabs[5]:
        public = {k: v for k, v in report.items() if k != "resume_state"}
        st.json({"generated_at": report["generated_at"], "input_sha256": report["input_sha256"],
                 "elapsed_seconds": report.get("elapsed_seconds"), "usage": report["usage"]}, expanded=False)
        left, right = st.columns(2)
        left.download_button("Download JSON evidence", json.dumps(public, indent=2), file_name="datatrace-report.json", mime="application/json")
        right.download_button("Download readable report", markdown_report(report), file_name="datatrace-report.md", mime="text/markdown")


def _clarify_prompt(report):
    dom = get_domain(report.get("domain"))
    question = (report.get("clarification") or {}).get("question") or \
        f"Treatment of {dom.reversal_noun} is not defined. Should they net against {dom.metric_noun}?"
    st.markdown(f"""<div class="verdict" style="border-left:6px solid #475467">
      <div class="verdict-kicker">THE AGENT PAUSED TO ASK YOU</div>
      <div class="verdict-title" style="color:#344054;font-size:1.15rem">❓ {_html(question)}</div></div>""", unsafe_allow_html=True)
    left, right, _ = st.columns([1, 1, 2])
    exclude_label, include_label = (("Exclude refunds (gross sales)", "Include refunds (net revenue)") if dom.name == "revenue"
                                    else ("Exclude reversals (gross paid)", "Include reversals (net paid)"))
    if left.button(exclude_label, type="primary", key="answer-exclude"):
        st.session_state["pending_answer"] = "exclude"
        st.rerun()
    if right.button(include_label, key="answer-include"):
        st.session_state["pending_answer"] = "include"
        st.rerun()
    if report.get("events"):
        with st.expander("Agent timeline so far", expanded=True):
            _render_timeline(report["events"])


# ---------------------------------------------------------------- recorded runs

def _recorded_path(choice):
    return RECORDED / f"{choice[0]}-{choice[1]}.json"


def _play(events, container, speed=5.0):
    last = None
    for event in events:
        if last is not None:
            time.sleep(min(1.0, max(0.0, (event.get("t", last) - last) / speed)))
        last = event.get("t", last or 0)
        _event(container, event)


# ---------------------------------------------------------------- benchmark and explainer tabs

def _benchmark_tab():
    path = RESULTS / "benchmark.json"
    if not path.exists():
        st.info("Benchmark results have not been generated yet. Run `python scripts/summarize_benchmark.py` after an evaluation.")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    st.subheader("Does giving the Meta model tools, a verifier and a reviewer actually help?")
    st.markdown(data.get("headline", ""))
    chart_rows = pd.DataFrame(data.get("chart", []))
    if not chart_rows.empty:
        chart_rows["Label"] = chart_rows["Correct"].map(lambda v: f"{v:.0%}" if v > 0 else "0% · could not run")
        base = alt.Chart(chart_rows).encode(
            x=alt.X("System:N", title=None, axis=alt.Axis(labelAngle=0, labelLimit=200)),
            y=alt.Y("Correct:Q", title="Correct diagnoses", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1.1])))
        bars = base.mark_bar(cornerRadius=3).encode(
            color=alt.Color("System:N", scale=alt.Scale(range=["#214ed3", "#98a2b3"]), legend=None),
            tooltip=["Split", "System", alt.Tooltip("Correct:Q", format=".0%")])
        text = base.mark_text(dy=-8, fontWeight="bold", color="#17264a").encode(text="Label:N")
        chart = alt.layer(bars, text, data=chart_rows).properties(width=200, height=230).facet(
            column=alt.Column("Split:N", title=None, sort=list(dict.fromkeys(chart_rows["Split"])),
                              header=alt.Header(labelFontSize=13)))
        st.altair_chart(chart)
    st.dataframe(pd.DataFrame(data["table"]), hide_index=True, width="stretch")
    st.caption(data.get("method", ""))
    reviewer_path = RESULTS / "reviewer_eval.json"
    if reviewer_path.exists():
        rev = json.loads(reviewer_path.read_text(encoding="utf-8"))
        st.subheader("Is the reviewer more than decoration?")
        st.markdown(f"We planted one known error into each of {rev['planted_total']} otherwise-correct diagnoses "
                    f"(inflated dollar amounts, an invented cause, a flipped classification, an unverified fix). "
                    f"**{rev['model']} challenged {rev['planted_caught']}/{rev['planted_total']}** and passed "
                    f"**{rev['controls_passed']}/{rev['controls_total']}** unmodified diagnoses; the one it flagged had a real "
                    f"double-count in the agent's explanation.")
        st.dataframe(pd.DataFrame([{"Planted error": k.replace("_", " "), "Cases": v["n"], "Challenged": v["challenged"]}
                                   for k, v in rev["summary"].items()]), hide_index=True, width="stretch")
        st.caption(rev.get("method", ""))


def _how_tab():
    st.subheader("How DataTrace works")
    st.graphviz_chart("""digraph G { rankdir=LR; bgcolor="transparent";
      node [shape=box style="rounded,filled" fillcolor="#eef2ff" color="#3656ae" fontname="Helvetica" fontsize=11];
      voice [label="Voice note\\nmuse-voice-transcribe-1.0"]; shot [label="Dashboard screenshot\\n+ message"];
      intake [label="Intake\\nmuse-spark-1.3 (vision)\\ndrafts metric contract"];
      agent [label="Investigator agent\\nmuse-spark-1.3\\nhypothesis → query → revise" fillcolor="#dbe4ff"];
      sql [label="Sandboxed SQLite\\nread-only, bounded\\nraw rows stay local" fillcolor="#e6f4f1" color="#0f8179"];
      ver [label="Independent verifier\\nper-order contract check\\n(Python, no AI)" fillcolor="#e6f4f1" color="#0f8179"];
      analyst [label="Analyst\\nanswers clarifying\\nquestions" fillcolor="#fff4e5" color="#c05e29"];
      rev [label="Reviewer\\nmuse-wonder-1.0\\nchallenges the diagnosis"];
      out [label="Verdict, revenue bridge,\\nverified SQL fix, CFO brief"];
      voice -> intake; shot -> intake; intake -> agent; agent -> sql [label="query_snapshot"]; sql -> agent;
      agent -> ver [label="verify_correction"]; ver -> agent; agent -> analyst [label="request_clarification"]; analyst -> agent;
      agent -> rev; rev -> agent [label="challenge → revise"]; rev -> out; }""")
    st.markdown("""
**What each layer adds**

| | Verifier only (no AI) | Same model, raw rows, no tools | **DataTrace agent** |
| --- | --- | --- | --- |
| Detects that the number is wrong | ✓ | ✓ | ✓ |
| Names the root cause | ✗ | ✓ when data fits | ✓ |
| Correct dollar split, 4k-order retail incidents | n/a | 12/24 | **24/24** |
| Correct dollar split, CMS claims incidents | n/a | 4/16 | **16/16** |
| Works at 42k orders | ✓ | ✗ (context exceeded) | ✓ 10/10 |
| Raw rows sent to the model | none | all | **none** |
| Asks when the definition is missing | ✗ | ✗ | ✓ |
| Fix verified order by order | ✓ (its own) | after the fact | ✓ before reporting |
| Cost per realistic case | $0 | $0.264 | $0.061 |

**Four Meta model roles**

| Model | Role in DataTrace |
| --- | --- |
| `muse-spark-1.3` | Investigator agent: plans hypotheses, writes diagnostic SQL, calls tools in parallel, revises from evidence, asks for clarification, proposes a fix |
| `muse-wonder-1.0` | Independent reviewer: sees only executed evidence and checks, challenges unsupported claims, drafts the stakeholder brief |
| `muse-spark-1.3` (vision) | Intake: reads a dashboard screenshot and message and drafts the metric contract |
| `muse-voice-transcribe-1.0` | Turns a stakeholder's voice note into the incident description |

**Trust boundaries**

- The agent never sees raw snapshot rows, only the schema, row counts, and results of its own bounded queries.
- SQL runs in an in-memory SQLite sandbox: read-only, table and function allowlists, VM-step and time limits, capped rows.
- A fix is accepted only when a deterministic Python check finds the **complete per-order multiset** matches the metric contract. A model cannot self-certify.
- Evidence IDs cited by the model must exist; fabricated IDs are rejected.
- A missing definition pauses the agent for a human answer instead of a guess.
- The API key comes from `.env` or Streamlit secrets, is sent only to `https://api.meta.ai/v1` with redirects blocked, and is never displayed or logged. Public demo mode caps live runs per visitor and per day.
""")


# ---------------------------------------------------------------- main

CSS = """<style>
.stApp {background:#f5f7fb;color:#18243a}
.block-container {padding-top:2rem;max-width:1180px}
.trace-hero {padding:1.6rem 2rem;border-radius:20px;margin-bottom:1rem;background:linear-gradient(120deg,#0b1736,#233c79 70%,#2f5bd3);color:#fff}
.trace-hero .trace-brand {font-size:.76rem;font-weight:750;letter-spacing:.16em;color:#b6d3ff}
.trace-hero h1 {color:#fff!important;margin:.35rem 0;font-size:clamp(1.5rem,4vw,2.6rem);line-height:1.12}
.trace-hero p {color:#e1ebfc;margin:.5rem 0 0;max-width:72ch}
.trace-hero .models {margin-top:.8rem;font-size:.8rem;color:#c9dbff}
.trace-hero code {background:rgba(255,255,255,.12);color:#fff;border-radius:6px;padding:1px 6px}
h2,h3 {color:#14213b!important}
div[data-testid="stMetric"] {background:white;padding:14px;border:1px solid #dfe6f4;border-radius:12px}
div[data-testid="stMetricValue"] {font-size:clamp(1.05rem,2.3vw,1.6rem)}
.verdict {background:white;border:1px solid #dfe6f4;border-radius:14px;padding:1rem 1.25rem;margin:.6rem 0 1rem}
.verdict-kicker {font-size:.72rem;font-weight:700;letter-spacing:.12em;color:#667085}
.verdict-title {font-size:1.55rem;font-weight:750;margin:.15rem 0}
.verdict-line {font-size:1.02rem;color:#253858}
.trace-pill {display:inline-block;margin:.5rem .4rem 0 0;background:#eef4ff;color:#2948a6;border-radius:999px;padding:3px 12px;font-size:.82rem;font-weight:600}
.brief {background:#fffaf0;border:1px solid #f5d9a8;border-radius:12px;padding:.8rem 1rem;margin:.6rem 0 1rem;color:#4a3410}
</style>"""


def _deep_link():
    """Read ?incident=<name>&mode=recorded|offline|live&autorun=1&fast=1 from the URL.

    Autorun only ever applies to recorded and offline modes, so a link can never spend API credits.
    """
    try:
        params = st.query_params
        names = [choice[1] for _, choice in SCENARIO_CHOICES]
        incident = params.get("incident")
        mode = {"recorded": RECORDED_MODE, "offline": OFFLINE, "live": LIVE}.get(params.get("mode", ""))
        return {"incident_index": names.index(incident) if incident in names else None, "mode": mode,
                "autorun": params.get("autorun") == "1" and mode in {RECORDED_MODE, OFFLINE},
                "fast": params.get("fast") == "1"}
    except Exception:
        return {"incident_index": None, "mode": None, "autorun": False, "fast": False}


def _context_key(case, mode, scenario_key):
    # Recorded runs are tied to the bundled incident, not to local edits.
    return f"{scenario_key}:{mode}" if mode == RECORDED_MODE else fingerprint(case) + ":" + mode


def main():
    st.set_page_config(page_title="DataTrace | Metric investigator", page_icon="🔎", layout="wide")
    _load_secrets()
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("""<div class="trace-hero">
    <div class="trace-brand">DATATRACE · AN AGENT THAT EXPLAINS WHY A METRIC MOVED</div>
    <h1>Is the jump real, or is the dashboard wrong?</h1>
    <p>DataTrace's Meta agent investigates a metric change with executed SQL evidence, separates genuine business movement
    from reporting errors down to the order, and reports a fix only after an independent check verifies it.</p>
    <div class="models">Powered by <code>muse-spark-1.3</code> agent · <code>muse-wonder-1.0</code> reviewer · <code>muse-voice-transcribe-1.0</code> intake</div>
    </div>""", unsafe_allow_html=True)
    key_ready = bool(os.environ.get("MODEL_API_KEY", "").strip()) or (
        os.environ.get("DATATRACE_PROVIDER", "").lower() == "openweight" and bool(os.environ.get("OPENWEIGHT_API_KEY", "").strip()))
    public = _public_demo()
    with st.sidebar:
        st.header("Investigation setup")
        link = _deep_link()
        scenario = st.selectbox("Incident", [label for label, _ in SCENARIO_CHOICES],
                                index=link["incident_index"] or 0)
        choice = dict(SCENARIO_CHOICES)[scenario]
        modes = [LIVE, RECORDED_MODE, OFFLINE]
        mode = st.radio("Investigation mode", modes,
                        index=modes.index(link["mode"]) if link["mode"] else (0 if key_ready else 1),
                        help="Recorded runs replay real Meta agent runs captured from this app, at no cost.")
        source = st.radio("Input source", ["Bundled example", "Incident JSON", "Four CSV snapshots"],
                          disabled=mode == RECORDED_MODE)
        if mode == RECORDED_MODE:
            source = "Bundled example"
            st.caption("Recorded runs replay a real captured Meta run of the bundled incident; edits to SQL or the definition apply to live and offline modes.")
        with st.expander("Agent settings"):
            review = st.toggle("Independent reviewer (muse-wonder-1.0)", value=True)
            effort = st.select_slider("Agent reasoning effort", ["low", "medium", "high"], value="medium")
        if mode == LIVE:
            provider = os.environ.get("DATATRACE_PROVIDER", "meta").lower()
            if provider == "openweight":
                st.success(f"Open-weight agent: {os.environ.get('OPENWEIGHT_MODEL', '?')} (key never displayed).")
            elif key_ready:
                st.success("Meta key configured (never displayed).")
            else:
                st.info("Add MODEL_API_KEY to .env for live mode.")
            if public:
                st.caption("Public demo: live runs are capped per visitor and per day to protect API credits.")
        consent = True
        if mode == LIVE and source != "Bundled example":
            consent = st.checkbox("Allow query results from this data to be sent to Meta for this run", value=False)
            if public:
                st.warning("On the public demo, uploaded data runs in offline mode only.")
        st.caption("SQL runs locally in memory; no production connection. Raw rows are never sent to the agent.")
    scenario_key = "-".join(choice)
    case = _base_case(choice)
    override = st.session_state.get("overrides", {}).get(scenario_key)
    if override:
        from .intake import apply_draft
        case = replace(case, description=override["description"][:4000],
                       contract=apply_draft(case.contract, override["draft"]))
    answered = st.session_state.get("refund_answers", {}).get(scenario_key)
    if answered and case.contract["refund_policy"] is None:
        case = replace(case, contract={**case.contract, "refund_policy": answered})
    st.sidebar.download_button("Download this incident (JSON + CSVs)", _example_zip(case),
                               file_name="datatrace-input-template.zip", mime="application/zip")

    investigate_tab, bench_tab, how_tab = st.tabs(["🔎 Investigate", "📊 Agent vs. baseline benchmark", "⚙️ How it works"])
    with bench_tab:
        _benchmark_tab()
    with how_tab:
        _how_tab()
    with investigate_tab:
        if mode == LIVE and source == "Bundled example":
            _intake(key_ready, scenario_key)
        try:
            case = _inputs(case, source)
        except (InputError, TypeError, ValueError) as exc:
            st.error(str(exc))
            return
        if case is None:
            return
        context_key = _context_key(case, mode, scenario_key)

        answer = st.session_state.pop("pending_answer", None)
        saved = st.session_state.get("result")
        if answer and saved and saved[1].get("status") == "needs_clarification":
            paused = saved[1]
            st.session_state.setdefault("refund_answers", {})[scenario_key] = answer
            clarified = replace(case, contract={**case.contract, "refund_policy": answer})
            box = st.status("Resuming the investigation with your answer…", expanded=True)
            try:
                if mode == RECORDED_MODE:
                    recording = json.loads(_recorded_path(choice).read_text(encoding="utf-8"))
                    report = recording.get("resumed") or recording["report"]
                    _play(report.get("events", [])[len(paused.get("events", [])):], box)
                else:
                    ok, why = _budget_ok("investigation")
                    if not ok:
                        raise MetaAPIError(why)
                    client = make_agent_client()
                    client.effort = effort
                    report = investigate_meta(clarified, client=client, review=review, resume=paused["resume_state"],
                                              answer=answer, on_event=lambda e: _event(box, e))
                    _record_use("investigation")
                box.update(label="Investigation complete", state="complete", expanded=False)
                st.session_state["result"] = (_context_key(clarified, mode, scenario_key), report)
                st.rerun()
            except (MetaAPIError, QueryRejected, ValueError, OSError) as exc:
                box.update(label="Investigation stopped", state="error")
                st.error(str(exc))

        disabled = mode == LIVE and (not key_ready or not consent or (public and source != "Bundled example"))
        autorun = link["autorun"] and not st.session_state.get("autoran")
        if autorun:
            st.session_state["autoran"] = True
        if st.button("③ Investigate metric change", type="primary", disabled=disabled) or autorun:
            labels = {LIVE: "Muse Spark is investigating…", RECORDED_MODE: "Replaying a recorded Meta agent run…",
                      OFFLINE: "Running deterministic contract checks…"}
            box = st.status(labels[mode], expanded=mode != OFFLINE)
            try:
                if mode == LIVE:
                    ok, why = _budget_ok("investigation")
                    if not ok:
                        raise MetaAPIError(why)
                    client = make_agent_client()
                    client.effort = effort
                    report = investigate_meta(case, client=client, review=review, on_event=lambda e: _event(box, e))
                    _record_use("investigation")
                elif mode == RECORDED_MODE:
                    path = _recorded_path(choice)
                    if not path.exists():
                        raise ValueError("No recorded run for this incident yet. Choose the live agent or offline checks.")
                    recording = json.loads(path.read_text(encoding="utf-8"))
                    report = recording.get("paused") or recording["report"]
                    st.session_state.get("refund_answers", {}).pop(scenario_key, None)
                    _play(report.get("events", []), box, speed=1e9 if link["fast"] else 5.0)
                else:
                    report = offline_walkthrough(case)
                paused_now = report.get("status") == "needs_clarification"
                box.update(label="Paused: the agent has a question for you" if paused_now else "Investigation complete",
                           state="complete", expanded=False)
                st.session_state["result"] = (_context_key(case, mode, scenario_key), report)
                history = st.session_state.get("run_history", [])
                st.session_state["run_history"] = (history + [{k: v for k, v in copy.deepcopy(report).items()
                                                               if k != "resume_state"}])[-5:]
            except (MetaAPIError, QueryRejected, ValueError, OSError) as exc:
                box.update(label="Investigation stopped", state="error")
                st.session_state.pop("result", None)
                st.error(str(exc))
                if mode == LIVE and isinstance(exc, MetaAPIError):
                    # Never leave the analyst empty-handed: show the deterministic contract checks instead.
                    try:
                        fallback = offline_walkthrough(case)
                        fallback["fallback_reason"] = str(exc)
                        st.session_state["result"] = (_context_key(case, mode, scenario_key), fallback)
                    except (QueryRejected, ValueError):
                        pass
        saved = st.session_state.get("result")
        if saved and saved[0] == context_key:
            report = copy.deepcopy(saved[1])
            if report.get("status") == "needs_clarification":
                _clarify_prompt(report)
            else:
                _result(case, report, context_key)
        else:
            st.info("Pick an incident, optionally describe what you saw, then press **Investigate metric change**.")
        history = st.session_state.get("run_history", [])
        if history:
            st.sidebar.download_button("Download recent run history", json.dumps(history, indent=2),
                                       file_name="datatrace-history.json", mime="application/json")
    st.divider()
    st.caption("Built for the Meta Global AI Developer Hackathon 2026 · Synthetic data · Execution evidence before explanations")
