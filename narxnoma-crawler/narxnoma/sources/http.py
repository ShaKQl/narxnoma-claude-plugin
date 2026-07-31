"""Polite HTTP. Every retailer call goes through here.

We look exactly like the retailer's own SPA: their User-Agent, their Origin
and Referer, one request at a time, with a delay between them.
"""
import random
import time

import requests

from narxnoma.config import Settings, load_settings

# Loaded lazily so tests can monkeypatch settings without an import-time
# side effect baking a delay in before the test gets a chance to change it.
_settings: Settings | None = None


class NonJsonResponse(ValueError):
    """Raised when a 200-status response body is not valid JSON.

    Retailers under load hand back WAF challenge pages, rate-limit HTML, or
    expired-session redirects with an HTTP 200 -- response.json() would
    otherwise raise a bare "expecting value: line 1 column 1" that tells you
    nothing about which retailer or endpoint misbehaved. Carrying the URL,
    status, and a body snippet here is what makes the cause diagnosable from
    a single log line instead of requiring a live repro. Subclasses
    ValueError so existing `except ValueError` callers keep working
    unchanged.
    """

    def __init__(self, url: str, status_code: int, body_snippet: str) -> None:
        self.url = url
        self.status_code = status_code
        self.body_snippet = body_snippet
        super().__init__(
            f"non-JSON response from {url} (status {status_code}): {body_snippet!r}"
        )


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def polite_session(referer: str, origin: str | None = None,
                   extra_headers: dict[str, str] | None = None) -> requests.Session:
    settings = _get_settings()
    session = requests.Session()
    session.headers.update({
        "User-Agent": settings.user_agent,
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
    })
    if origin:
        session.headers["Origin"] = origin
    if extra_headers:
        session.headers.update(extra_headers)
    return session


def pause() -> None:
    settings = _get_settings()
    time.sleep(random.uniform(settings.min_delay, settings.max_delay))


def get_json(session: requests.Session, url: str, **kwargs) -> dict:
    settings = _get_settings()
    timeout = (settings.connect_timeout, settings.read_timeout)
    # The delay runs whether the request succeeds or raises: a failing
    # retailer is exactly when backing off matters most, and a retry loop
    # must not hit a struggling API at full speed.
    try:
        response = session.get(url, timeout=timeout, **kwargs)
        response.raise_for_status()
    finally:
        pause()
    try:
        return response.json() or {}
    except ValueError as exc:
        raise NonJsonResponse(url, response.status_code, response.text[:200]) from exc


def post_json(session: requests.Session, url: str, **kwargs) -> dict:
    settings = _get_settings()
    timeout = (settings.connect_timeout, settings.read_timeout)
    # See get_json: the delay must not be skipped on failure.
    try:
        response = session.post(url, timeout=timeout, **kwargs)
        response.raise_for_status()
    finally:
        pause()
    try:
        return response.json() or {}
    except ValueError as exc:
        raise NonJsonResponse(url, response.status_code, response.text[:200]) from exc
