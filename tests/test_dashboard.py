"""Headless dashboard tests with Streamlit's AppTest (uses the local database if present)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tremor.config import load_config

APP = str(Path(__file__).resolve().parents[1] / "src" / "tremor" / "dashboard" / "app.py")


def test_locked_without_passcode(monkeypatch):
    monkeypatch.delenv("TREMOR_PASSCODE", raising=False)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert at.error and "locked" in at.error[0].value


def test_wrong_then_right_passcode(monkeypatch):
    monkeypatch.setenv("TREMOR_PASSCODE", "s3cret")
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input[0].input("nope").run()
    assert any("Wrong passcode" in e.value for e in at.error)
    at.text_input[0].input("s3cret").run()
    assert not at.exception
    assert at.session_state["unlocked"]


@pytest.mark.skipif(not load_config().storage_path.exists(), reason="needs local data")
def test_pages_render_with_real_data(monkeypatch):
    monkeypatch.setenv("TREMOR_PASSCODE", "s3cret")
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.text_input[0].input("s3cret").run()
    assert not at.exception, at.exception
    assert any("Event feed" in h.value for h in at.subheader)
    # switch Asset and Episode, then the Track record page
    at.radio(key="asset").set_value("BDRY").run()
    assert not at.exception, at.exception
    episodes = at.radio(key="episode")
    episodes.set_value(len(episodes.options) - 1).run()  # oldest Episode
    assert not at.exception, at.exception
    at.radio(key="page").set_value("Track record").run()
    assert not at.exception, at.exception
    assert any("Track record" in h.value for h in at.subheader)


def test_label_page_renders(monkeypatch):
    monkeypatch.setenv("TREMOR_PASSCODE", "s3cret")
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.text_input[0].input("s3cret").run()
    at.radio(key="page").set_value("Label (Eval set)").run()
    assert not at.exception, at.exception
    assert any("Label the Eval set" in h.value for h in at.subheader)
