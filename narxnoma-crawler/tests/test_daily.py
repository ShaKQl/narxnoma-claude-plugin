"""Offline tests for narxnoma.daily: catalogue paging, field mapping, token reading, the lock."""

import json
import os
import time

import pytest

from narxnoma import daily


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, pages, status=200):
        self.pages, self.status, self.calls = pages, status, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((params["page"], headers["Authorization"]))
        if self.status != 200:
            return FakeResp({}, self.status)
        i = params["page"] - 1
        return FakeResp(self.pages[i] if i < len(self.pages) else {"items": []})


CFG = {
    "ECOM_PRODUCTS_URL": "https://example.test/api/products",
    "ECOM_TOKEN": "Bearer tkn",
    "ECOM_PAGE_SIZE": "2",
    "ECOM_PAUSE_S": "0",
}


def test_paginates_until_short_page_and_sends_bearer():
    pages = [{"items": [{"name": "a"}, {"name": "b"}]}, {"items": [{"name": "c"}]}]
    s = FakeSession(pages)
    got = daily.fetch_catalogue(CFG, s)
    assert [x["name"] for x in got] == ["a", "b", "c"]
    assert s.calls == [(1, "Bearer tkn"), (2, "Bearer tkn")]


@pytest.mark.parametrize(
    "payload",
    [
        [{"name": "a"}],
        {"data": [{"name": "a"}]},
        {"data": {"items": [{"name": "a"}]}},
        {"results": [{"name": "a"}], "total": 1},
    ],
)
def test_envelopes(payload):
    assert daily.extract_items(payload) == [{"name": "a"}]


def test_server_ignoring_page_does_not_loop():
    same = {"items": [{"name": "a"}, {"name": "b"}]}
    got = daily.fetch_catalogue(CFG, FakeSession([same] * 600))
    assert len(got) == 2  # stops on the repeated first item


def test_expired_token_is_a_clear_error():
    with pytest.raises(PermissionError, match="expired"):
        daily.fetch_catalogue(CFG, FakeSession([], status=401))


def test_targets_mapping_and_stats():
    items = [
        {
            "name": "Phone X 8/256",
            "price": "5 990 000",
            "category": {"name": "Смартфоны"},
            "is_active": True,
        },
        {"title": "TV", "sale_price": 3000000.0, "category_name": "Телевизоры", "active": 1},
        {"name": "Hidden", "price": 1, "is_active": False},
        {"name": "No price", "price": 0},
        {"price": 5},
        {"name": "Loose", "price": 100},
    ]
    rows, st = daily.to_targets(items, {})
    assert [r["name"] for r in rows] == ["Phone X 8/256", "TV", "Loose"]
    assert rows[0]["our price"] == 5990000.0 and rows[0]["category"] == "Смартфоны"
    assert st == {
        "seen": 6,
        "inactive": 1,
        "no_name": 1,
        "no_price": 1,
        "no_category": 1,
        "kept": 3,
    }


def test_include_inactive_switch():
    rows, _ = daily.to_targets(
        [{"name": "H", "price": 1, "is_active": False}], {"ECOM_ONLY_ACTIVE": "0"}
    )
    assert len(rows) == 1


def test_custom_field_mapping_with_dotted_path():
    rows, _ = daily.to_targets(
        [{"info": {"label": "Z"}, "pricing": {"uzs": 10}}],
        {"ECOM_FIELD_NAME": "info.label", "ECOM_FIELD_PRICE": "pricing.uzs"},
    )
    assert rows[0]["name"] == "Z" and rows[0]["our price"] == 10.0


def test_targets_file_round_trips_through_the_research_loader(tmp_path):
    from narxnoma.research.targets import load_targets

    p = tmp_path / "t.csv"
    daily.write_targets(
        [{"name": "Samsung Galaxy S24 8/256", "our price": 9000000.0, "category": "Смартфоны"}], p
    )
    (t,) = load_targets(p)
    assert t.name.startswith("Samsung") and t.our_price == 9000000.0 and t.category == "smartphones"


def test_shape_hides_values():
    s = daily.shape([{"name": "secret name", "price": 5, "category": {"name": "x"}}])
    assert s == {"name": "str", "price": "int", "category.name": "str"}
    assert "secret" not in json.dumps(s)


@pytest.mark.parametrize(
    "content,expect",
    [
        ("Bearer abc\n", "abc"),
        ('{"access_token": "abc"}', "abc"),
        ("OTHER=1\nECOM_TOKEN='abc'\n", "abc"),
    ],
)
def test_token_file_formats(tmp_path, content, expect):
    f = tmp_path / "tok"
    f.write_text(content, encoding="utf-8")
    assert daily.read_token({"ECOM_TOKEN_FILE": str(f)}) == expect


def test_token_is_reread_each_call(tmp_path):
    f = tmp_path / "tok"
    f.write_text("one")
    assert daily.read_token({"ECOM_TOKEN_FILE": str(f)}) == "one"
    f.write_text("two")
    assert daily.read_token({"ECOM_TOKEN_FILE": str(f)}) == "two"


def test_lock_excludes_and_recovers_stale(tmp_path):
    a, b = daily.Lock(tmp_path / "l"), daily.Lock(tmp_path / "l", stale_h=0.001)
    assert a.acquire()
    assert not daily.Lock(tmp_path / "l").acquire(wait_s=0)
    old = time.time() - 3600
    os.utime(tmp_path / "l", (old, old))
    assert b.acquire()  # stale -> taken over
    b.release()
    assert a.acquire()


def test_load_env_file(tmp_path):
    f = tmp_path / "e"
    f.write_text("# c\nECOM_PAGE_SIZE = 50\nTG_API_ID='7'\n", encoding="utf-8")
    cfg = daily.load_env(f)
    assert cfg["ECOM_PAGE_SIZE"] == "50" and cfg["TG_API_ID"] == "7"


def test_load_env_strips_inline_comments(tmp_path):
    f = tmp_path / "e"
    f.write_text(
        "TG_SESSION=C:\\tg\\userbot_session        # the .session file\n"
        "TG_API_HASH='ab # cd'  # quoted keeps its hash\n"
        "ECOM_EXTRA_PARAMS=a=1&b=2\n",
        encoding="utf-8",
    )
    cfg = daily.load_env(f)
    assert cfg["TG_SESSION"] == "C:\\tg\\userbot_session"
    assert cfg["TG_API_HASH"] == "ab # cd"
    assert cfg["ECOM_EXTRA_PARAMS"] == "a=1&b=2"


def test_shipped_env_example_parses_to_clean_values(monkeypatch):
    for k in list(os.environ):
        if k.startswith(("ECOM_", "TG_", "NARXNOMA_")):
            monkeypatch.delenv(k)
    example = daily.Path(__file__).parents[2] / "tools" / "daily" / "daily.env.example"
    cfg = daily.load_env(example)
    assert cfg["TG_SESSION"] and all("#" not in v for v in cfg.values()), cfg


def test_report_refuses_to_start_when_telegram_cannot_send(tmp_path, monkeypatch):
    monkeypatch.setattr(daily, "fetch_catalogue", lambda *a, **k: pytest.fail("fetched"))
    cfg = {
        "NARXNOMA_DAILY_DIR": str(tmp_path),
        "TG_SESSION": str(tmp_path / "nope"),
        "TG_API_ID": "1",
        "TG_API_HASH": "h",
    }
    assert "not found" in daily.telegram_problem(cfg)
    assert daily.job_report(cfg) == 1
    assert "missing" in daily.telegram_problem({})


def test_report_end_to_end_offline(tmp_path, monkeypatch):
    """Catalogue -> csv -> research on the cache -> workbook -> one send, no network."""
    from narxnoma.research import collect
    from narxnoma.sources import SOURCES

    def sweep(slug, category, cache_dir, max_age_h, force):
        rows = [
            {
                "store_slug": slug,
                "source_key": "k",
                "price": 4_990_000,
                "name_raw": "Samsung Galaxy A55 8/256GB Black",
                "url": f"https://x/{slug}",
                "availability": "IN_STOCK",
                "image_url": None,
                "category": category,
            }
        ]
        return (rows if category == "smartphones" else []), time.time()

    monkeypatch.setattr(collect, "_sweep_cached", sweep)
    for s in SOURCES.values():
        if not s.can_sweep:
            monkeypatch.setattr(s, "search", lambda q: [], raising=False)
    items = [
        {
            "name": "Samsung Galaxy A55 8/256GB Black",
            "price": "5 100 000",
            "category": {"name": "Smartphones"},
            "is_active": True,
        },
        {"name": "Old phone", "price": 1, "category": "Smartphones", "is_active": False},
    ]
    monkeypatch.setattr(daily, "fetch_catalogue", lambda *a, **k: items)
    monkeypatch.setattr(daily, "telegram_problem", lambda cfg: None)
    sent = []
    monkeypatch.setattr(daily, "send_telegram", lambda cfg, p, c: sent.append((p, c)))
    assert daily.job_report({"NARXNOMA_DAILY_DIR": str(tmp_path)}) == 0
    ((path, caption),) = sent
    assert path.name.startswith("market_analysis_") and path.exists()
    assert caption.startswith("Market analysis") and "1 products" in caption
    assert not (tmp_path / "daily.lock").exists()
