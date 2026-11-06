import logging

import pytest
import requests

from collector import fetch as fetch_module
from collector.fetch import fetch

FAKE_KEY = "testkey-0123456789abcdef"
URL = "https://example.test/feed.pb"


class FakeResponse:
    def __init__(self, status, content=b""):
        self.status_code = status
        self.content = content


@pytest.fixture
def sleeps(monkeypatch):
    """Record backoff waits instead of sleeping."""
    calls = []
    monkeypatch.setattr(fetch_module.time, "sleep", calls.append)
    return calls


def fake_get(monkeypatch, outcomes):
    """Each call to requests.get returns or raises the next outcome."""
    calls = []

    def _get(url, headers, timeout):
        calls.append(headers)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(fetch_module.requests, "get", _get)
    return calls


def test_retries_then_succeeds(monkeypatch, sleeps):
    calls = fake_get(
        monkeypatch,
        [requests.ConnectionError("down"), FakeResponse(500), FakeResponse(200, b"ok")],
    )
    result = fetch(URL, FAKE_KEY, timeout=1)
    assert result.data == b"ok"
    assert result.status == 200
    assert result.attempts == 3
    assert sleeps == [2, 4]
    assert calls[0] == {"api_key": FAKE_KEY}


def test_gives_up_after_four_attempts(monkeypatch, sleeps):
    fake_get(monkeypatch, [FakeResponse(503)] * 4)
    result = fetch(URL, FAKE_KEY, timeout=1)
    assert result.data is None
    assert result.status == 503
    assert result.attempts == 4
    assert sleeps == [2, 4, 8]


def test_no_retry_on_auth_error(monkeypatch, sleeps):
    fake_get(monkeypatch, [FakeResponse(401)])
    result = fetch(URL, FAKE_KEY, timeout=1)
    assert result.data is None
    assert result.error == "HTTP 401"
    assert result.attempts == 1
    assert sleeps == []


def test_key_never_logged(monkeypatch, sleeps, caplog):
    fake_get(monkeypatch, [requests.Timeout("slow")] * 3 + [FakeResponse(401)])
    with caplog.at_level(logging.DEBUG):
        fetch(URL, FAKE_KEY, timeout=1)
    assert caplog.records
    assert FAKE_KEY not in caplog.text
