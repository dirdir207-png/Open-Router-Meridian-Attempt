import runpy
from pathlib import Path

import pytest
from flask import Flask

import app as app_module


@pytest.fixture
def simplecrew():
    return app_module


def test_production_debug_is_disabled(simplecrew):
    assert simplecrew.app.debug is False


def test_session_cookie_defaults(simplecrew):
    assert simplecrew.app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert simplecrew.app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_development_launch_only_enables_debug_when_requested(monkeypatch, tmp_path):
    run_calls = []
    monkeypatch.setenv("DB_FILE", str(tmp_path / "simplecrew.db"))
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    monkeypatch.setattr(Flask, "run", lambda _app, **kwargs: run_calls.append(kwargs))

    runpy.run_path(Path(__file__).parents[1] / "app.py", run_name="__main__")

    assert run_calls == [{"host": "0.0.0.0", "debug": False, "port": 8080}]
