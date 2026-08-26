import pytest
import requests

from crew.client import (
    CrewAPIError,
    CrewAuthenticationError,
    CrewClient,
    CrewTransportError,
    CrewUncertainWriteError,
)
from crew.credentials import StoredBearerTokenProvider


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.responses.pop(0)


def client(session, token="secret-token"):
    return CrewClient(
        StoredBearerTokenProvider(lambda: token),
        session=session,
        timeout_seconds=7,
    )


def test_execute_injects_bearer_header_and_timeout():
    session = FakeSession([FakeResponse(payload={"data": {"viewer": {"id": "1"}}})])
    result = client(session).execute("Viewer", "query Viewer { viewer { id } }")
    assert result == {"viewer": {"id": "1"}}
    _, kwargs = session.calls[0]
    assert kwargs["headers"]["authorization"] == "Bearer secret-token"
    assert kwargs["timeout"] == 7


def test_missing_token_raises_authentication_error_without_secret():
    session = FakeSession()
    with pytest.raises(CrewAuthenticationError) as exc:
        client(session, token=None).execute("Viewer", "query Viewer { viewer { id } }")
    assert "token" not in str(exc.value).lower() or "missing" in str(exc.value).lower()


@pytest.mark.parametrize("status", [401, 403])
def test_http_auth_failure_is_classified(status):
    session = FakeSession([FakeResponse(status_code=status, payload={})])
    with pytest.raises(CrewAuthenticationError):
        client(session).execute("Viewer", "query Viewer { viewer { id } }")


def test_graphql_auth_error_is_classified():
    session = FakeSession([FakeResponse(payload={"errors": [{"message": "Unauthorized"}]})])
    with pytest.raises(CrewAuthenticationError):
        client(session).execute("Viewer", "query Viewer { viewer { id } }")


def test_generic_graphql_error_is_classified():
    session = FakeSession([FakeResponse(payload={"errors": [{"message": "Validation failed"}]})])
    with pytest.raises(CrewAPIError):
        client(session).execute("Viewer", "query Viewer { viewer { id } }")


def test_read_timeout_is_transport_error():
    session = FakeSession(error=requests.Timeout("boom"))
    with pytest.raises(CrewTransportError):
        client(session).execute("Viewer", "query Viewer { viewer { id } }")


def test_mutation_timeout_is_uncertain_and_not_retried():
    session = FakeSession(error=requests.Timeout("boom"))
    with pytest.raises(CrewUncertainWriteError):
        client(session).execute(
            "InitiateTransferScottie",
            "mutation InitiateTransferScottie { __typename }",
            {"input": {"amount": 100}},
            is_mutation=True,
        )
    assert len(session.calls) == 1


def test_exception_text_never_contains_bearer_value():
    session = FakeSession([FakeResponse(status_code=401, payload={})])
    with pytest.raises(CrewAuthenticationError) as exc:
        client(session, token="do-not-leak-me").execute("Viewer", "query Viewer { viewer { id } }")
    assert "do-not-leak-me" not in str(exc.value)
