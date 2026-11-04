from streamlit.testing.v1 import AppTest


def test_offline_ui_displays_evidence_after_run():
    app = AppTest.from_file("app.py", default_timeout=20).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert any("Mixed Change" in element.value for element in app.subheader)
    assert any("$1,300.00" in element.value for element in app.subheader)
    assert any("Affected orders (1)" in element.value for element in app.subheader)
    assert any("matches the metric contract" in element.value for element in app.success)
    assert len(app.metric) == 3


def test_switching_incident_hides_stale_results():
    app = AppTest.from_file("app.py", default_timeout=20).run()
    app.button[0].click().run()
    next(widget for widget in app.selectbox if widget.label == "Synthetic incident").select("Revenue incident 03").run()
    assert not app.metric
    app.button[0].click().run()
    assert not app.exception
    assert any("Insufficient Evidence" in element.value for element in app.subheader)


def test_editing_sql_hides_previous_report():
    app = AppTest.from_file("app.py", default_timeout=20).run()
    app.button[0].click().run()
    next(widget for widget in app.text_area if widget.label == "Current SQL").input("SELECT 1").run()
    assert not app.metric
    app.button[0].click().run()
    assert not app.exception
    assert app.error


def test_live_run_is_disabled_without_key(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    app = AppTest.from_file("app.py", default_timeout=20).run()
    next(widget for widget in app.radio if widget.label == "Investigation mode").set_value("Live Meta investigator").run()
    assert app.button[0].disabled


def test_manual_verification_rejects_equal_total_wrong_order():
    app = AppTest.from_file("app.py", default_timeout=20).run()
    app.button[0].click().run()
    next(widget for widget in app.text_area if widget.label == "Candidate SQL to verify").input(
        "SELECT 1 AS order_id, 130000 AS revenue_cents").run()
    next(widget for widget in app.button if widget.label == "Verify candidate SQL").click().run()
    assert not app.exception
    assert any("violates" in element.value for element in app.warning)
