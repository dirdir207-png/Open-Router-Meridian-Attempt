import base64
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import quote

import pytest

if "app" not in sys.modules:
    os.environ["DB_FILE"] = os.path.join(
        tempfile.mkdtemp(prefix="meridian_api_test_"), "savings_data.db"
    )

import app as simplecrew
from meridian.repository import FinancialRepository


@pytest.fixture(autouse=True)
def disable_background_polling(monkeypatch):
    monkeypatch.setattr(simplecrew, "_background_thread_started", True)


@pytest.fixture
def api_client(monkeypatch, tmp_path):
    repository = FinancialRepository(str(tmp_path / "financial.db"))
    user_id = "meridian-api-user"
    monkeypatch.setattr(
        simplecrew.login_manager,
        "_user_callback",
        lambda value: simplecrew.User(value, "meridian-api-user", "meridian-api@example.com"),
    )

    monkeypatch.setitem(
        simplecrew.app.config,
        "MERIDIAN_REPOSITORY_FACTORY",
        lambda: repository,
    )
    client = simplecrew.app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
    return client, repository


@pytest.mark.parametrize(
    "path",
    [
        "/api/meridian/today",
        "/api/meridian/activity",
        "/api/meridian/transactions/1",
        "/api/meridian/accounts",
    ],
)
def test_meridian_read_apis_require_login(path):
    response = simplecrew.app.test_client().get(path)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login?next=" + quote(path, safe=""))


def test_meridian_read_apis_serialize_safe_data_and_stable_errors(api_client, monkeypatch):
    client, repository = api_client
    account = repository.upsert_account(
        provider="crew",
        external_id="account-number-123456789",
        name="Checking",
        account_type="checking",
        balance=125.0,
        available_balance=100.0,
        synced_at="2026-08-27T12:00:00Z",
    )
    first = repository.upsert_transaction(
        provider="crew",
        external_id="transaction-secret-111",
        account_id=account.id,
        amount=-12.5,
        occurred_at="2026-08-27T11:00:00Z",
        description="Coffee",
        raw_description="Bearer should-never-appear",
        status="posted",
        synced_at="2026-08-27T12:00:00Z",
    )
    repository.upsert_transaction(
        provider="crew",
        external_id="transaction-secret-222",
        account_id=account.id,
        amount=-20.0,
        occurred_at="2026-08-26T11:00:00Z",
        description="Lunch",
        status="posted",
        synced_at="2026-08-27T12:00:00Z",
    )
    monkeypatch.setenv("BEARER_TOKEN", "super-secret-sentinel-value")

    today = client.get("/api/meridian/today")
    accounts = client.get("/api/meridian/accounts")
    activity = client.get("/api/meridian/activity?limit=1")
    transaction = client.get(f"/api/meridian/transactions/{first.id}")
    missing = client.get("/api/meridian/transactions/99999")

    assert today.status_code == accounts.status_code == activity.status_code == 200
    assert transaction.status_code == 200
    assert activity.get_json()["next_cursor"]
    assert activity.get_json()["transactions"][0]["id"] == first.id
    for response in (today, accounts, activity, transaction):
        payload = response.get_json()
        assert "data_freshness" in payload
        body = response.get_data(as_text=True)
        assert "account-number-123456789" not in body
        assert "transaction-secret-111" not in body
        assert "should-never-appear" not in body
        assert "super-secret-sentinel-value" not in body

    assert missing.status_code == 404
    assert missing.get_json()["error"] == {
        "code": "transaction_not_found",
        "message": "The requested transaction is not available.",
        "recovery_action": "Return to Activity and choose another transaction.",
    }


def test_meridian_activity_rejects_invalid_pagination_with_a_stable_error(api_client):
    client, _ = api_client

    response = client.get("/api/meridian/activity?limit=not-a-number")

    assert response.status_code == 400
    assert response.get_json()["error"] == {
        "code": "invalid_request",
        "message": "limit must be an integer between 1 and 200.",
        "recovery_action": "Use a limit between 1 and 200 and try again.",
    }


def _cursor(payload):
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64",
        _cursor(["not-a-timestamp", 1]),
        _cursor([1, 1]),
        _cursor(["2026-08-27T08:00:00", 1]),
        _cursor(["2026-08-27T08:00:00Z", True]),
        _cursor(["2026-08-27T08:00:00Z", 0]),
        _cursor(["2026-08-27T08:00:00Z", 1, "extra"]),
        base64.urlsafe_b64encode(b'["2026-08-27T08:00:00Z", 1]').decode("ascii"),
    ],
)
def test_meridian_activity_rejects_malformed_or_noncanonical_cursors(api_client, cursor):
    client, _ = api_client

    response = client.get("/api/meridian/activity", query_string={"cursor": cursor})

    assert response.status_code == 400
    assert response.get_json()["error"] == {
        "code": "invalid_request",
        "message": "The activity cursor is invalid.",
        "recovery_action": "Restart from the first Activity page and try again.",
    }


@pytest.mark.parametrize("account_id", ["not-a-number", "0", "-1"])
def test_meridian_activity_names_an_invalid_account_filter(api_client, account_id):
    client, _ = api_client

    response = client.get("/api/meridian/activity", query_string={"account_id": account_id})

    assert response.status_code == 400
    assert response.get_json()["error"] == {
        "code": "invalid_request",
        "message": "account_id must be a positive integer.",
        "recovery_action": "Use a positive account_id and try again.",
    }


def test_meridian_missing_transaction_keeps_last_known_good_freshness(api_client):
    client, repository = api_client
    now = datetime.now(timezone.utc).isoformat()
    run = repository.begin_sync_run(
        provider="crew",
        connection_external_id="crew-household",
        connection_name="Crew",
    )
    repository.upsert_account(
        provider="crew",
        external_id="checking",
        name="Checking",
        account_type="checking",
        balance=100.0,
        connection_id=run.connection_id,
        source_updated_at=now,
    )
    repository.finish_sync_run(
        run.id,
        status="complete",
        accounts_synced=1,
        transactions_synced=0,
        errors=0,
    )

    response = client.get("/api/meridian/transactions/99999")

    assert response.status_code == 404
    assert response.get_json()["data_freshness"]["status"] == "fresh"


def test_meridian_api_hides_repository_failures_behind_a_stable_error(api_client, monkeypatch):
    client, _ = api_client

    class UnavailableRepository:
        @staticmethod
        def list_accounts():
            raise RuntimeError("Bearer should-never-appear")

    monkeypatch.setitem(
        simplecrew.app.config,
        "MERIDIAN_REPOSITORY_FACTORY",
        UnavailableRepository,
    )

    response = client.get("/api/meridian/accounts")

    assert response.status_code == 503
    assert response.get_json()["error"] == {
        "code": "financial_data_unavailable",
        "message": "Financial data is temporarily unavailable.",
        "recovery_action": "Try again after your provider reconnects.",
    }
    assert "should-never-appear" not in response.get_data(as_text=True)
