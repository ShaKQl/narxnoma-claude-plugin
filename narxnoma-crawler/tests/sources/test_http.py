"""Tests for the polite HTTP layer.

Nothing here touches the network: polite_session is exercised against a
real (but never-called) requests.Session, and get_json/post_json are
exercised against a FakeSession stub. pause() is monkeypatched with a
counter so the suite stays fast.
"""
import json

import pytest
import requests

from narxnoma.sources import http


class FakeResponse:
    def __init__(self, json_data=None, raise_exc=None, text=None, status_code=200,
                json_exc=None):
        self._json_data = json_data if json_data is not None else {}
        self._raise_exc = raise_exc
        self._json_exc = json_exc
        self.text = text if text is not None else ""
        self.status_code = status_code

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_data


class FakeSession:
    """Stands in for requests.Session, recording calls instead of hitting the network."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self._response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._response


@pytest.fixture(autouse=True)
def reset_settings_cache(monkeypatch):
    # Fix 4: settings are now cached lazily on the module. Reset the cache
    # so tests don't depend on import order or on each other.
    monkeypatch.setattr(http, "_settings", None)


@pytest.fixture
def pause_counter(monkeypatch):
    calls = {"count": 0}

    def fake_pause():
        calls["count"] += 1

    monkeypatch.setattr(http, "pause", fake_pause)
    return calls


def test_polite_session_sets_browser_like_user_agent_and_referer():
    session = http.polite_session(referer="https://example.uz/catalog")
    assert "Mozilla" in session.headers["User-Agent"]
    assert session.headers["Referer"] == "https://example.uz/catalog"


def test_polite_session_omits_origin_when_not_supplied():
    session = http.polite_session(referer="https://example.uz/catalog")
    assert "Origin" not in session.headers


def test_polite_session_sets_origin_when_supplied():
    session = http.polite_session(
        referer="https://example.uz/catalog", origin="https://example.uz",
    )
    assert session.headers["Origin"] == "https://example.uz"


def test_polite_session_merges_extra_headers():
    session = http.polite_session(
        referer="https://example.uz/catalog",
        extra_headers={"X-Custom": "abc"},
    )
    assert session.headers["X-Custom"] == "abc"
    # the standard headers are still there
    assert session.headers["Referer"] == "https://example.uz/catalog"


def test_get_json_passes_connect_read_timeout_tuple(pause_counter):
    session = FakeSession(FakeResponse(json_data={"ok": True}))
    result = http.get_json(session, "https://example.uz/api")
    assert result == {"ok": True}
    _, _, kwargs = session.calls[0]
    settings = http._get_settings()
    assert kwargs["timeout"] == (settings.connect_timeout, settings.read_timeout)


def test_get_json_calls_pause_on_success(pause_counter):
    session = FakeSession(FakeResponse(json_data={"ok": True}))
    http.get_json(session, "https://example.uz/api")
    assert pause_counter["count"] == 1


def test_get_json_calls_pause_when_response_raises_for_status(pause_counter):
    # Regression test for Fix 1: the politeness delay must not be skipped
    # when the retailer starts returning errors -- that is exactly the
    # moment a retry loop needs to back off, not hit the API at full speed.
    error = requests.HTTPError("500 Server Error")
    session = FakeSession(FakeResponse(raise_exc=error))
    with pytest.raises(requests.HTTPError):
        http.get_json(session, "https://example.uz/api")
    assert pause_counter["count"] == 1


def test_get_json_raises_non_json_response_on_decode_failure(pause_counter):
    # Fix 2: retailers under load return WAF challenge pages, rate-limit
    # HTML, or expired-session redirects with a 200 status. That must not
    # surface as a bare, undiagnosable JSON decode error.
    body = "<html><body>Attention Required! | Cloudflare</body></html>"
    decode_error = json.JSONDecodeError("Expecting value", body, 0)
    session = FakeSession(FakeResponse(text=body, status_code=200, json_exc=decode_error))
    with pytest.raises(http.NonJsonResponse) as exc_info:
        http.get_json(session, "https://example.uz/api")
    message = str(exc_info.value)
    assert "https://example.uz/api" in message
    assert "Cloudflare" in message


def test_non_json_response_is_a_value_error():
    # An existing caller that does `except ValueError` (e.g. try_build_listing's
    # pattern) must keep working unchanged even though this is a new,
    # more specific exception type.
    exc = http.NonJsonResponse("https://example.uz/api", 200, "<html>...</html>")
    assert isinstance(exc, ValueError)


def test_get_json_calls_pause_when_body_fails_to_decode(pause_counter):
    # Same guarantee as test_get_json_calls_pause_when_response_raises_for_status,
    # but for a body that fails to decode rather than a bad status code.
    body = "not json"
    decode_error = json.JSONDecodeError("Expecting value", body, 0)
    session = FakeSession(FakeResponse(text=body, status_code=200, json_exc=decode_error))
    with pytest.raises(http.NonJsonResponse):
        http.get_json(session, "https://example.uz/api")
    assert pause_counter["count"] == 1
