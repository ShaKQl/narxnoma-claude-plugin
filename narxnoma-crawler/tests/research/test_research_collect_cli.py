import json
import os
import time

import pytest

from narxnoma.research import collect as C
from narxnoma.research.cli import build_parser
from narxnoma.research.model import Target
from narxnoma.sources.base import Listing


class FakeSource:
    def __init__(self, slug, can_sweep=True, fail=False):
        self.slug, self.can_sweep, self.fail, self.calls = slug, can_sweep, fail, 0

    def sweep(self, category="smartphones"):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        yield Listing(
            store_slug=self.slug,
            source_key="k1",
            name_raw="Samsung Galaxy A56 8/256GB",
            price=5_000_000,
            url="https://x.example/1",
            category=category,
        )

    def search(self, query):
        self.calls += 1
        yield Listing(
            store_slug=self.slug,
            source_key="s1",
            name_raw=f"found {query}",
            price=1_000_000,
            url="https://x.example/s",
            category="smartphones",
        )


@pytest.fixture()
def fakes(monkeypatch):
    fs = {
        "uzum": FakeSource("uzum"),
        "olcha": FakeSource("olcha", fail=True),
        "mediapark": FakeSource("mediapark", can_sweep=False),
    }
    monkeypatch.setattr(C, "SOURCES", fs)
    return fs


TARGETS = [Target("Samsung Galaxy A56 8/256GB", "smartphones")]


def test_sweep_is_cached_then_reused(fakes, tmp_path):
    first = C.collect(["uzum"], TARGETS, tmp_path)
    assert fakes["uzum"].calls == 1 and len(first.sweeps[("uzum", "smartphones")]) == 1
    C.collect(["uzum"], TARGETS, tmp_path)
    assert fakes["uzum"].calls == 1  # served from cache


def test_stale_cache_is_refetched_and_force_ignores_it(fakes, tmp_path):
    C.collect(["uzum"], TARGETS, tmp_path)
    cache = tmp_path / "uzum__smartphones.json"
    old = time.time() - 48 * 3600
    os.utime(cache, (old, old))
    C.collect(["uzum"], TARGETS, tmp_path, max_age_h=24)
    assert fakes["uzum"].calls == 2
    C.collect(["uzum"], TARGETS, tmp_path, force=True)
    assert fakes["uzum"].calls == 3


def test_a_failed_sweep_is_noted_and_does_not_end_the_run(fakes, tmp_path):
    got = C.collect(["olcha", "uzum"], TARGETS, tmp_path)
    assert "sweep failed" in got.notes["olcha"]
    assert ("olcha", "smartphones") not in got.sweeps and ("uzum", "smartphones") in got.sweeps
    assert (
        "olcha" not in got.fetched_at and "uzum" in got.fetched_at
    )  # the hole is visible, not hidden


def test_a_failed_sweep_leaves_no_cache_file(fakes, tmp_path):
    C.collect(["olcha"], TARGETS, tmp_path)
    assert not list(tmp_path.glob("olcha__*"))


def test_search_only_markets_are_queried_per_target(fakes, tmp_path):
    got = C.collect(["mediapark"], TARGETS, tmp_path)
    assert fakes["mediapark"].calls == 1
    assert got.searches["mediapark"][TARGETS[0].name][0]["price"] == 1_000_000


def test_search_query_drops_only_the_leading_category_noun():
    assert (
        C.search_query(Target("Смартфон Samsung Galaxy A56 8/256GB Black"))
        == "Samsung Galaxy A56 8/256GB Black"
    )


def test_default_markets_exclude_glotr_and_keep_a_fixed_order():
    ms = C.default_markets()
    assert "glotr" not in ms and ms.index("uzum") < ms.index("texnomart") < ms.index("openshop")


def test_cache_file_is_valid_json(fakes, tmp_path):
    C.collect(["uzum"], TARGETS, tmp_path)
    assert (
        json.loads((tmp_path / "uzum__smartphones.json").read_text(encoding="utf-8"))[0]["price"]
        == 5_000_000
    )


def test_cli_parser_knows_the_three_commands():
    p = build_parser()
    assert p.parse_args(["run", "--targets", "a.csv", "--out", "b.xlsx"]).pivots == "auto"
    assert (
        p.parse_args(
            ["workbook", "--from", "r.json", "--out", "b.xlsx", "--pivots", "ooxml"]
        ).pivots
        == "ooxml"
    )
    assert p.parse_args(["check", "b.xlsx", "--save"]).save is True
