import json

import pytest

from crew.advisor import (
    AdvisorService,
    AdvisorUnavailable,
    FinancialContextBuilder,
)


class FakeLLM:
    def __init__(self, reply="", error=None):
        self._reply = reply
        self._error = error
        self.calls = []

    def complete(self, system, messages):
        if self._error:
            raise self._error
        self.calls.append({"system": system, "messages": messages})
        return self._reply


@pytest.fixture
def context_builder():
    return FinancialContextBuilder(snapshot_fn=lambda: {
        "safe_to_spend": 1234.56,
        "checking": {"id": "acc-1", "name": "Checking", "balance": 1234.56},
        "pockets": [
            {"id": "pock-1", "name": "Rent", "balance": 400.0},
            {"id": "pock-2", "name": "Fun Money/Splurge/Travel", "balance": 75.25},
        ],
    })


def make_service(llm, store=None):
    import tempfile

    from crew.actions import ActionStore
    if store is None:
        store = ActionStore(db_path=tempfile.mktemp(suffix=".db"), allowed_types=("move_money",))
    def resolver(name):
        return {
            "checking": "acc-1",
            "rent": "pock-1",
            "fun money/splurge/travel": "pock-2",
        }.get((name or "").lower())
    service = AdvisorService(llm_client=llm, context_builder=context_builder_snapshot(), store=store, resolver=resolver)
    return service, store


def context_builder_snapshot():
    return FinancialContextBuilder(snapshot_fn=lambda: {
        "checking": {"id": "acc-1", "name": "Checking"},
        "pockets": [{"id": "pock-1", "name": "Rent"}, {"id": "pock-2", "name": "Fun Money/Splurge/Travel"}],
    })


def test_plain_question_returns_reply_without_proposal():
    service, _ = make_service(FakeLLM(reply="You could save by packing lunch."))
    result = service.chat("how do i save more?")
    assert result["reply"] == "You could save by packing lunch."
    assert result.get("proposal") is None


def test_llm_receives_context_and_history():
    llm = FakeLLM(reply="ok")
    service, _ = make_service(llm)
    service.chat("hello", history=[{"role": "user", "content": "hi"}])
    sent = llm.calls[0]
    assert '"Checking"' in sent["system"]
    assert sent["messages"][-1]["content"] == "hello"


def test_proposal_json_becomes_pending_action():
    llm = FakeLLM(reply=(
        "Happy to help! ```json\n"
        + json.dumps({
            "action": "move_money",
            "params": {"from_name": "Checking", "to_name": "Rent", "amount": 50, "memo": "top-up"},
            "summary": "Move $50.00 from Checking → Rent",
        })
        + "\n``` Anything else?"
    ))
    service, store = make_service(llm)
    result = service.chat("move 50 to rent")
    assert result["proposal"]["id"] == store.list_pending()[0]["id"]
    assert result["proposal"]["summary"].startswith("Move $50.00")
    assert result["reply"].startswith("Happy to help!")


def test_malformed_proposal_json_is_treated_as_text():
    llm = FakeLLM(reply="Sure ```json {not valid} ```")
    service, store = make_service(llm)
    result = service.chat("do a thing")
    assert result.get("proposal") is None
    assert store.list_pending() == []


def test_unknown_action_type_is_never_proposed():
    llm = FakeLLM(reply="```json " + json.dumps({"action": "delete_account", "params": {}}) + " ```")
    service, store = make_service(llm)
    result = service.chat("nuke it")
    assert result.get("proposal") is None
    assert store.list_pending() == []
    assert "valid proposal" in result["reply"].lower()


def test_unavailable_client_raises_normalized_error():
    import requests as _rq

    llm = FakeLLM(error=_rq.Timeout("boom"))
    service, _ = make_service(llm)
    with pytest.raises(AdvisorUnavailable):
        service.chat("hello")


def test_context_builder_shapes_display_safe_snapshot(context_builder):
    snapshot = context_builder.build()
    assert snapshot["accounts"][0]["name"] == "Checking"
    assert snapshot["safe_to_spend"] == 1234.56
    assert "token" not in json.dumps(snapshot).lower()
