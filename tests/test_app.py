from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_ui_runs_demo_and_renders_all_phases(scenario):
    root = scenario.parents[1]
    source = (
        Path(__file__).resolve().parents[1] / "src" / "market_intelligence" / "app.py"
    ).read_text(encoding="utf-8")
    source = source.replace(
        "ROOT = Path(__file__).resolve().parents[2]", f"ROOT = Path({str(root)!r})"
    )
    app = AppTest.from_string(source, default_timeout=30)
    app.run()
    assert not app.exception
    button = next(button for button in app.button if button.label == "Run pipeline")
    button.click().run()
    assert not app.exception
    assert any("DETERMINISTIC DEMO" in warning.value for warning in app.warning)
    assert any("Premium gym concept" in success.value for success in app.success)
    assert any(metric.label == "Evidence records" and metric.value == "16" for metric in app.metric)
