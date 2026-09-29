import os

import pytest
import requests

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
