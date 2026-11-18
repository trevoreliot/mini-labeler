import importlib
from pathlib import Path

import pytest

from md_labeler import config


@pytest.fixture
def reload_config(monkeypatch):
    def load(**env):
        for name in ("MD_LABELER_CONTACT", "MD_LABELER_MUSIC_ROOT", "MD_LABELER_PRINTER"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return importlib.reload(config)

    yield load
    monkeypatch.undo()
    importlib.reload(config)  # leave the module as other tests expect it


def test_defaults(reload_config):
    c = reload_config()
    assert c.CONTACT == "https://github.com/trevoreliot"
    assert c.MUSIC_ROOT == Path("/mnt/ssd500/Media/Music")
    assert c.PRINTER is None
    assert c.USER_AGENT.endswith(f"( {c.CONTACT} )")


def test_environment_overrides(reload_config):
    c = reload_config(MD_LABELER_CONTACT="https://example.org/me", MD_LABELER_MUSIC_ROOT="~/Music", MD_LABELER_PRINTER="Office")
    assert c.CONTACT == "https://example.org/me" and "( https://example.org/me )" in c.USER_AGENT
    assert c.MUSIC_ROOT == Path.home() / "Music"
    assert c.PRINTER == "Office"


def test_empty_variables_mean_default(reload_config):
    c = reload_config(MD_LABELER_CONTACT="  ", MD_LABELER_MUSIC_ROOT="")
    assert c.CONTACT == "https://github.com/trevoreliot"
    assert c.MUSIC_ROOT == Path("/mnt/ssd500/Media/Music")
