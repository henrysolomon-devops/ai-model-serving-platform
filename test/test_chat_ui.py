import os

import pytest
import requests
from prometheus_client import REGISTRY

os.environ["MODEL_API_URL"] = "http://model.test/v1/chat/completions"
os.environ["API_KEY"] = "test-key"

import app as chat_app  # noqa: E402


class FakeResponse:
    def __init__(self, payload=None, error=None):
        self._payload = payload or {}
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._payload


@pytest.fixture
def client():
    chat_app.app.testing = True
    return chat_app.app.test_client()


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_index_serves_the_chat_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"<textarea" in res.data


def test_chat_rejects_empty_messages(client):
    res = client.post("/chat", json={"messages": []})
    assert res.status_code == 400


def test_chat_forwards_the_request_and_returns_the_reply(client, monkeypatch):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, body=json)
        return FakeResponse({"choices": [{"message": {"content": "hi there"}}]})

    monkeypatch.setattr(chat_app.requests, "post", fake_post)
    messages = [{"role": "user", "content": "hello"}]
    res = client.post("/chat", json={"messages": messages})

    assert res.status_code == 200
    assert res.get_json() == {"reply": "hi there"}
    assert seen["url"] == "http://model.test/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    assert seen["body"]["messages"] == messages
    assert seen["body"]["model"] == "llama-3.2-3b-instruct"


@pytest.mark.parametrize("error", [requests.ConnectionError("down"), requests.Timeout("slow")])
def test_chat_returns_502_when_the_model_is_unreachable(client, monkeypatch, error):
    def fake_post(*args, **kwargs):
        raise error

    monkeypatch.setattr(chat_app.requests, "post", fake_post)
    res = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})

    assert res.status_code == 502
    assert "error" in res.get_json()


def test_chat_returns_502_when_the_model_rejects_the_request(client, monkeypatch):
    def fake_post(*args, **kwargs):
        return FakeResponse(error=requests.HTTPError("401"))

    monkeypatch.setattr(chat_app.requests, "post", fake_post)
    res = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})

    assert res.status_code == 502


# ---- metrics ----
# The registry is shared by every test in the process, so these tests
# compare numbers before and after a request instead of expecting zero.


def sample(name, labels=None):
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


def snapshot():
    return {
        "ok": sample("chat_requests_total", {"status": "200"}),
        "bad_request": sample("chat_requests_total", {"status": "400"}),
        "bad_gateway": sample("chat_requests_total", {"status": "502"}),
        "durations": sample("chat_request_duration_seconds_count"),
        "prompt_tokens": sample("chat_tokens_total", {"type": "prompt"}),
        "completion_tokens": sample("chat_tokens_total", {"type": "completion"}),
    }


def fake_model(monkeypatch, payload):
    monkeypatch.setattr(chat_app.requests, "post", lambda *a, **k: FakeResponse(payload))


def test_metrics_endpoint_exposes_the_chat_metrics(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    assert res.content_type.startswith("text/plain")
    for name in (
        b"chat_requests_total",
        b"chat_request_duration_seconds_bucket",
        b"chat_requests_in_flight",
        b"chat_tokens_total",
    ):
        assert name in res.data


def test_successful_chat_is_counted_timed_and_token_counted(client, monkeypatch):
    fake_model(monkeypatch, {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7},
    })
    before = snapshot()
    res = client.post("/chat", json={"messages": [{"role": "user", "content": "hello"}]})
    after = snapshot()

    assert res.status_code == 200
    assert after["ok"] == before["ok"] + 1
    assert after["durations"] == before["durations"] + 1
    assert after["prompt_tokens"] == before["prompt_tokens"] + 12
    assert after["completion_tokens"] == before["completion_tokens"] + 7


def test_a_reply_without_usage_still_works(client, monkeypatch):
    fake_model(monkeypatch, {"choices": [{"message": {"content": "hi"}}]})
    before = snapshot()
    res = client.post("/chat", json={"messages": [{"role": "user", "content": "hello"}]})
    after = snapshot()

    assert res.status_code == 200
    assert after["ok"] == before["ok"] + 1
    assert after["prompt_tokens"] == before["prompt_tokens"]
    assert after["completion_tokens"] == before["completion_tokens"]


def test_empty_messages_are_counted_as_400(client):
    before = snapshot()
    client.post("/chat", json={"messages": []})
    after = snapshot()
    assert after["bad_request"] == before["bad_request"] + 1


def test_an_unreachable_model_is_counted_as_502_without_tokens(client, monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(chat_app.requests, "post", fake_post)
    before = snapshot()
    client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    after = snapshot()

    assert after["bad_gateway"] == before["bad_gateway"] + 1
    assert after["durations"] == before["durations"] + 1
    assert after["prompt_tokens"] == before["prompt_tokens"]


def test_health_index_and_metrics_are_not_counted_as_chats(client):
    before = snapshot()
    client.get("/health")
    client.get("/")
    client.get("/metrics")
    assert snapshot() == before


def test_in_flight_gauge_returns_to_zero(client, monkeypatch):
    fake_model(monkeypatch, {"choices": [{"message": {"content": "hi"}}]})
    client.post("/chat", json={"messages": [{"role": "user", "content": "hello"}]})
    client.post("/chat", json={"messages": []})
    assert sample("chat_requests_in_flight") == 0
