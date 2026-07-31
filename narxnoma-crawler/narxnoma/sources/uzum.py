"""uzum.uz client: anonymous-token GraphQL, per-brand sweep.

uzum is the largest marketplace in Uzbekistan and the only source here with
auth, per-variant (SKU) pricing, and a failure mode that looks like success.
Read docs/parsers/uzum.md in full before touching this file -- every trap
below has a section there with the live evidence behind it.

Auth (docs/parsers/uzum.md section 1): `graphql.uzum.uz` returns a bare 401
without a Bearer token. The token is minted anonymously via
`POST id.uzum.uz/api/auth/token` with an empty JSON body -- no account, no
captcha. The response is **204 No Content**: the token is not in the body,
it arrives as a `Set-Cookie: access_token=<JWT>` header, which is why
`_mint_token` talks to `requests` directly instead of `get_json`/`post_json`
(those call `response.json()` unconditionally and would raise
`NonJsonResponse` on the empty 204 body). Exactly two headers are required
to mint -- `Accept-Language` (any value) and `Referer` (must be on the
uzum.uz origin); `Origin` is NOT required, the opposite of what you would
guess. TTL is 6 hours (`exp` in the JWT payload); `_get_token` caches the
token at module (process) level and refreshes ~5 minutes before `exp`.

The GraphQL endpoint itself (docs/parsers/uzum.md section 2) needs four
headers -- `Authorization`, `Content-Type`, `apollographql-client-name:
web-customers`, `x-iid: <any UUID>` -- or it returns a bare 401. Drop only
`apollographql-client-name` or `x-iid` and it instead returns **200 OK**
with `data: null` and an `errors` array: checking `response.status_code`
alone reports success on a request that returned nothing.
`UzumSource._fetch` inspects `payload.get("errors")` explicitly and raises
`UzumGraphQLError` when present, so a broken sweep call is loud rather than
silently looking like "no more items for this brand." `parse()` itself
never raises for this -- it logs and returns `[]`, so a caller handed one
already-fetched payload gets an empty result rather than a crash.

**Card price is not product price** (section 5): a card bundles several
models and every storage tier under one `minSellPrice`. Every listing here
is built from a `skuList[]` entry using `sellPrice` -- never `minSellPrice`,
never `fullPrice` (a struck-through pre-discount figure, often fantasy).

**Off-category noise** (section 3): relevance search mixes in cases,
chargers and vacuum cleaners. `parse()` filters client-side on
`catalogCard.category.id` in `PHONE_CATEGORY_IDS` (15271 Android, 15272
iPhone) -- folded into `parse()` itself, not left to a separate crawl-policy
step, because `search()` hits the exact same noisy relevance endpoint as
`sweep()` and both need it.

**Pagination caps at offset ~= 1000** (section 3): beyond that `items` comes
back empty regardless of `limit`, so `sweep()` goes brand by brand (see
`narxnoma.sources.brand_queries.BRAND_QUERIES`) rather than attempting one
unbounded query -- the Android smartphone category alone runs to thousands
of multi-seller listings.

**name_raw** (sections 5a/5b/7): uzum hands back no single product-name
field. `_build_name_raw` takes the card title only up to its first comma
(marketing blurb after that), lets the SKU's own `Модель` characteristic
override it when present, and -- when the SKU states its own memory --
strips memory figures out of the spec before combining, so the card's
overall storage *range* never masquerades as this SKU's specific tier (the
exact bug that once reported 2,672,010 for a phone whose true price was
3,068,010; see `test_known_product_name_raw_strips_the_cards_other_memory_tiers`
in tests/sources/test_uzum.py for the live instance of this trap in the
recorded fixture). Characteristic keys are a typo minefield (`Память`,
`памяять`, `Памяьт:`, `Xotirasi`, and -- observed live in this recording --
`xotra`, a typo the doc's own `startswith("xotira")` sample does not catch;
`_char_kind` here classifies by the shorter `startswith("xot")` prefix
instead), so keys are classified loosely by prefix, never matched exactly.
`_parse_sku` also puts the untouched card title and the SKU's full
`characteristicValues` list into `Listing.raw`, so a later clustering stage
can redo this name-building better without re-crawling.

**Two deliberate inversions of docs/parsers/uzum.md** (project decision, not
a doc bug -- see the task-10 brief): that document was written for a
target-driven matcher hunting one specific phone, where an eSIM-only
variant or a zero-stock SKU is noise to screen out. This client is an
*aggregator* cataloguing every real offer, so both instructions invert:

- eSIM-only variants (section 6) are **kept**, not dropped -- they are a
  legitimate, separate product at a genuinely different price. Whatever SIM
  characteristic exists survives into `raw["characteristic_values"]`
  verbatim for a later clustering stage to classify.
- Zero-stock SKUs (`availableAmount <= 0`, section 4) are **kept**, not
  dropped -- recorded with `availability="OUT_OF_STOCK"` rather than
  discarded. Hiding an out-of-stock offer is a presentation decision that
  belongs downstream, not a reason to lose the observation.
"""
import base64
import json
import logging
import re
import time
import uuid
from typing import Iterator

import requests

from narxnoma.config import load_settings
from narxnoma.matching.normalize import normalize
from narxnoma.sources.base import Listing, coerce_price, try_build_listing
from narxnoma.sources.brand_queries import BRAND_QUERIES
from narxnoma.sources.http import pause, polite_session, post_json

logger = logging.getLogger(__name__)

AUTH_URL = "https://id.uzum.uz/api/auth/token"
GRAPHQL_URL = "https://graphql.uzum.uz/"
PRODUCT_URL = "https://uzum.uz/ru/product/{product_id}?skuId={sku_id}"

# 15271 = Смартфоны Android, 15272 = Смартфоны Apple iPhone (iOS) -- see
# docs/parsers/uzum.md section 3. Relevance search mixes in cases, chargers
# and (genuinely) vacuum cleaners; this is the only usable signal to drop them.
PHONE_CATEGORY_IDS = frozenset({15271, 15272})

PAGE_LIMIT = 72
# Pagination caps at offset ~= 1000 -- beyond that `items` is always empty
# regardless of limit (docs/parsers/uzum.md section 3). sweep() stops each
# brand here even if the response claims a larger `total`.
OFFSET_CAP = 1000

# Refresh the cached token 5 minutes before its 6-hour JWT `exp`, per
# docs/parsers/uzum.md section 1.
_TOKEN_REFRESH_MARGIN_SECONDS = 300

# Cached at module (process) level -- "mint a token once (cached for the
# process, refreshed ~5 minutes before its 6-hour exp)" per the task brief.
# Every UzumSource instance in this process shares one token.
_token_cache: dict = {"token": None, "iid": None, "exp": 0}

SEARCH_QUERY = """
query getMakeSearch($q: MakeSearchQueryInput!) {
  makeSearch(query: $q) {
    total
    items {
      catalogCard {
        __typename
        productId
        title
        category { id title }
        ... on SkuGroupCard {
          skuList {
            id
            sellPrice
            fullPrice
            availableAmount
            characteristicValues { title characteristic { title } }
          }
        }
      }
    }
  }
}
"""


class UzumGraphQLError(RuntimeError):
    """Raised by the live fetch path (never by parse()) when a 200 OK
    GraphQL response carries an `errors` key -- docs/parsers/uzum.md
    section 2's headline trap: this looks like success by status code alone.
    """


def _decode_jwt_exp(token: str) -> int:
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    return int(claims["exp"])


def _mint_token() -> tuple[str, str]:
    """POST id.uzum.uz/api/auth/token and pull the bearer token out of the
    Set-Cookie header (the 204 response body is empty -- see module
    docstring). Bypasses get_json/post_json on purpose: both call
    response.json() unconditionally and would raise NonJsonResponse on this
    endpoint's empty body.
    """
    settings = load_settings()
    iid = str(uuid.uuid4())
    session = requests.Session()
    try:
        response = session.post(
            AUTH_URL,
            headers={
                "Accept": "*/*",
                "Accept-Language": "ru-RU",       # required
                "Content-Type": "application/json",
                "Referer": "https://uzum.uz/",    # required, must be uzum.uz origin
                "User-Agent": settings.user_agent,
                "x-iid": iid,
            },
            json={},
            timeout=(settings.connect_timeout, settings.read_timeout),
        )
        response.raise_for_status()
    finally:
        pause()  # a real retailer call either way -- see http.get_json/post_json
    token = next((c.value for c in session.cookies if c.name == "access_token"), None)
    if not token:
        raise RuntimeError("uzum auth: no access_token cookie in the mint response")
    return token, iid


def _get_token() -> tuple[str, str]:
    """The process-cached bearer token and install id, minting or refreshing
    as needed. See module docstring for the caching contract.
    """
    if _token_cache["token"] and time.time() < _token_cache["exp"] - _TOKEN_REFRESH_MARGIN_SECONDS:
        return _token_cache["token"], _token_cache["iid"]
    token, iid = _mint_token()
    exp = _decode_jwt_exp(token)
    _token_cache.update(token=token, iid=iid, exp=exp)
    return token, iid


def _char_kind(key: str) -> str:
    """Classify a characteristic key loosely by prefix -- never match
    exactly. docs/parsers/uzum.md section 7 catalogues the typo minefield
    (`Память`, `память`, `ПАМЯТЬ`, `Памят:`, `Память:`, `Памяьт:`,
    `памяять`, `Объем памяти`, `Xotirasi`); this recording additionally
    turned up `xotra` (missing the final `i`) and `Xotira:` (trailing
    colon, stripped by `normalize` anyway) -- neither matches the doc's own
    `startswith("xotira")` sample, which is why this uses the shorter
    `startswith("xot")` instead.
    """
    k = normalize(key)
    if k.startswith("памя") or k.startswith("xot") or "объем памяти" in k:
        return "memory"
    if k.startswith("модел") or k.startswith("model"):
        return "model"
    if "sim" in k or "сим" in k:
        return "sim"
    if k.startswith("цвет") or k.startswith("rang"):
        return "color"
    return "other"


def _characteristics(sku: dict) -> dict[str, str]:
    """First model/memory/color value seen for this SKU, classified via
    _char_kind. SIM values are not extracted here -- name_raw never carries
    them (see module docstring); they survive into Listing.raw verbatim as
    part of the full characteristicValues list instead.
    """
    found = {"model": "", "memory": "", "color": ""}
    for cv in sku.get("characteristicValues") or []:
        if not isinstance(cv, dict):
            continue
        key = ((cv.get("characteristic") or {}).get("title")) or ""
        kind = _char_kind(key)
        if kind in found and not found[kind]:
            value = cv.get("title")
            if value:
                found[kind] = str(value)
    return found


# docs/parsers/uzum.md section 5b, verbatim: when a SKU states its own
# memory, strip memory figures out of the card-derived spec before
# combining, or the card's overall storage range masquerades as this SKU's
# specific tier.
_MEMORY_PAIR_RE = re.compile(
    r"(?<![a-zа-я])\d{1,4}\s*(?:gb|гб|tb|тб)?\s*[/\\+|]\s*"
    r"\d{1,4}\s*(?:gb|гб|tb|тб)?",
    re.I,
)
_MEMORY_SINGLE_RE = re.compile(
    r"(?<![a-zа-я\d])\d{1,4}\s*(?:gb|гб|tb|тб)\b",
    re.I,
)


def _strip_memory(text: str) -> str:
    text = _MEMORY_PAIR_RE.sub(" ", text)
    text = _MEMORY_SINGLE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _build_name_raw(card_title: str | None, model_v: str, mem_v: str, color_v: str) -> str:
    """Best-effort faithful name. docs/parsers/uzum.md sections 5a/5b:

    - take the card title only up to its first comma (the marketing blurb
      lives after it);
    - let the SKU's own Модель characteristic override that head entirely
      when present;
    - when the SKU states its own memory, strip memory figures out of
      whichever spec string is in play before combining.

    When the SKU's Модель already stands in for the head, the card's first
    word (almost always a brand/product-type token) is prefixed back on --
    a bare Модель value like "17 Pro Max 256 GB" carries no brand context
    of its own. When the head is used directly it already starts with that
    same token, so nothing is prefixed and duplicated.
    """
    head = (card_title or "").split(",")[0].strip()
    first_word = head.split()[0] if head else ""

    if model_v:
        spec = model_v
        prefix = first_word
    else:
        spec = head
        prefix = ""

    if mem_v:
        spec = _strip_memory(spec)

    parts = [p for p in (prefix, spec, mem_v, color_v) if p]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _items(payload: dict) -> list[dict]:
    return (((payload or {}).get("data") or {}).get("makeSearch") or {}).get("items") or []


def _parse_sku(card: dict, sku: dict) -> Listing | None:
    if not isinstance(sku, dict):
        return None
    sku_id = sku.get("id")
    if sku_id is None:
        return None
    product_id = card.get("productId")
    if product_id is None:
        return None

    price = coerce_price(sku.get("sellPrice"))  # never fullPrice -- see module docstring
    chars = _characteristics(sku)
    name_raw = _build_name_raw(card.get("title"), chars["model"], chars["memory"], chars["color"])

    try:
        amount = int(sku.get("availableAmount") or 0)
    except (TypeError, ValueError):
        amount = 0
    # Deliberate inversion of docs/parsers/uzum.md section 4 -- see module
    # docstring. Kept, not dropped; OUT_OF_STOCK rather than discarded.
    availability = "IN_STOCK" if amount > 0 else "OUT_OF_STOCK"

    return try_build_listing(
        store_slug="uzum",
        source_key=str(sku_id),
        name_raw=name_raw,
        price=price,
        url=PRODUCT_URL.format(product_id=product_id, sku_id=sku_id),
        availability=availability,
        raw={
            "card_title": card.get("title"),      # untouched, for re-derivation downstream
            "category_id": (card.get("category") or {}).get("id"),
            "product_id": product_id,
            "sku_id": sku_id,
            "characteristic_values": sku.get("characteristicValues") or [],
            "available_amount": sku.get("availableAmount"),
            "full_price": sku.get("fullPrice"),
        },
    )


def parse(payload: dict) -> list[Listing]:
    """Turn one raw makeSearch response into Listings. Pure function, no I/O.

    Unlike idea/beemarket, category filtering happens inside parse() itself
    rather than as a separate crawl-policy step in sweep() -- search() hits
    the same noisy relevance endpoint sweep() does, so both need the filter
    and there is no separate category-scoped endpoint to lean on instead.

    Handles the `errors`-key failure mode (docs/parsers/uzum.md section 2)
    by returning [] rather than raising -- the live fetch path
    (UzumSource._fetch) is what raises on this, so a broken sweep call is
    loud instead of silently looking like an empty brand.
    """
    if (payload or {}).get("errors"):
        logger.warning("uzum: graphql payload carries an errors key, returning no listings: %s",
                        payload.get("errors"))
        return []

    listings: list[Listing] = []
    for item in _items(payload):
        card = (item or {}).get("catalogCard") or {}
        category_id = (card.get("category") or {}).get("id")
        if category_id not in PHONE_CATEGORY_IDS:
            continue
        for sku in card.get("skuList") or []:
            lst = _parse_sku(card, sku)
            if lst is not None:
                listings.append(lst)
    return listings


def _search_variables(text: str, offset: int) -> dict:
    return {
        "q": {
            "text": text,
            "showAdultContent": "TRUE",
            "filters": [],
            "sort": "BY_RELEVANCE_DESC",
            "pagination": {"offset": offset, "limit": PAGE_LIMIT},
        }
    }


class UzumSource:
    slug = "uzum"
    can_sweep = True

    def __init__(self) -> None:
        self._session = None

    def _get_session(self):
        if self._session is None:
            self._session = polite_session(
                referer="https://uzum.uz/",
                origin="https://uzum.uz",
                extra_headers={
                    "Accept-Language": "ru-RU",
                    "apollographql-client-name": "web-customers",  # required
                    "apollographql-client-version": "1.63.2",
                    "city-id": "1",
                },
            )
        return self._session

    def _fetch_payload(self, text: str, offset: int) -> dict:
        """POST one makeSearch page, raising on the errors-key failure mode
        (docs/parsers/uzum.md section 2) rather than treating it as an
        empty/end-of-results page -- see module docstring for why.
        """
        session = self._get_session()
        token, iid = _get_token()
        payload = post_json(
            session,
            GRAPHQL_URL,
            headers={"Authorization": f"Bearer {token}", "x-iid": iid},
            json={"query": SEARCH_QUERY, "variables": _search_variables(text, offset)},
        )
        errors = (payload or {}).get("errors")
        if errors:
            raise UzumGraphQLError(f"uzum graphql errors for {text!r}@{offset}: {errors!r}")
        return payload

    def _walk(self, text: str) -> Iterator[Listing]:
        offset = 0
        while offset <= OFFSET_CAP:
            payload = self._fetch_payload(text, offset)
            raw_items = _items(payload)
            if not raw_items:
                break
            yield from parse(payload)
            offset += PAGE_LIMIT

    def sweep(self) -> Iterator[Listing]:
        """Every phone uzum returns across a fixed list of brand queries,
        paginating each until its items run out or offset hits OFFSET_CAP
        (see module docstring for why offset can't just run unbounded).
        Deduplicated by source_key (SKU id) across brand queries, since the
        same SKU can surface under more than one brand query.
        """
        seen: set[str] = set()
        for brand in BRAND_QUERIES:
            # TODO(plan-3): no per-page error handling -- a transient
            # failure on any one page loses the rest of this brand's sweep.
            # Same gap as olcha/texnomart/idea/beemarket/alifshop; deferred
            # until partial-progress recovery is built once.
            for listing in self._walk(brand):
                if listing.source_key in seen:
                    continue
                seen.add(listing.source_key)
                yield listing

    def search(self, query: str) -> Iterator[Listing]:
        payload = self._fetch_payload(query, 0)
        yield from parse(payload)
