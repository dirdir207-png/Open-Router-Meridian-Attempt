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
    assert simplecrew.app.config["SESSION_COOKIE_SECURE"] is True


def test_development_launch_only_enables_debug_when_requested(monkeypatch, tmp_path):
    run_calls = []
    monkeypatch.setenv("DB_FILE", str(tmp_path / "simplecrew.db"))
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    monkeypatch.setattr(Flask, "run", lambda _app, **kwargs: run_calls.append(kwargs))

    runpy.run_path(Path(__file__).parents[1] / "app.py", run_name="__main__")

    assert run_calls == [{"host": "0.0.0.0", "debug": False, "port": 8080}]


def test_development_launch_enables_debug_only_with_explicit_opt_in(monkeypatch, tmp_path):
    run_calls = []
    monkeypatch.setenv("DB_FILE", str(tmp_path / "simplecrew.db"))
    monkeypatch.setenv("FLASK_DEBUG", "1")
    monkeypatch.setattr(Flask, "run", lambda _app, **kwargs: run_calls.append(kwargs))

    runpy.run_path(Path(__file__).parents[1] / "app.py", run_name="__main__")

    assert run_calls == [{"host": "0.0.0.0", "debug": True, "port": 8080}]


def test_session_cookie_is_not_secure_when_debug_is_explicitly_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_FILE", str(tmp_path / "simplecrew.db"))
    monkeypatch.setenv("FLASK_DEBUG", "1")

    debug_module = runpy.run_path(Path(__file__).parents[1] / "app.py", run_name="debug_app")

    assert debug_module["app"].config["SESSION_COOKIE_SECURE"] is False
