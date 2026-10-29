from streamlit.testing.v1 import AppTest


def test_offline_ui_displays_evidence_after_run():
    app = AppTest.from_file("app.py", default_timeout=20).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert any("Calculation Defect" in element.value for element in app.subheader)
    assert any("matches the metric contract" in element.value for element in app.success)
    assert len(app.metric) == 3


def test_switching_incident_hides_stale_results():
    app = AppTest.from_file("app.py", default_timeout=20).run()
    app.button[0].click().run()
    app.selectbox[0].select("Revenue incident 03").run()
    assert not app.metric
    app.button[0].click().run()
    assert not app.exception
    assert any("Insufficient Evidence" in element.value for element in app.subheader)
