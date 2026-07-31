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
    return response.json() or {}


def post_json(session: requests.Session, url: str, **kwargs) -> dict:
    settings = _get_settings()
    timeout = (settings.connect_timeout, settings.read_timeout)
    # See get_json: the delay must not be skipped on failure.
    try:
        response = session.post(url, timeout=timeout, **kwargs)
        response.raise_for_status()
    finally:
        pause()
    return response.json() or {}
