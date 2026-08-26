import app as simplecrew


def test_production_debug_is_disabled():
    assert simplecrew.app.debug is False


def test_session_cookie_defaults():
    assert simplecrew.app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert simplecrew.app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
