"""One call from a product list to a `Research`: collect, then match."""

import logging
from datetime import datetime
from pathlib import Path

from narxnoma.research.collect import MARKET_ORDER, collect, default_markets
from narxnoma.research.match import index_by_brand, match_target
from narxnoma.research.model import Research, Target
from narxnoma.sources import SOURCES
from narxnoma.sources.http import get_json, polite_session

logger = logging.getLogger("narxnoma.research")

CBU_URL = "https://cbu.uz/ru/arkhiv-kursov-valyut/json/USD/"


def cbu_usd_rate() -> tuple[float, str]:
    """Official USD rate in UZS and its date, from the central bank. Raises when unreachable:
    a silent default would put a wrong number in every converted price."""
    data = get_json(polite_session(), CBU_URL)
    row = data[0] if isinstance(data, list) else data
    return float(str(row["Rate"]).replace(",", ".")), str(row["Date"])


def run_research(
    targets: list[Target],
    markets: list[str] | None = None,
    cache_dir: str | Path = "database/research_cache",
    max_age_h: float = 24,
    force: bool = False,
    title: str = "Market research",
    usd_rate: float | None = None,
) -> Research:
    markets = [m for m in MARKET_ORDER if m in (markets or default_markets())]
    unknown = [m for m in (markets or []) if m not in SOURCES]
    if unknown:
        raise ValueError(f"unknown market(s): {unknown}")
    rate_date = ""
    if any(t.currency == "USD" and t.our_price for t in targets):
        if usd_rate is None:
            usd_rate, rate_date = cbu_usd_rate()
        else:
            rate_date = "given on the command line"

    got = collect(markets, targets, cache_dir, max_age_h=max_age_h, force=force)
    pools = {key: index_by_brand(listings, key[1]) for key, listings in got.sweeps.items()}

    offers = []
    for t in targets:
        if not t.category:
            continue
        for m in markets:
            if SOURCES[m].can_sweep:
                offers += match_target(t, m, pools.get((m, t.category)))
            else:
                offers += match_target(t, m, None, got.searches.get(m, {}).get(t.name))
    logger.info(
        "%d offers for %d of %d products",
        len(offers),
        len({o.target for o in offers}),
        len(targets),
    )
    notes = dict(got.notes)
    no_cat = [t.name for t in targets if not t.category]
    if no_cat:
        logger.warning(
            "%d products have no category and were not matched (pass --category)", len(no_cat)
        )
    return Research(
        targets=targets,
        offers=offers,
        markets=markets,
        fetched_at=got.fetched_at,
        notes=notes,
        run_at=datetime.now().isoformat(timespec="seconds"),
        usd_rate=usd_rate,
        usd_rate_date=rate_date,
        title=title,
    )
