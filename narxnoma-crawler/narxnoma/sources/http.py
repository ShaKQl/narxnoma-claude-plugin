"""Polite HTTP. Every retailer call goes through here.

We look exactly like the retailer's own SPA: their User-Agent, their Origin
and Referer, one request at a time, with a delay between them.
"""
import random
import time

import requests

from narxnoma.config import load_settings

_SETTINGS = load_settings()


def polite_session(referer: str, origin: str | None = None,
                   extra_headers: dict[str, str] | None = None) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": _SETTINGS.user_agent,
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
    })
    if origin:
        session.headers["Origin"] = origin
    if extra_headers:
        session.headers.update(extra_headers)
    return session


def pause() -> None:
    time.sleep(random.uniform(_SETTINGS.min_delay, _SETTINGS.max_delay))


def get_json(session: requests.Session, url: str, **kwargs) -> dict:
    timeout = (_SETTINGS.connect_timeout, _SETTINGS.read_timeout)
    response = session.get(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    pause()
    return response.json() or {}


def post_json(session: requests.Session, url: str, **kwargs) -> dict:
    timeout = (_SETTINGS.connect_timeout, _SETTINGS.read_timeout)
    response = session.post(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    pause()
    return response.json() or {}
