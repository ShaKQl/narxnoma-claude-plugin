# Narxnoma Crawler Hardening Implementation Plan (Plan 2b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the crawler survive a bad afternoon at a retailer, stop it cataloguing things that are not phones, and let it reach the whole catalogue — the debt Plans 1–3 deliberately deferred, all of it now measured against live data.

**Architecture:** No new stages. One shared `paginate()` helper in `sources/base.py` replaces six hand-rolled loops and adds the per-page retry none of them have; the remaining tasks each close one measured hole in an existing module. Nothing here changes the matching engine or the clustering rules.

**Tech Stack:** Python 3.11+, `requests`, `psycopg[binary]` 3.x, PostgreSQL 16, pytest.

## Global Constraints

- Python 3.11 or newer. `narxnoma/matching/**` stays stdlib-only; a test enforces it.
- Tests read `NARXNOMA_TEST_DSN`, **never** `NARXNOMA_DSN`. `require_disposable_test_database()` refuses any database whose name lacks `test`. Export it before every run — a green run with it unset proves nothing.
- `docs/parsers/` is the source of truth for retailer behaviour and **is corrected in the same commit** as any behaviour change. Plan 3 breached this and had to fix it afterwards; do not repeat that.
- `parse(payload) -> list[Listing]` stays a **pure function of one response**, faithful and unfiltered. Crawl policy (category filtering, dedup, pagination) belongs in `sweep()`. The one documented exception is uzum, whose `search()` and `sweep()` hit the same noisy endpoint.
- Every source must keep its `test_every_listing_yields_a_usable_identity` test passing with its measured keyable floor.
- Price fences 100,000–100,000,000 SUM are enforced in Python, in a Postgres CHECK, and in tests. Never widen them to admit a listing.
- Start Postgres with:
  `.local/pgsql/bin/pg_ctl.exe -D .local/pgdata -l .local/pg.log -o "-p 55432" start`

## Baseline (measured 2026-08-02, `main` at `a19e534`)

| | |
|---|---|
| suite | 365 passed, 8 deselected, ruff clean |
| offers | 5,133 across 7 sources |
| attached | 4,138 (80.6%) · unresolved 995 (19.4%) |
| canonical variants | 1,398 |
| texnomart off-category by name | **142 of 467 (30.4%)** |
| non-phone products already catalogued as phone variants | **15, all texnomart** |
| `variant_price.computed_at` distinct values | **1 of 1,388** (Pass B cannot rotate) |
| brand vocabulary | 16 brands + 3 aliases = 19 queries |

---

## File Structure

```
narxnoma-crawler/
  narxnoma/
    sources/
      base.py            + paginate(), PageResult; retry policy lives here once
      http.py            unchanged
      brand_queries.py   + the crawl-frontier contract, widened vocabulary
      olcha.py           sweep() -> paginate()
      texnomart.py       sweep() -> paginate(); + phone filter in sweep()
      idea.py            sweep() -> paginate()
      beemarket.py       sweep()/search() -> paginate()
      alifshop.py        sweep() -> paginate()
      uzum.py            _walk() -> paginate()
    db/
      repository.py      + try_advisory_lock(); + variant.last_queried_at accessors
      schema.sql         + migration 3: variant.last_queried_at
    pipeline/
      backfill.py        build_query() takes a key, not a display name
    cli.py               + advisory lock around `cycle`
  tests/
    sources/test_paginate.py          new
    sources/test_contract_live.py     + a weekly-run marker note
    fixtures/sources/uzum_apple.json  new recorded fixture
```

---

### Task 1: `paginate()` — one loop, with the retry none of the six have

**Files:**
- Modify: `narxnoma-crawler/narxnoma/sources/base.py`
- Test: `narxnoma-crawler/tests/sources/test_paginate.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `paginate(fetch_page, parse_page, next_page, first_page=1, max_pages=200, retries=2) -> Iterator[Listing]`, where `fetch_page(page) -> dict`, `parse_page(payload) -> list[Listing]`, `next_page(payload, page) -> int | None` (return `None` to stop). Also `MAX_PAGES = 200` and `PAGE_RETRIES = 2`.

**Why this is Task 1.** Six clients hand-roll the same `while page <= last_page` loop, and **not one has per-page error handling** — a single transient failure on page 12 of 28 loses that source's whole cycle. This is not hypothetical: a beemarket 502 already cost a full source in a live run, and a retry minutes later succeeded, proving the failure was transient. Fixing it in six places would guarantee six subtly different behaviours.

The retry belongs **inside** the page loop, not around the sweep: retrying the sweep re-fetches every page already yielded, and `harvest_source` has already written those to the database in `WRITE_BATCH_SIZE` chunks.

- [ ] **Step 1: Write the failing tests**

Create `narxnoma-crawler/tests/sources/test_paginate.py`:

```python
"""The shared pagination loop. Six clients hand-rolled this; none retried."""
import pytest

from narxnoma.sources.base import Listing, paginate


def listing(key: str) -> Listing:
    return Listing(store_slug="test", source_key=key, name_raw=f"Phone {key}",
                   price=1_000_000, url=f"https://example.test/{key}",
                   availability="IN_STOCK")


def pages(*payloads):
    """A fetch_page over a fixed list of payloads, recording the calls made."""
    calls = []

    def fetch(page):
        calls.append(page)
        return payloads[page - 1]

    return fetch, calls


def parse_page(payload):
    return [listing(k) for k in payload["keys"]]


def next_page(payload, page):
    return page + 1 if page < payload["last"] else None


def test_walks_every_page_to_the_end():
    fetch, calls = pages({"keys": ["a", "b"], "last": 3},
                         {"keys": ["c"], "last": 3},
                         {"keys": ["d"], "last": 3})
    got = [x.source_key for x in paginate(fetch, parse_page, next_page)]
    assert got == ["a", "b", "c", "d"]
    assert calls == [1, 2, 3]


def test_a_transient_page_failure_is_retried_not_fatal():
    # THE BUG THIS EXISTS FOR: a beemarket 502 on one page lost that source's
    # entire cycle. A retry minutes later succeeded, so the failure really was
    # transient -- the sweep simply had no way to survive it.
    attempts = {"n": 0}

    def fetch(page):
        if page == 2:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise OSError("502 Bad Gateway")
        return {"keys": [f"p{page}"], "last": 3}

    got = [x.source_key for x in paginate(fetch, parse_page, next_page)]
    assert got == ["p1", "p2", "p3"]
    assert attempts["n"] == 2, "the failing page must be retried, not skipped"


def test_a_page_that_keeps_failing_raises_after_its_retries():
    # Retrying forever would hammer a retailer that is genuinely down. The
    # error must surface so harvest_run records ok=false and the coverage
    # report flags the source.
    def fetch(page):
        if page == 2:
            raise OSError("503 Service Unavailable")
        return {"keys": [f"p{page}"], "last": 3}

    with pytest.raises(OSError, match="503"):
        list(paginate(fetch, parse_page, next_page, retries=2))


def test_pages_already_yielded_survive_a_later_failure():
    # harvest_source writes in batches as the sweep proceeds, so everything
    # yielded before the failure is already durable. The generator must not
    # discard it -- that is why the retry sits INSIDE the loop rather than
    # around the whole sweep.
    def fetch(page):
        if page == 3:
            raise OSError("boom")
        return {"keys": [f"p{page}"], "last": 5}

    got = []
    with pytest.raises(OSError):
        for item in paginate(fetch, parse_page, next_page, retries=0):
            got.append(item.source_key)
    assert got == ["p1", "p2"]


def test_max_pages_stops_a_runaway_paginator():
    # A retailer whose last_page grows every request, or a next_page that
    # never returns None, would otherwise loop until the cron killed it.
    def fetch(page):
        return {"keys": [f"p{page}"], "last": 10_000}

    got = list(paginate(fetch, parse_page, next_page, max_pages=5))
    assert len(got) == 5


def test_an_empty_page_ends_the_sweep():
    # HTTP 200 with no items is how a retailer signals the end -- and also how
    # a rescoped endpoint signals it has nothing. Stopping is right; noticing
    # the catalogue shrank is EXPECTED_MIN_OFFERS' job, not this loop's.
    fetch, calls = pages({"keys": ["a"], "last": 9}, {"keys": [], "last": 9})
    got = [x.source_key for x in paginate(fetch, parse_page, next_page)]
    assert got == ["a"]
    assert calls == [1, 2]


def test_retry_pauses_between_attempts(monkeypatch):
    # Retrying a struggling API at full speed is the opposite of backing off.
    slept = []
    monkeypatch.setattr("narxnoma.sources.base.pause", lambda: slept.append(1))

    def fetch(page):
        if page == 1 and not slept:
            raise OSError("transient")
        return {"keys": ["a"], "last": 1}

    list(paginate(fetch, parse_page, next_page))
    assert slept, "a retry must pause before trying again"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_paginate.py -v`
Expected: FAIL — `ImportError: cannot import name 'paginate' from 'narxnoma.sources.base'`.

- [ ] **Step 3: Implement `paginate()` in `base.py`**

Add near the bottom of `narxnoma-crawler/narxnoma/sources/base.py`, and add `from narxnoma.sources.http import pause` to its imports:

```python
# A runaway paginator -- a retailer whose reported last_page grows with every
# request, or a next_page that never returns None -- would loop until the cron
# killed it. Well above the largest real catalogue observed (beemarket, 28
# pages; uzum, ~14 per brand).
MAX_PAGES = 200

# Per-PAGE retries. The unit matters: retrying the whole sweep would re-fetch
# every page already yielded and already written to the database in
# WRITE_BATCH_SIZE chunks by harvest_source.
PAGE_RETRIES = 2


def paginate(fetch_page, parse_page, next_page, first_page: int = 1,
             max_pages: int = MAX_PAGES,
             retries: int = PAGE_RETRIES) -> Iterator[Listing]:
    """Walk a paginated endpoint, surviving a transient failure on one page.

    Six clients hand-rolled this loop and not one of them retried, so a single
    bad response lost that source's entire cycle -- a beemarket 502 really did
    cost a whole source in a live run, and a retry minutes later succeeded.

    `fetch_page(page) -> payload`, `parse_page(payload) -> list[Listing]`,
    `next_page(payload, page) -> int | None`; returning None ends the sweep, as
    does a page that parses to nothing.

    A page that fails all its attempts RAISES. That is deliberate: swallowing it
    would let a half-swept catalogue be recorded as a success, which is the one
    failure mode `EXPECTED_MIN_OFFERS` and `harvest_run.ok` exist to catch.
    Everything yielded before the failure is already durable, so the caller
    keeps it.
    """
    page = first_page
    for _ in range(max_pages):
        payload = None
        for attempt in range(retries + 1):
            try:
                payload = fetch_page(page)
                break
            except Exception:
                if attempt == retries:
                    raise
                logger.warning("page %d failed (attempt %d/%d), retrying",
                               page, attempt + 1, retries + 1)
                # Back off before trying again -- a retry loop must not hit a
                # struggling API at full speed.
                pause()

        listings = parse_page(payload)
        if not listings:
            return
        yield from listings

        following = next_page(payload, page)
        if following is None:
            return
        page = following
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_paginate.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Prove the retry is real, not vacuous**

Temporarily change `if attempt == retries:` to `if True:` and re-run. Expected: `test_a_transient_page_failure_is_retried_not_fatal` and `test_retry_pauses_between_attempts` fail. Revert.

- [ ] **Step 6: Commit**

```bash
git add narxnoma-crawler/narxnoma/sources/base.py narxnoma-crawler/tests/sources/test_paginate.py
git commit -m "feat(sources): add paginate() with the per-page retry no client had"
```

---

### Task 2: Move all six sweeping clients onto `paginate()`

**Files:**
- Modify: `narxnoma-crawler/narxnoma/sources/olcha.py` (`sweep`), `texnomart.py` (`_paginate`), `idea.py` (`sweep`), `beemarket.py` (`sweep`, `search`), `alifshop.py` (`sweep`), `uzum.py` (`_walk`)
- Test: the existing per-source test files, unchanged, must all still pass

**Interfaces:**
- Consumes: `paginate`, `MAX_PAGES` from Task 1.
- Produces: no new public names. Every client's `sweep()`/`search()` signature is unchanged.

**The behaviour that must not change.** Each client keeps its own endpoint, params, category filtering and dedup. Only the loop moves. Every source's existing parse tests and its `test_every_listing_yields_a_usable_identity` floor must pass untouched — if one fails, the migration changed behaviour and is wrong.

- [ ] **Step 1: Run the suite and record the starting point**

Run: `cd narxnoma-crawler && python -m pytest -q`
Expected: `365 passed, 8 deselected`. Write the number down; it must not fall.

- [ ] **Step 2: Migrate olcha**

Replace `sweep()` in `narxnoma-crawler/narxnoma/sources/olcha.py`:

```python
    def sweep(self) -> Iterator[Listing]:
        """Every phone in olcha's telefony category, walking pagination to the end."""
        session = self._get_session()

        def fetch(page):
            return get_json(session, API_URL,
                            params={"page": page, "per_page": PER_PAGE,
                                    "category": CATEGORY})

        def following(payload, page):
            paginator = ((payload or {}).get("data") or {}).get("paginator") or {}
            return page + 1 if page < paginator.get("last_page", page) else None

        yield from paginate(fetch, parse, following)
```

Add `from narxnoma.sources.base import paginate` to olcha's imports and delete the `TODO(plan-3)` comment.

- [ ] **Step 3: Migrate texnomart**

Replace `_paginate()` in `narxnoma-crawler/narxnoma/sources/texnomart.py`:

```python
    def _paginate(self, query: str) -> Iterator[Listing]:
        session = self._get_session()

        def fetch(page):
            return get_json(session, API_URL,
                            params={"q": query, "page": page, "limit": LIMIT})

        def following(payload, page):
            pagination = ((payload or {}).get("data") or {}).get("pagination") or {}
            return page + 1 if page < pagination.get("total_page", page) else None

        yield from paginate(fetch, parse, following)
```

- [ ] **Step 4: Migrate beemarket (both `sweep` and `search`)**

```python
    def sweep(self) -> Iterator[Listing]:
        """Every phone in BeeMarket's smartfony category. See the module
        docstring for why this hits the category-scoped endpoint rather than
        the documented generic search."""
        yield from self._walk(SWEEP_API_URL, {"is_bshop": 1},
                              _filter_phone_listings)

    def search(self, query: str) -> Iterator[Listing]:
        yield from self._walk(API_URL, {"q": query, "is_bshop": 1})

    def _walk(self, url, params, post_filter=None) -> Iterator[Listing]:
        session = self._get_session()

        def fetch(page):
            return get_json(session, url, params={**params, "page": page})

        def parse_page(payload):
            listings = parse(payload)
            return post_filter(listings) if post_filter else listings

        def following(payload, page):
            data = (payload or {}).get("data") or {}
            return page + 1 if page < data.get("last_page", page) else None

        yield from paginate(fetch, parse_page, following)
```

**Watch this one.** `_filter_phone_listings` can legitimately empty a page whose raw payload had items, and `paginate` stops on an empty parse. Pass the filter as `post_filter` **only** if beemarket's category endpoint returns exclusively phones (it does — that is why the endpoint was chosen). If a live run shows the sweep stopping short, move the filter out of `parse_page` and apply it to `paginate`'s output instead.

- [ ] **Step 5: Migrate idea, alifshop and uzum**

`idea.py` has no pagination — it issues one request per brand query. Leave its loop alone; it has nothing to hoist. Add a one-line comment saying so, so the next reader does not go looking:

```python
        # No pagination: idea returns one full response per brand query, so
        # there is no page loop to hoist onto base.paginate().
```

`alifshop.py`'s `sweep()` walks `page < n_pages and page < MAX_PAGES` per brand, after a facet-discovery request. Replace only the inner page loop with `paginate(..., first_page=0)` — alifshop is **0-based**. Keep the per-brand facet discovery exactly as it is.

`uzum.py`'s `_walk()` becomes:

```python
    def _walk(self, text: str) -> Iterator[Listing]:
        def fetch(offset):
            return self._fetch_payload(text, offset)

        def following(payload, offset):
            nxt = offset + PAGE_LIMIT
            return nxt if nxt <= OFFSET_CAP else None

        yield from paginate(fetch, parse, following, first_page=0)
```

uzum paginates by **offset, not page number**, and caps at `OFFSET_CAP`. `paginate`'s "page" is just an opaque cursor, which is why this works. Delete uzum's `TODO(plan-3)` comment.

- [ ] **Step 6: Run the full suite**

Run: `cd narxnoma-crawler && export NARXNOMA_TEST_DSN="postgresql://narxnoma@127.0.0.1:55432/narxnoma_test" && python -m pytest -q`
Expected: PASS, at least 365 + 7 = 372.

- [ ] **Step 7: Prove it live against one real retailer**

Run: `cd narxnoma-crawler && export NARXNOMA_DSN="postgresql://narxnoma@127.0.0.1:55432/narxnoma" && python -m narxnoma.cli harvest --source olcha`
Expected: `seen=` within ±5% of 448, status `ok`, and the coverage table showing olcha above its floor of 300. A large drop means the migration lost pages.

- [ ] **Step 8: Commit**

```bash
git add narxnoma-crawler/narxnoma/sources/
git commit -m "refactor(sources): move every sweep onto the shared paginate()"
```

---

### Task 3: texnomart is cataloguing things that are not phones

**Files:**
- Modify: `narxnoma-crawler/narxnoma/sources/texnomart.py`
- Modify: `docs/parsers/texnomart.md`
- Test: `narxnoma-crawler/tests/sources/test_texnomart.py`

**Interfaces:**
- Consumes: `paginate` (Task 1).
- Produces: `is_phone_listing(listing) -> bool` in `texnomart.py`, applied in `sweep()` only.

**Measured, not assumed.** texnomart is the only swept source with no category filter. Of its 467 live offers, **142 (30.4%) are not phones** — tablets, laptops, adapters, cases. And they do not merely pollute `unresolved_offer`: a tablet has a brand, a memory pair and a colour, so it forms a **full key** and becomes a canonical product. **15 non-phone variants are in the catalogue right now, all from texnomart**, including:

```
Смартфон Samsung A11 Plus 6/128 ГБ, Серый     <- Galaxy Tab A11+
Смартфон Huawei 11 SE 8/128 ГБ, Серый         <- MatePad 11 SE
Смартфон Apple iPhone 11 A16 128 ГБ, Синий    <- an iPad
```

texnomart's items carry **no category field at all** — verified against the recorded fixture — so unlike idea (`category_id`) and beemarket (a category endpoint) there is no structured signal. The only usable evidence is the product-type noun the retailer puts in the name: `Plansheti`, `Noutbuki`, `adapteri`. That is weaker evidence than a category id, so the rule must be a **denylist of product-type nouns, not an allowlist of phone words** — an allowlist would silently drop any phone whose name lacks the expected noun, and losing real phones is worse than admitting the odd accessory.

- [ ] **Step 1: Write the failing tests**

Append to `narxnoma-crawler/tests/sources/test_texnomart.py`:

```python
from narxnoma.sources.texnomart import is_phone_listing


def _listing(name):
    from narxnoma.sources.base import Listing
    return Listing(store_slug="texnomart", source_key="k", name_raw=name,
                   price=2_000_000, url="https://texnomart.uz/x",
                   availability="IN_STOCK")


def test_tablets_and_laptops_are_not_phones():
    """Measured live: 142 of texnomart's 467 offers are not phones, and 15
    became canonical PRODUCTS -- a tablet has a brand, a memory pair and a
    colour, so it forms a full key exactly like a phone does. The catalogue
    really did contain "Смартфон Samsung A11 Plus 6/128 ГБ" (a Galaxy Tab)
    and "Смартфон Apple iPhone 11 A16 128 ГБ" (an iPad).
    """
    for name in [
        "Samsung Tab A11 Wi-Fi 8/128GB Gray Plansheti",
        "Honor Pad X7 4/128GB Space Grey Plansheti",
        'Huawei MatePad 11.5"S PaperMatte WIFI 12/256GB Grey Plansheti',
        "Asus VivoBook 15 i5/8/512 Silver Noutbuki",
        "Samsung EP-T6010NBEGRU 60W Black adapteri",
    ]:
        assert not is_phone_listing(_listing(name)), name


def test_real_phones_survive():
    for name in [
        "Samsung Galaxy A17 4G 8/256GB Qora",
        "Apple iPhone 17 Pro 256GB Silver",
        "Xiaomi Redmi Note 15 12/256 GB Black",
        "Honor X9d 12/256GB Black",
    ]:
        assert is_phone_listing(_listing(name)), name


def test_the_rule_is_a_denylist_not_an_allowlist():
    """A phone whose name carries no product-type noun at all must pass.
    An allowlist of phone words would silently drop it, and losing a real
    phone is worse than admitting the odd accessory -- which the price
    fence and the matcher then get a second chance at.
    """
    assert is_phone_listing(_listing("Nothing Phone 3a 8/256 Grey"))
    assert is_phone_listing(_listing("ZTE Blade V70 8/256"))


def test_parse_stays_unfiltered():
    """parse() is a pure function of the payload and must stay faithful --
    the filter is CRAWL POLICY and belongs in sweep(). The recorded count
    pin exists to catch exactly this drifting.
    """
    listings = parse(payload())
    assert len(listings) == PARSED_COUNT
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_texnomart.py -v`
Expected: FAIL — `cannot import name 'is_phone_listing'`.

- [ ] **Step 3: Implement**

Add to `narxnoma-crawler/narxnoma/sources/texnomart.py`:

```python
# texnomart items carry NO category field -- verified against the recorded
# fixture, unlike idea (category_id) and beemarket (a category endpoint). The
# only usable signal is the product-type noun the retailer appends to the
# name, which is weaker evidence, so this is a DENYLIST of things that are
# not phones rather than an allowlist of things that are: an allowlist would
# silently drop any phone whose name lacks the expected word, and losing a
# real phone is worse than admitting an accessory the price fence and the
# matcher still get a chance to reject.
#
# Measured on 467 live offers: 142 (30.4%) are not phones, and 15 of them had
# already become canonical PRODUCTS -- a tablet carries a brand, a memory pair
# and a colour, so it forms a full key exactly as a phone does.
_NOT_A_PHONE = re.compile(
    r"\b("
    r"plansh\w*|планшет\w*|noutbuk\w*|ноутбук\w*|"
    r"adapter\w*|адаптер\w*|zaryadk\w*|зарядн\w*|"
    r"chexol\w*|чехол\w*|shisha\w*|стекл\w*|plyonka\w*|плёнк\w*|пленк\w*|"
    r"quloqchin\w*|наушник\w*|kabel\w*|кабел\w*|powerbank|"
    r"televizor\w*|телевизор\w*|soat\w*|watch|часы|"
    r"matepad|ipad|galaxy tab|pad\s|tab\s"
    r")\b",
    re.I,
)


def is_phone_listing(listing) -> bool:
    """False for the accessories and non-phone devices texnomart mixes in."""
    return not _NOT_A_PHONE.search(listing.name_raw or "")
```

Then apply it in `sweep()` only — `parse()` stays unfiltered:

```python
    def sweep(self) -> Iterator[Listing]:
        """Every phone texnomart returns for the generic query 'smartfon'.

        The filter is crawl POLICY and lives here, not in parse(): parse must
        stay a faithful pure function of one response.
        """
        kept = dropped = 0
        for listing in self._paginate(SWEEP_QUERY):
            if is_phone_listing(listing):
                kept += 1
                yield listing
            else:
                dropped += 1
        # Logged rather than silent: if a texnomart naming change made this
        # rule match everything, the sweep would empty and only this line
        # would say why.
        logger.info("texnomart sweep: %d phones kept, %d non-phones dropped",
                    kept, dropped)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_texnomart.py -v`
Expected: PASS.

- [ ] **Step 5: Measure it against the live catalogue before trusting it**

```bash
cd narxnoma-crawler && export NARXNOMA_DSN="postgresql://narxnoma@127.0.0.1:55432/narxnoma"
python -c "
import psycopg, sys; sys.path.insert(0,'.')
from narxnoma.sources.texnomart import is_phone_listing
from narxnoma.sources.base import Listing
with psycopg.connect('postgresql://narxnoma@127.0.0.1:55432/narxnoma') as c, c.cursor() as cur:
    cur.execute(\"SELECT o.name_raw FROM offer o JOIN store s ON s.id=o.store_id WHERE s.slug='texnomart'\")
    rows=[r[0] for r in cur.fetchall()]
d=[n for n in rows if not is_phone_listing(Listing('texnomart','k',n,1000000,'u','IN_STOCK'))]
print(f'dropped {len(d)} of {len(rows)}')
[print('  ',x) for x in d[:40]]
"
```

**Read every dropped name.** Expected around 140 of 467. If a real phone appears in that list, the rule is wrong — narrow it and re-measure. Report the count and any judgement calls.

- [ ] **Step 6: Correct `docs/parsers/texnomart.md`**

Add a section recording: that texnomart items carry no category field; that the rule is a denylist and why; the measured 142/467; the 15 non-phone variants that had reached the catalogue; and that the doc's previously stated mitigation belonged to the target-driven matcher and does not apply at harvest time.

- [ ] **Step 7: Commit**

```bash
git add narxnoma-crawler/narxnoma/sources/texnomart.py narxnoma-crawler/tests/sources/test_texnomart.py docs/parsers/texnomart.md
git commit -m "fix(texnomart): stop cataloguing tablets and accessories as phones"
```

---

### Task 4: `BRAND_QUERIES` is a crawl frontier, not a vocabulary

**Files:**
- Modify: `narxnoma-crawler/narxnoma/matching/brands.py`
- Modify: `narxnoma-crawler/narxnoma/sources/brand_queries.py`
- Test: `narxnoma-crawler/tests/matching/test_brands.py`, `narxnoma-crawler/tests/sources/test_brand_queries.py`

**Interfaces:**
- Consumes: nothing.
- Produces: no new names. `BRANDS` gains entries; `BRAND_QUERIES` grows with it automatically.

**The contract nobody wrote down.** `BRANDS` was built as a **recognition** vocabulary, where a missing brand degrades one name. It now doubles as a **crawl frontier** for idea, alifshop and uzum, which have no catalogue browse — and there a missing brand means **zero offers, permanently**. Those two roles have opposite failure modes, and only one of them is documented.

Current vocabulary is 16 brands + 3 aliases. Absent, and therefore invisible to three sources: **itel, nokia, oneplus, nubia, blackview, doogee, ulefone, tcl, alcatel, lava, micromax**. The Uzbek market genuinely carries itel and Nokia in volume.

- [ ] **Step 1: Write the failing tests**

Append to `narxnoma-crawler/tests/sources/test_brand_queries.py`:

```python
def test_brands_sold_in_uzbekistan_are_reachable():
    """BRAND_QUERIES is the ENTIRE catalogue reach of idea, alifshop and
    uzum -- none has a browsable category endpoint. A brand missing here is
    not a degraded name, it is zero offers, permanently. itel and Nokia sell
    in volume in this market and neither was reachable.
    """
    for brand in ("itel", "nokia", "oneplus", "nubia", "tcl"):
        assert brand in BRAND_QUERIES, f"{brand} is unreachable by three sources"


def test_queries_stay_derived_from_the_matching_vocabulary():
    # Hand-maintaining a second list is how the two drift apart.
    from narxnoma.matching.brands import BRAND_ALIASES, BRANDS
    assert set(BRAND_QUERIES) == set(BRANDS) | set(BRAND_ALIASES)
```

Append to `narxnoma-crawler/tests/matching/test_brands.py`:

```python
def test_new_brands_are_recognised_in_real_listing_shapes():
    from narxnoma.matching import extract_features
    assert extract_features("itel A70 4/128 GB Black").brand == "itel"
    assert extract_features("Nokia 110 4G Dual SIM Blue").brand == "nokia"
    assert extract_features("OnePlus Nord 4 12/256 Green").brand == "oneplus"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_brand_queries.py tests/matching/test_brands.py -v`
Expected: FAIL on the new assertions.

- [ ] **Step 3: Widen `BRANDS` and state the dual contract**

In `narxnoma-crawler/narxnoma/matching/brands.py`, extend `BRANDS` with `"itel", "nokia", "oneplus", "nubia", "tcl", "blackview", "doogee", "ulefone"` and add above the list:

```python
# TWO ROLES, WITH OPPOSITE FAILURE MODES -- read this before removing an entry.
#
# 1. RECOGNITION vocabulary for extract_features. A brand missing here degrades
#    ONE listing's identity.
# 2. CRAWL FRONTIER, via narxnoma.sources.brand_queries. idea, alifshop and
#    uzum have no browsable catalogue endpoint, so this list is their ENTIRE
#    reach. A brand missing here is not a degraded name -- it is ZERO OFFERS,
#    permanently, from three of seven sources, and nothing in the system
#    reports the absence of something never looked for.
#
# So this list is cheap to extend and expensive to trim. Adding a brand nobody
# sells costs one wasted query per cycle; omitting one costs its whole catalogue.
```

- [ ] **Step 4: Run to verify pass, and check the golden corpus did not move**

Run: `cd narxnoma-crawler && python -m pytest tests/matching tests/sources/test_brand_queries.py -q`
Expected: PASS — including `test_golden.py`, whose `MAX_DISAGREEMENTS = 1` must still hold. A widened brand vocabulary can change which candidates match; if the count rises, report which rows and why before going further.

- [ ] **Step 5: Measure the cost of the wider frontier**

The three brand-driven sources now issue 27 queries per cycle instead of 19. uzum paginates each to `OFFSET_CAP`, so this is the largest single increase in request volume in the project. Run one real uzum sweep and report wall-clock time and offers gained:

```bash
cd narxnoma-crawler && export NARXNOMA_DSN="postgresql://narxnoma@127.0.0.1:55432/narxnoma"
time python -m narxnoma.cli harvest --source uzum
```

Report the before (2,344 seen) and after counts. If the new brands yield nothing at a source, say so — that is evidence for trimming *that source's* list, not the shared vocabulary.

- [ ] **Step 6: Commit**

```bash
git add narxnoma-crawler/narxnoma/matching/brands.py narxnoma-crawler/narxnoma/sources/brand_queries.py narxnoma-crawler/tests/
git commit -m "feat(brands): state the crawl-frontier contract and widen the vocabulary"
```

---

### Task 5: One cycle at a time

**Files:**
- Modify: `narxnoma-crawler/narxnoma/db/repository.py`
- Modify: `narxnoma-crawler/narxnoma/cli.py`
- Test: `narxnoma-crawler/tests/db/test_advisory_lock.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `try_advisory_lock(conn, key: int) -> bool` in `repository.py`; `CYCLE_LOCK_KEY = 2026_0802` in `cli.py`.

**Why.** A cycle makes 400+ requests at up to a 90-second read timeout. A single slow retailer can push it past four hours, at which point the next cron starts **while the first is still running** — and the two together double our request rate at every retailer simultaneously, which is exactly the behaviour that gets an IP blocked. `ishonchsale.uz` already 403s our current IP at Cloudflare's edge, so this is not a theoretical concern.

A Postgres advisory lock is the right instrument: it is held by the **session**, so it is released automatically when the process dies, however it dies. A lock table would need cleanup logic for the crash case, and that logic is where this kind of guard usually fails.

- [ ] **Step 1: Write the failing tests**

Create `narxnoma-crawler/tests/db/test_advisory_lock.py`:

```python
"""One cycle at a time. A second overlapping run doubles our request rate at
every retailer at once, which is how an IP gets blocked."""
import psycopg
import pytest

from narxnoma.db.repository import try_advisory_lock

pytestmark = pytest.mark.db

KEY = 20260802


def test_the_lock_is_granted_when_free(db_conn):
    assert try_advisory_lock(db_conn, KEY) is True


def test_a_second_connection_is_refused_while_it_is_held(db_conn, dsn):
    assert try_advisory_lock(db_conn, KEY) is True
    with psycopg.connect(dsn) as other:
        assert try_advisory_lock(other, KEY) is False


def test_the_lock_is_released_when_the_session_ends(dsn):
    # Session-scoped, so a crashed cycle cannot wedge the crontab forever.
    # This is the property a lock TABLE would need explicit cleanup for.
    with psycopg.connect(dsn) as first:
        assert try_advisory_lock(first, KEY) is True
    with psycopg.connect(dsn) as second:
        assert try_advisory_lock(second, KEY) is True


def test_different_keys_do_not_block_each_other(db_conn, dsn):
    assert try_advisory_lock(db_conn, KEY) is True
    with psycopg.connect(dsn) as other:
        assert try_advisory_lock(other, KEY + 1) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && export NARXNOMA_TEST_DSN="postgresql://narxnoma@127.0.0.1:55432/narxnoma_test" && python -m pytest tests/db/test_advisory_lock.py -v`
Expected: FAIL — `cannot import name 'try_advisory_lock'`.

- [ ] **Step 3: Implement in `repository.py`**

```python
def try_advisory_lock(conn: psycopg.Connection, key: int) -> bool:
    """Take a session-scoped advisory lock, or return False immediately.

    Session-scoped rather than transaction-scoped on purpose: the lock must
    outlive every transaction a cycle runs, and must be released even if the
    process is killed. Postgres drops it when the connection closes, however
    that happens -- a lock TABLE would need explicit crash cleanup, and that
    cleanup is where this kind of guard usually fails.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
        return bool(cur.fetchone()[0])
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && python -m pytest tests/db/test_advisory_lock.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Guard the `cycle` command**

In `narxnoma-crawler/narxnoma/cli.py`, add `CYCLE_LOCK_KEY = 20260802` near the top, and immediately after `migrate(conn)` inside the `cycle` branch:

```python
            if not repository.try_advisory_lock(conn, CYCLE_LOCK_KEY):
                logging.error(
                    "another cycle is already running; refusing to start a "
                    "second one. Two concurrent cycles double our request rate "
                    "at every retailer at once.")
                return 1
```

Return code 1 is deliberate: a skipped cycle is not a success, and cron should surface it.

- [ ] **Step 6: Add the CLI test**

Append to `narxnoma-crawler/tests/test_cli.py`:

```python
def test_cycle_refuses_to_run_twice_at_once(db_conn, dsn, monkeypatch):
    import psycopg
    from narxnoma.cli import CYCLE_LOCK_KEY, main
    from narxnoma.db.repository import try_advisory_lock

    holder = psycopg.connect(dsn)
    try:
        assert try_advisory_lock(holder, CYCLE_LOCK_KEY) is True
        monkeypatch.setenv("NARXNOMA_DSN", dsn)
        assert main(["cycle"]) == 1
    finally:
        holder.close()
```

- [ ] **Step 7: Run the full suite and commit**

```bash
cd narxnoma-crawler && python -m pytest -q
git add narxnoma-crawler/narxnoma/db/repository.py narxnoma-crawler/narxnoma/cli.py narxnoma-crawler/tests/
git commit -m "feat(cli): refuse to start a second cycle while one is running"
```

---

### Task 6: Record the Apple-query uzum fixture

**Files:**
- Create: `narxnoma-crawler/tests/fixtures/sources/uzum_apple.json`
- Test: `narxnoma-crawler/tests/sources/test_uzum.py`

**Interfaces:**
- Consumes: nothing.
- Produces: no new names — a second fixture and the tests over it.

**Why this matters more now than when it was first deferred.** uzum's `Модель`-override path has only ever been tested on **constructed input**: the recorded Samsung fixture contains no SKU carrying a `Модель` characteristic. That was flagged as "record this before the first live uzum sweep" and never done.

Since then that exact path has been **substantially rewritten** — `_states_memory`, the prefix truncation, the range-versus-spec rule, the tight-hyphen separator. It is now the most-changed and least-fixture-covered code in the project, and one of those changes shipped a Critical that only a live diff caught. The evidence today is a replay against the live database, which is real but is not something the suite runs.

`uzum.md` §5a's own worked example is an iPhone, and every card-range bug found so far came from an Apple card.

- [ ] **Step 1: Record the fixture**

```bash
cd narxnoma-crawler && python -c "
import json, sys; sys.path.insert(0,'.')
from narxnoma.sources.uzum import UzumSource, _search_variables
s = UzumSource()
payload = s._fetch_payload('iPhone', 0)
items = payload['data']['makeSearch']['items'][:20]
payload['data']['makeSearch']['items'] = items
open('tests/fixtures/sources/uzum_apple.json','w',encoding='utf-8').write(
    json.dumps(payload, ensure_ascii=False, indent=1))
print('cards:', len(items))
print('skus :', sum(len(i['catalogCard'].get('skuList') or []) for i in items))
"
```

- [ ] **Step 2: Confirm it actually covers the path**

The fixture is worthless unless it contains SKUs with a `Модель` characteristic **and** a card whose title states a memory range. Check:

```bash
cd narxnoma-crawler && python -c "
import json
p = json.load(open('tests/fixtures/sources/uzum_apple.json',encoding='utf-8'))
n_model = n_range = 0
for it in p['data']['makeSearch']['items']:
    c = it['catalogCard']
    if '/' in (c.get('title') or ''): n_range += 1
    for s in c.get('skuList') or []:
        for cv in s.get('characteristicValues') or []:
            if (cv.get('characteristic') or {}).get('title','').lower().startswith(('модел','model')):
                n_model += 1
print('skus with a Модель characteristic:', n_model)
print('cards whose title carries a range:', n_range)
"
```

Both must be non-zero. If `n_model` is 0, re-record with a different query (`iPhone 17 Pro`, `Apple`) until an Apple reseller card with `Модель` is captured — that is the whole point of the fixture.

- [ ] **Step 3: Write the tests**

Append to `narxnoma-crawler/tests/sources/test_uzum.py`:

```python
APPLE_FIXTURE = (pathlib.Path(__file__).resolve().parents[1]
                 / "fixtures" / "sources" / "uzum_apple.json")


def apple_payload():
    return json.loads(APPLE_FIXTURE.read_text(encoding="utf-8"))


def test_apple_fixture_exists_and_covers_the_model_path():
    """The Samsung fixture has NO SKU carrying a Модель characteristic, so the
    override path -- the one that once lost brand, RAM and storage together,
    and the one most rewritten since -- was only ever tested on constructed
    input. This fixture is what makes it real.
    """
    assert APPLE_FIXTURE.exists()
    payload = apple_payload()
    model_skus = [
        cv for it in payload["data"]["makeSearch"]["items"]
        for sku in (it["catalogCard"].get("skuList") or [])
        for cv in (sku.get("characteristicValues") or [])
        if (cv.get("characteristic") or {}).get("title", "").lower().startswith(
            ("модел", "model"))
    ]
    assert model_skus, "fixture does not exercise the Модель path; re-record it"


def test_no_apple_listing_takes_a_capacity_into_its_model_tokens():
    """The card-range leak, in executable form. It produced
    "Смартфон Apple iPhone 17 256 Pro Max 512 ГБ" -- a product that does not
    exist -- and merged a 17 Pro 256, a 17 Pro Max 256 and a 17 Pro 512 into
    one variant with one headline price.
    """
    capacities = {"32", "64", "128", "256", "512", "1024", "2048"}
    offenders = []
    for lst in parse(apple_payload()):
        tokens = extract_features(lst.name_raw).model_tokens
        if capacities & tokens:
            offenders.append((lst.name_raw, sorted(tokens)))
    assert not offenders, offenders


def test_apple_listings_are_keyable():
    """Apple publishes no RAM, so an iPhone keys on storage and colour alone.
    A card-derived name that loses either is a product silently lost.
    """
    listings = parse(apple_payload())
    keyed = [l for l in listings if variant_key(extract_features(l.name_raw), "dual")]
    assert len(keyed) >= int(len(listings) * 0.7), (
        f"only {len(keyed)} of {len(listings)} Apple listings are keyable")


def test_sibling_skus_on_one_card_do_not_collapse_together():
    """uzum bundles the Pro and the Pro Max, and several capacities, on one
    card. Every SKU on a card must yield a DISTINCT identity, or different
    products pool behind one price -- the incumbent's defect, in our data.
    """
    by_card = {}
    for lst in parse(apple_payload()):
        by_card.setdefault(lst.raw["product_id"], []).append(lst)
    for product_id, listings in by_card.items():
        if len(listings) < 2:
            continue
        keys = [variant_key(extract_features(l.name_raw), "dual") for l in listings]
        keys = [k for k in keys if k is not None]
        assert len(set(keys)) == len(keys), (
            f"card {product_id} collapsed {len(keys)} SKUs into "
            f"{len(set(keys))} identities: {[l.name_raw for l in listings]}")
```

- [ ] **Step 4: Run**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_uzum.py -v`

**If `test_sibling_skus_on_one_card_do_not_collapse_together` fails, do not weaken it.** It is the exact defect Plan 3 spent its investigation on. Report the collapsing card, diagnose it the way that one was diagnosed — replay `_build_name_raw` over the raw payloads and read the characteristics — and fix the cause.

- [ ] **Step 5: Document the recording**

Add a docstring block at the top of the fixture's test section recording the exact query, headers, date, and the live `total` — matching the format the Samsung fixture already uses at the top of `test_uzum.py`.

- [ ] **Step 6: Commit**

```bash
git add narxnoma-crawler/tests/fixtures/sources/uzum_apple.json narxnoma-crawler/tests/sources/test_uzum.py
git commit -m "test(uzum): record an Apple-query fixture covering the Модель path"
```

---

### Task 7: Pass B reaches the whole catalogue, and asks in the right words

**Files:**
- Modify: `narxnoma-crawler/narxnoma/db/schema.sql` (migration 3)
- Modify: `narxnoma-crawler/narxnoma/db/repository.py`
- Modify: `narxnoma-crawler/narxnoma/pipeline/backfill.py`
- Modify: `narxnoma-crawler/narxnoma/cli.py`
- Modify: `docs/parsers/mediapark.md`, `docs/superpowers/specs/2026-07-27-narxnoma-design.md`
- Test: `narxnoma-crawler/tests/pipeline/test_backfill.py`

**Interfaces:**
- Consumes: `variant` table.
- Produces: `variant.last_queried_at timestamptz` column; `repository.variants_to_backfill(conn, limit) -> list[tuple[UUID, VariantKey]]`; `repository.mark_variants_queried(conn, variant_ids)`; `backfill.build_query(key: VariantKey) -> str` (**signature change** — was `build_query(display_name: str)`).

**Read `schema.sql`'s header comment first.** Append migration 3 at the bottom; never edit an existing `CREATE TABLE`.

**Three findings from the Plan 3 branch review, all in this one module.**

1. **Pass B never rotates.** `run_backfill` orders by `store_count DESC, computed_at` and takes 200. But `recompute_variant_prices` sets `computed_at = now()` for every row in a single statement, so **all 1,388 rows share one identical timestamp** — measured: 1 distinct value, 0.000s spread. The tiebreak does nothing, the same 200 best-covered variants are queried every cycle forever, and **the other ~1,188 are never reached by mediapark at all**. `backfill.py`'s docstring claims the opposite.

2. **It reads the current cycle, not the previous one.** The docstring, the design spec and Plan 3 Task 6 all say "previous, deliberately", because feeding it this cycle's clustering output "would make the pipeline cyclic". `cycle` runs `cluster → backfill` in one connection, so it reads what clustering just wrote. **Resolve this by amending the docs, not the code:** the harm the rule guarded against does not exist — Pass B writes offers and attaches nothing, so there is no cycle — and reading the current list gets a new phone its mediapark offer four hours sooner. What is not acceptable is a spec asserting a property the code does not have.

3. **`build_query` consumes a presentation string.** It takes `display_name` and strips `"Смартфон "` and `" ГБ"` back off — parsing a rendering to recover the key it was rendered from. Adding `" (eSIM)"` to `display_name` silently put that marker into mediapark queries against a **ranking** endpoint. Measured: 46 eSIM variants carry it, 0 currently inside the 200-query window, so there is no live damage — but the next display change alters crawl behaviour again, silently. Build the query from the **key**.

- [ ] **Step 1: Write the failing tests**

Append to `narxnoma-crawler/tests/pipeline/test_backfill.py`:

```python
from narxnoma.matching import VariantKey

KEY = VariantKey(brand="apple", model_tokens=frozenset({"17", "pro"}), ram_gb=None,
                 storage_gb=256, color="orange", sim_kind="dual")


def test_query_is_built_from_the_key_not_a_rendered_name():
    """build_query took display_name and stripped "Смартфон " and " ГБ" back
    off -- parsing a rendering to recover the key it was rendered from. Adding
    " (eSIM)" to display_name then put that marker into queries against a
    RANKING endpoint, silently changing crawl behaviour from a presentation
    change. The key is the input; the rendering is not.
    """
    assert build_query(KEY) == "Apple iPhone 17 Pro 256 Оранжевый"


def test_an_esim_variant_does_not_leak_a_presentation_marker():
    from dataclasses import replace
    assert "eSIM" not in build_query(replace(KEY, sim_kind="esim_only"))
    assert "(" not in build_query(replace(KEY, sim_kind="esim_only"))


def test_memory_stays_in_the_query():
    """mediapark RANKS rather than filtering with strict AND, so stripping
    terms measurably worsens recall -- docs/parsers/mediapark.md. The memory
    figure and the colour both stay.
    """
    from dataclasses import replace
    q = build_query(replace(KEY, ram_gb=12))
    assert "12/256" in q
    assert "Оранжевый" in q
```

Append to `narxnoma-crawler/tests/pipeline/test_cluster.py` (it already has `db_conn` and `seed_offer`):

```python
def test_backfill_rotates_through_the_whole_catalogue(db_conn):
    """Pass B queried the SAME 200 variants every cycle, forever.

    run_backfill ordered by store_count DESC then computed_at -- but
    recompute_variant_prices sets computed_at = now() for every row in one
    statement, so all 1,388 live rows shared ONE identical timestamp and the
    tiebreak did nothing. ~1,188 variants were never reached by mediapark at
    all, while backfill.py's docstring claimed the whole catalogue was
    covered over successive cycles.
    """
    for i, colour in enumerate(["черный", "белый", "синий", "зеленый", "красный"]):
        seed_offer(db_conn, f"Смартфон Honor X9d 12/256 ГБ, {colour}", f"k{i}")
    cluster_offers(db_conn, identities_for(db_conn))

    first = repo.variants_to_backfill(db_conn, limit=2)
    assert len(first) == 2
    repo.mark_variants_queried(db_conn, [vid for vid, _ in first])

    second = repo.variants_to_backfill(db_conn, limit=2)
    assert not ({v for v, _ in first} & {v for v, _ in second}), (
        "a variant queried this cycle must not be queried again before the "
        "rest of the catalogue has had a turn")


def test_a_fully_swept_catalogue_starts_over(db_conn):
    seed_offer(db_conn, "Смартфон Honor X9d 12/256 ГБ, черный", "only")
    cluster_offers(db_conn, identities_for(db_conn))
    got = repo.variants_to_backfill(db_conn, limit=5)
    repo.mark_variants_queried(db_conn, [vid for vid, _ in got])
    assert repo.variants_to_backfill(db_conn, limit=5), (
        "once every variant has been queried, the oldest must come round again")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && export NARXNOMA_TEST_DSN="postgresql://narxnoma@127.0.0.1:55432/narxnoma_test" && python -m pytest tests/pipeline/test_backfill.py tests/pipeline/test_cluster.py -v`
Expected: FAIL — `build_query` takes a string; `variants_to_backfill` does not exist.

- [ ] **Step 3: Append migration 3 to `schema.sql`**

```sql
-- ---------------------------------------------------------------------------
-- Migration 3: a real rotation cursor for Pass B.
--
-- run_backfill previously ordered by variant_price.computed_at, which
-- recompute_variant_prices sets to now() for EVERY row in one statement -- so
-- all rows shared one timestamp, the tiebreak did nothing, and the same 200
-- variants were queried every cycle while the rest were never reached.
-- computed_at belongs to the price rollup and can never serve as a cursor.
-- NULL means never queried, and sorts first.
-- ---------------------------------------------------------------------------

ALTER TABLE variant ADD COLUMN IF NOT EXISTS last_queried_at timestamptz;
CREATE INDEX IF NOT EXISTS variant_backfill_cursor
    ON variant (last_queried_at NULLS FIRST);

INSERT INTO schema_version (version) VALUES (3) ON CONFLICT (version) DO NOTHING;
```

- [ ] **Step 4: Implement the repository accessors**

```python
def variants_to_backfill(conn: psycopg.Connection, limit: int) -> list[tuple[UUID, VariantKey]]:
    """The next `limit` variants due a Pass B query, least recently asked first.

    NULLS FIRST means a brand-new variant is asked about immediately. Returns
    KEYS, not display names: the query is built from identity, never from a
    rendering (see backfill.build_query).
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, brand, model_tokens, ram_gb, storage_gb, color, sim_kind
              FROM variant
             ORDER BY last_queried_at ASC NULLS FIRST, id
             LIMIT %s
        """, (limit,))
        return [
            (vid, VariantKey(brand=brand, model_tokens=frozenset(tokens), ram_gb=ram,
                             storage_gb=storage, color=color, sim_kind=sim))
            for vid, brand, tokens, ram, storage, color, sim in cur.fetchall()
        ]


def mark_variants_queried(conn: psycopg.Connection, variant_ids: list[UUID]) -> None:
    """Advance the rotation cursor. Called for every variant ASKED ABOUT,
    including misses -- a variant mediapark does not stock must still take its
    turn, or the rotation stalls on it forever."""
    if not variant_ids:
        return
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE variant SET last_queried_at = now() WHERE id = ANY(%s)",
                (variant_ids,))
```

- [ ] **Step 5: Rewrite `build_query` to take a key**

```python
def build_query(key: VariantKey) -> str:
    """What to ask mediapark for, built from the IDENTITY.

    Kept nearly verbatim, including the memory figure and the colour word:
    unlike every other source here, mediapark RANKS rather than filtering with
    strict AND, so stripping terms measurably worsens recall -- see
    docs/parsers/mediapark.md.

    It takes the KEY rather than display_name because the previous version
    parsed a rendering to recover the identity it was rendered from, stripping
    "Смартфон " and " ГБ" back off. That made a presentation change into a
    crawl change: adding " (eSIM)" to display_name put that marker straight
    into queries against a ranking endpoint.
    """
    brand = BRAND_LABELS.get(key.brand, key.brand.capitalize())
    model = " ".join(_token_label(t) for t in ordered_model_tokens(key.model_tokens))
    memory = f"{key.ram_gb}/{key.storage_gb}" if key.ram_gb else str(key.storage_gb)
    colour = _COLOR_RU.get(key.color, key.color.capitalize())
    return " ".join(p for p in (brand, model, memory, colour) if p)
```

Import `BRAND_LABELS`, `_COLOR_RU`, `_token_label` and `ordered_model_tokens` from `narxnoma.matching.keys`. If any are private, export them properly rather than reaching past the underscore — a second consumer means they are part of the interface now.

- [ ] **Step 6: Wire the rotation into `cli.run_backfill`**

```python
def run_backfill(conn) -> int:
    """Query every search-only source for variants the catalogue already has,
    rotating through the whole catalogue over successive cycles."""
    ids = repository.store_ids(conn)
    written = 0
    due = repository.variants_to_backfill(conn, DEFAULT_MAX_QUERIES)

    for source in SOURCES.values():
        if source.can_sweep or source.slug not in ids:
            continue
        result = backfill_search_only_sources(conn, source, ids[source.slug], due)
        logging.info("backfill %-10s queried=%d matched=%d offers=%d",
                     source.slug, result.queried, result.variants_matched,
                     result.offers_written)
        written += result.offers_written

    # Advance the cursor for everything ASKED ABOUT, hits and misses alike, or
    # the rotation stalls forever on a variant mediapark does not stock.
    repository.mark_variants_queried(conn, [vid for vid, _ in due])
    return written
```

Update `backfill_search_only_sources` so `variants` is a sequence of `(variant_id, VariantKey)` and it calls `build_query(key)`.

- [ ] **Step 7: Run to verify pass**

Run: `cd narxnoma-crawler && python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Prove the rotation live over two cycles**

```bash
cd narxnoma-crawler && export NARXNOMA_DSN="postgresql://narxnoma@127.0.0.1:55432/narxnoma"
python -m narxnoma.cli cluster
python -c "
import psycopg
with psycopg.connect('postgresql://narxnoma@127.0.0.1:55432/narxnoma') as c, c.cursor() as cur:
    cur.execute('SELECT count(*), count(last_queried_at) FROM variant')
    print('variants / already queried:', cur.fetchone())
"
```

Run `run_backfill` twice and confirm the second call returns a **disjoint** set of variant ids from the first. Report both counts and the overlap (which must be 0).

- [ ] **Step 9: Correct the documentation**

- `docs/parsers/mediapark.md`: record that queries are built from the key.
- `backfill.py`'s module docstring: **delete** the "reads the previous cycle" paragraph and replace it with what the code does and why the cyclic concern does not apply (Pass B writes offers and attaches nothing).
- The design spec's Pass B section: same correction.

- [ ] **Step 10: Commit**

```bash
git add narxnoma-crawler/narxnoma/ narxnoma-crawler/tests/ docs/
git commit -m "fix(backfill): rotate through the whole catalogue and query by key"
```

---

### Task 8: Make the live contract tests actually run

**Files:**
- Modify: `narxnoma-crawler/tests/sources/test_contract_live.py`
- Create: `narxnoma-crawler/docs/running-live-tests.md` **or** a section in `docs/deployment/owner-checklist.md`
- Modify: `narxnoma-crawler/pyproject.toml` (marker documentation only)

**Interfaces:**
- Consumes: the existing 8 `@pytest.mark.live` tests.
- Produces: a `live` CLI entry point or documented command, plus a scheduling instruction.

**Why.** Recorded fixtures are single snapshots. They catch field renames, type flips, nesting changes and unit changes — and they have, repeatedly. They **cannot** catch pagination-semantics changes, category renumbering, duplicate `source_key`s across pages, or any brand outside the one recorded query. The 8 `live` tests are the only counterweight, and they are currently **deselected by default and scheduled nowhere**, which means they have never run on a schedule in this project's life.

Two of this project's sources have already shipped URL patterns that 404'd, caught only by a human opening a browser.

- [ ] **Step 1: Verify they still pass today**

Run: `cd narxnoma-crawler && python -m pytest -m live -v`
Expected: 8 tests. **Record which pass and which fail.** A failure here is live information about a retailer, not a broken test — diagnose it, correct `docs/parsers/<source>.md`, and fix the client before continuing.

- [ ] **Step 2: Add a documented command**

Append to `docs/deployment/owner-checklist.md` a section reading:

```markdown
## Weekly: run the live contract tests

Recorded fixtures are snapshots. They catch a retailer renaming a field or
changing a type — and they have, several times. They cannot catch a retailer
changing pagination semantics, renumbering categories, or reusing a
source_key across pages. The `live` tests are the only check that does, and
they hit the real sites, so they are deselected from the ordinary suite.

Run them once a week:

    cd narxnoma-crawler
    python -m pytest -m live -v

A failure is information about a retailer, not a broken test. Fix the client,
correct `docs/parsers/<source>.md` in the same commit, and re-record the
fixture if the response shape changed.
```

- [ ] **Step 3: Schedule it**

On the server, add to the crontab alongside the cycle:

```
# Live retailer contract tests, Mondays 06:00. Output mailed on failure.
0 6 * * 1 cd /srv/narxnoma/narxnoma-crawler && /srv/narxnoma/.venv/bin/python -m pytest -m live -q
```

Record in the owner checklist that this is **not** part of `cycle` and must not be — it makes real requests and a failure must not abort a harvest.

- [ ] **Step 4: Add a test that the marker is still wired**

```python
def test_live_tests_are_deselected_by_default_but_still_collected():
    """If `live` stopped being a registered marker, these tests would either
    error on every ordinary run or silently vanish. Both have happened to
    marker-based suites; pin it."""
    import subprocess, sys
    out = subprocess.run([sys.executable, "-m", "pytest", "-m", "live",
                          "--collect-only", "-q"],
                         capture_output=True, text=True, cwd=".")
    assert "8 tests collected" in out.stdout or "8/" in out.stdout, out.stdout
```

Adjust the expected count if Task 6 added a live test.

- [ ] **Step 5: Commit**

```bash
git add narxnoma-crawler/tests/ docs/deployment/owner-checklist.md
git commit -m "docs: schedule the live contract tests weekly"
```

---

## Self-Review

**Spec coverage.** Plan 2b's scope was fixed by the deferred-items list in `.superpowers/sdd/progress.md` plus the four open findings from the Plan 3 branch review. Mapping:

| Deferred item | Task |
|---|---|
| Hoist the 6×-duplicated pagination loop | 1, 2 |
| Per-page error handling / retry | 1, 2 |
| texnomart category filter | 3 |
| `brand_queries` as a crawl frontier | 4 |
| `pg_try_advisory_lock` single-instance guard | 5 |
| Apple-query uzum fixture | 6 |
| Pass B never rotates (review, Important 1) | 7 |
| Pass B previous-vs-current cycle (review, Important 2) | 7 |
| `build_query` takes a presentation string (review, Minor 1) | 7 |
| Schedule the live contract tests weekly | 8 |

**Deliberately NOT in this plan, with reasons:**

- **Marketing prose leaking into identity** (review, Important 3 — 11 confirmed split offer pools). It belongs to the uzum name-building code, not the crawler's transport layer, and a first attempt at a value-based rule immediately misclassified Infinix 60, Honor 200 and Motorola 60, which are *real model numbers*. Same lesson as `_SKU_MIN_LEN`: the populations overlap in value as well as length. It needs its own measurement against the golden corpus and its own plan. **This is the largest known correctness gap left in the project.**
- **`uzum_spread` is called by nothing** (review, Minor 2). It is a read-only display helper; Plan 4 either consumes it or deletes it. Deciding here would be guessing at Plan 4's needs.
- **`_memory_from_title`'s weak plausibility test** (review, Minor 3). Low impact — downstream extraction declines the figure anyway — and it sits in the same uzum name-building code as Important 3, so it should be fixed alongside it.
- **`MAX_UNRESOLVED_RATE`.** An owner decision, not an engineering one.

**Type consistency.** `paginate` is defined in Task 1 and consumed in Tasks 2 and 3 with the same signature. `build_query` changes signature in Task 7 and has exactly one caller, `backfill_search_only_sources`, updated in the same task. `variants_to_backfill` returns `(UUID, VariantKey)` and `run_backfill` unpacks it as `(vid, _)` consistently. `VariantKey` field names match `narxnoma/matching/keys.py`.

**Ordering.** Task 1 precedes Task 2 because the helper must exist. Task 3 uses `paginate` and so follows Task 2. Tasks 4–8 are independent of each other and of 1–3, and may be reordered freely — Task 6 is the one worth pulling forward if uzum work is planned, since it is the least fixture-covered code in the project.

## Follow-on plans

- **Plan 2c — uzum name building.** Marketing prose leaking into identity (11 measured split pools), `_memory_from_title`'s plausibility floor, and the "1 ТБ" → `1` model-token artefact. Needs its own corpus measurement.
- **Plan 4 — web.** Next.js against the Narxnoma design, reading `variant`, `variant_price` and `offer`. Must not lead with `max_price`, which honestly includes a genuinely mis-priced 30,000,000 alifshop listing.
