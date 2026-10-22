"""Gather the markets' listings for a research run.

Sweep, don't search per product: sweeping each (market, category) once costs a few hundred
requests, gives every target the same candidate pool, and -- the part that matters -- lets a
price be RE-MATCHED without re-fetching, so a matcher fix is a seconds-long re-run. Sweeps are
cached on disk and reused for `max_age_h` hours; prices move daily, so the default is 24.

Search-only sources (`can_sweep` is False -- mediapark) are reached one query per target.
glotr is left out of the default set: its robots.txt declares `Crawl-delay: 10` and it is
crawled only by grant, in its own process with NARXNOMA_MIN_DELAY=10 NARXNOMA_MAX_DELAY=11.
"""

import dataclasses
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from narxnoma.matching.keys import CATEGORY_PREFIX
from narxnoma.research.model import Target
from narxnoma.sources import SOURCES

logger = logging.getLogger("narxnoma.research")

#: Market column order, fixed so two runs can be diffed side by side. Removing a market that
#: matched nothing would silently change the shape of the file between runs.
MARKET_ORDER = (
    "uzum",
    "texnomart",
    "mediapark",
    "alifshop",
    "beemarket",
    "olcha",
    "idea",
    "asaxiy",
    "radius",
    "openshop",
    "glotr",
)
DEFAULT_EXCLUDE = frozenset({"glotr"})


def default_markets() -> list[str]:
    return [m for m in MARKET_ORDER if m in SOURCES and m not in DEFAULT_EXCLUDE]


@dataclass
class Collected:
    #: (market, category) -> listing dicts
    sweeps: dict = field(default_factory=dict)
    #: market -> target name -> listing dicts (search-only markets)
    searches: dict = field(default_factory=dict)
    #: market -> ISO time of its OLDEST catalogue -- a survey is only as fresh as its stalest column
    fetched_at: dict = field(default_factory=dict)
    #: market -> why it has no (or partial) data
    notes: dict = field(default_factory=dict)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="seconds")


def _listing_dict(listing) -> dict:
    d = dataclasses.asdict(listing)
    d.pop("raw", None)
    return d


def _sweep_cached(slug: str, category: str, cache_dir: Path, max_age_h: float, force: bool):
    """-> (listings, fetched_ts). Raises on a failed sweep: a half-swept catalogue must not
    be recorded as a success."""
    path = cache_dir / f"{slug}__{category}.json"
    if path.exists() and not force:
        age_h = (time.time() - path.stat().st_mtime) / 3600
        if age_h <= max_age_h:
            logger.info("%-10s %-12s cache hit (%.1f h old)", slug, category, age_h)
            return json.loads(path.read_text(encoding="utf-8")), path.stat().st_mtime
    logger.info("%-10s %-12s sweeping...", slug, category)
    listings = [_listing_dict(x) for x in SOURCES[slug].sweep(category)]
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(listings, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # never leave a truncated cache behind
    logger.info("%-10s %-12s %d listings", slug, category, len(listings))
    return listings, path.stat().st_mtime


def search_query(target: Target) -> str:
    """Keep the query close to verbatim: a ranking autocomplete (mediapark) needs the RAM/storage
    and colour words to rank the exact variant into its short list. Only the leading category
    noun is dropped."""
    nouns = "|".join(re.escape(p) for p in CATEGORY_PREFIX.values())
    return re.sub(rf"^\s*(?:{nouns}|Смартфон|Телевизор)\s+", "", target.name, flags=re.I).strip()


def collect(
    markets: list[str],
    targets: list[Target],
    cache_dir: str | Path,
    max_age_h: float = 24,
    force: bool = False,
) -> Collected:
    out = Collected()
    cache = Path(cache_dir)
    categories = sorted({t.category for t in targets if t.category})
    for slug in markets:
        src = SOURCES[slug]
        stamps = []
        if src.can_sweep:
            for cat in categories:
                try:
                    listings, ts = _sweep_cached(slug, cat, cache, max_age_h, force)
                except Exception as exc:  # noqa: BLE001 -- one source must not end the run
                    logger.error("%s/%s failed: %s", slug, cat, exc)
                    out.notes[slug] = (
                        out.notes.get(slug, "") + f"{cat}: sweep failed ({exc}). "
                    ).strip()
                    continue
                out.sweeps[(slug, cat)] = listings
                stamps.append(ts)
                if not listings:
                    out.notes[slug] = (out.notes.get(slug, "") + f"{cat}: no listings. ").strip()
        else:
            hits, failures = {}, 0
            todo = [t for t in targets if t.category]
            for i, t in enumerate(todo, 1):
                try:
                    hits[t.name] = [_listing_dict(x) for x in src.search(search_query(t))]
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    logger.warning("%s search %r failed: %s", slug, t.name, exc)
                    hits[t.name] = []
                if i % 25 == 0:
                    logger.info("%-10s search %d/%d", slug, i, len(todo))
            out.searches[slug] = hits
            stamps.append(time.time())
            if failures:
                out.notes[slug] = f"{failures} of {len(todo)} searches failed."
        if stamps:
            out.fetched_at[slug] = _iso(min(stamps))
        elif slug not in out.notes:
            out.notes[slug] = "no data collected."
    return out
