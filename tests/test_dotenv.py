import os

from tremor.config import load_dotenv


def test_dotenv_loads_without_overriding(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nTREMOR_T1='abc'\nexport TREMOR_T2=xyz\nTREMOR_T3=keep\n")
    monkeypatch.delenv("TREMOR_T1", raising=False)
    monkeypatch.delenv("TREMOR_T2", raising=False)
    monkeypatch.setenv("TREMOR_T3", "real")
    load_dotenv(env)
    assert os.environ["TREMOR_T1"] == "abc" and os.environ["TREMOR_T2"] == "xyz"
    assert os.environ["TREMOR_T3"] == "real"
    monkeypatch.delenv("TREMOR_T1"); monkeypatch.delenv("TREMOR_T2")
