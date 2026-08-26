import pytest
import requests

from crew.advisor import (
    AdvisorUnavailable,
    FailoverLLMClient,
    OpenAICompatClient,
    build_llm_chain,
)


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self._payload = payload or {}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code}")
            err.response = self
            raise err

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses_by_host=None, error_by_host=None):
        self.responses_by_host = responses_by_host or {}
        self.error_by_host = error_by_host or {}
        self.calls = []

    def post(self, url, **kwargs):
        host = url.split("/")[2]
        self.calls.append(host)
        if host in self.error_by_host:
            raise self.error_by_host[host]
        return self.responses_by_host[host]


def ok_response():
    return FakeResponse({"choices": [{"message": {"content": "hello"}}]})


def make_client(session, api_key="k", base_url="https://example.com/v1", model="m"):
    return OpenAICompatClient(api_key=api_key, base_url=base_url, model=model, session=session)


def test_openai_client_success_returns_content():
    session = FakeSession(responses_by_host={"example.com": ok_response()})
    client = make_client(session)
    assert client.complete("sys", [{"role": "user", "content": "hi"}]) == "hello"


@pytest.mark.parametrize("status", [401, 402, 429])
def test_credit_and_auth_failures_map_to_unavailable(status):
    session = FakeSession(responses_by_host={"example.com": FakeResponse(status=status)})
    client = make_client(session)
    with pytest.raises(AdvisorUnavailable):
        client.complete("s", [])


def test_failover_tries_second_provider_on_first_failure(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-primary")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-backup")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/stealth/ox-alpha")

    def fake_init(self, api_key=None, base_url=None, model=None, session=requests):
        self._api_key = api_key
        self._base_url = (base_url or "").rstrip("/")
        self._model = model or "m"
        self._session = None

    chain = FailoverLLMClient([
        ("openai", FailingClient()),
        ("openrouter", WorkingClient()),
    ])
    result = chain.complete("s", [{"role": "user", "content": "hi"}])
    assert result == "fallback-reply"
    assert chain.last_provider == "openrouter"


class FailingClient:
    def complete(self, system, messages):
        raise AdvisorUnavailable("primary down")


class WorkingClient:
    def __init__(self):
        self.called = False

    def complete(self, system, messages):
        self.called = True
        return "fallback-reply"


def test_failover_raises_when_all_providers_fail():
    chain = FailoverLLMClient([("openai", FailingClient()), ("openrouter", FailingClient())])
    with pytest.raises(AdvisorUnavailable):
        chain.complete("s", [])
    assert chain.last_provider is None


def test_build_chain_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-a")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    chain = build_llm_chain(session=FakeSession(responses_by_host={}))
    assert chain.providers() == ["openai"]

    monkeypatch.setenv("OPENROUTER_API_KEY", "or-b")
    chain = build_llm_chain(session=FakeSession(responses_by_host={}))
    assert chain.providers() == ["openai", "openrouter"]

    monkeypatch.delenv("OPENAI_API_KEY")
    chain = build_llm_chain(session=FakeSession(responses_by_host={}))
    assert chain.providers() == ["openrouter"]
