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
`UzumSource._fetch_payload` inspects `payload.get("errors")` explicitly and
raises `UzumGraphQLError` when present, so a broken sweep call is loud
rather than silently looking like "no more items for this brand." `parse()`
itself never raises for this -- it logs and returns `[]`, so a caller handed
one already-fetched payload gets an empty result rather than a crash.
`_fetch_payload` also survives a **server-side token revocation**: the cache
refreshes only when the locally decoded `exp` passes, so a token revoked
early arrives as a bare 401 the cache cannot predict. That 401 re-mints once
and retries; a second 401 is a real auth failure and raises.

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
field. `name_raw` is the *only* handle the clustering stage gets on a
product's identity -- a name that loses the brand or the storage figure
cannot be keyed at all, and the offer drops out of the catalogue silently.
`_build_name_raw` therefore has three jobs, and each of them has already
been got wrong once:

- take the card title only up to its first comma (marketing blurb after
  that), and let the SKU's own `Модель` characteristic override it;
- when the head is reduced to a prefix in front of a `Модель` value, keep
  the whole brand-bearing head rather than its first word, after dropping
  a leading `Smartfon`/`Смартфон`/`Telefon`/`Телефон` product-type noun.
  Keeping only the first word turned
  `("Smartfon Samsung Galaxy A16, ...", "A16 8/256")` into
  `"Smartfon A16 Qora"` -- brand, RAM and storage all unrecoverable -- and
  10 of this recording's 20 cards lead with that noun, so it was the common
  case rather than an edge;
- when the SKU states its own memory, strip memory figures out of the
  *card-derived* text before combining, so the card's overall storage
  *range* never masquerades as this SKU's specific tier (the exact bug that
  once reported 2,672,010 for a phone whose true price was 3,068,010; see
  `test_known_product_name_raw_strips_the_cards_other_memory_tiers`).
  Memory stripping is **never** applied to the `Модель` value itself --
  that value is the trustworthy one, and stripping it deleted the very
  figure section 5b exists to preserve.

When neither the SKU's characteristics nor the truncated head yields any
memory at all, the *full* card title is searched for a memory pattern and
the match appended: cards that state memory after the first comma
("Smartfon Samsung Galaxy A16, 4/128 GB, 2 SIM, ...") otherwise produced a
storage-less, unkeyable name from information we were already holding in
`raw["card_title"]`.

Characteristic keys are a typo minefield (`Память`, `памяять`, `Памяьт:`,
`Xotirasi`, `RAM/ROM`, and -- observed live in this recording -- `xotra`, a
typo the doc's own `startswith("xotira")` sample does not catch;
`_char_kind` here classifies by the shorter `startswith("xot")` prefix
instead, and treats a bare `ram`/`rom` token as memory because `normalize`
folds `RAM/ROM` to `ram rom`), so keys are classified loosely, never matched
exactly. `_parse_sku` also puts the untouched card title and the SKU's full
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

# Assumed TTL when the access_token cookie is not a decodable JWT. uzum can
# change the cookie format at any time; a crash inside _decode_jwt_exp would
# kill the entire sweep over a value that is only a refresh optimisation, so
# an undecodable token is treated as short-lived instead.
_TOKEN_FALLBACK_TTL_SECONDS = 3600

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
    """The `exp` claim of the access_token cookie, or a conservative
    fallback expiry if the cookie is not a decodable JWT.

    The expiry is only used to decide *when to refresh*, so it must never be
    able to raise: an opaque or reformatted cookie would otherwise crash
    _get_token and take the whole sweep with it, even though the token
    itself may be perfectly usable.
    """
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
        return int(claims["exp"])
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        logger.warning(
            "uzum: access_token is not a decodable JWT; assuming a %ds TTL",
            _TOKEN_FALLBACK_TTL_SECONDS,
        )
        return int(time.time()) + _TOKEN_FALLBACK_TTL_SECONDS


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


def _invalidate_token() -> None:
    """Force the next _get_token() to mint a fresh token.

    The cache refreshes on the locally decoded `exp`, which cannot see a
    *server-side* revocation: uzum can invalidate a token before its stated
    expiry, and the only signal is a 401 on the next graphql call. See
    UzumSource._fetch_payload.
    """
    _token_cache.update(token=None, iid=None, exp=0)


# `RAM/ROM` is in docs/parsers/uzum.md section 7's own observed-key list, but
# `normalize` folds the slash to a space and hands back `ram rom`, which no
# prefix test in this function recognised -- so the key classified as "other"
# and its memory value was dropped without a trace. Same class of bug as the
# `xotra` typo below. Matched on tokens, not as a substring: `rang` (colour)
# must not be caught by a bare `"ram" in k`.
_MEMORY_KEY_TOKENS = frozenset({"ram", "rom"})


def _char_kind(key: str) -> str:
    """Classify a characteristic key loosely -- never match exactly.
    docs/parsers/uzum.md section 7 catalogues the typo minefield
    (`Память`, `память`, `ПАМЯТЬ`, `Памят:`, `Память:`, `Памяьт:`,
    `памяять`, `Объем памяти`, `Xotirasi`, `RAM/ROM`); this recording
    additionally turned up `xotra` (missing the final `i`) and `Xotira:`
    (trailing colon, stripped by `normalize` anyway) -- neither matches the
    doc's own `startswith("xotira")` sample, which is why this uses the
    shorter `startswith("xot")` instead. Every key in section 7's list is
    exercised by test_char_kind_classifies_every_observed_key.
    """
    k = normalize(key)
    if (
        k.startswith("памя")
        or k.startswith("xot")
        or "объем памяти" in k
        or _MEMORY_KEY_TOKENS & set(k.split())
    ):
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
# The trailing `+` makes the chain greedy across MORE than two figures. A
# card offering three tiers ("Galaxy S25 Edge 12/256/512") otherwise had
# exactly two of them consumed, leaving "512" standing in the head -- where
# the bare-pair scan then read the card's 512 as the capacity and demoted
# the SKU's own 256 to a model token. That is the leak inverted, not fixed.
#
# `-` is in the separator class because uzum sellers write the RAM-ROM pair
# with a hyphen too ("POCO C81 Pro (4-64/4-128)"). The leading
# `(?<![a-zа-я])` still protects catalogue codes: the "0" of "SM-A075F" is
# preceded by a letter, so no chain can start inside one.
_MEMORY_PAIR_RE = re.compile(
    r"(?<![a-zа-я])\d{1,4}\s*(?:gb|гб|tb|тб)?"
    r"(?:\s*[/\\+|-]\s*\d{1,4}\s*(?:gb|гб|tb|тб)?)+",
    re.I,
)
_MEMORY_SINGLE_RE = re.compile(
    r"(?<![a-zа-я\d])\d{1,4}\s*(?:gb|гб|tb|тб)\b",
    re.I,
)


# Residue left behind by the two substitutions above. Stripping "(8+8)/128
# GB" out of "Smartfon Oppo A5i Pro (8+8)/128 GB" leaves "( )/" hanging off
# the end -- SKU 6931382 in the recorded fixture parsed to
# "Smartfon Oppo A5i Pro ( )/ 8/128 Binafsha".
_EMPTY_BRACKETS_RE = re.compile(r"[(\[{]\s*[)\]}]")
# A separator with no word character immediately to its left is orphaned.
# Deliberately one-sided: a separator that IS preceded by a word character
# may be a real model marker ("Note 14 Pro+"), and must survive.
_ORPHAN_SEPARATOR_RE = re.compile(r"(?<!\w)[/\\|+]+")

# Anything smaller is a RAM figure or a screen size, not a storage tier --
# used to reject "4/6" out of "4/6/128Gb" and "2 SIM" when recovering memory
# from a full card title.
_MIN_PLAUSIBLE_STORAGE_GB = 32

# RAM sizes retailers actually sell. Used to tell a RAM/storage SPEC from a
# storage RANGE: "4/128" and "12/256" pair a RAM figure with a capacity and
# identify one product, while "128/256" and "256/512" pair two capacities
# and are the card's range across the SKUs it bundles -- they identify
# nothing, and recovering one puts a coin-toss capacity on a real product.
_PLAUSIBLE_RAM_GB = frozenset({1, 2, 3, 4, 6, 8, 10, 12, 16, 18, 24})


def _is_storage_range(figures: list[int]) -> bool:
    """True when every figure is a capacity, so this states a range."""
    return len(figures) > 2 or (
        len(figures) == 2 and min(figures) not in _PLAUSIBLE_RAM_GB
    )


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" ,;:-/\\|")


def _strip_memory(text: str) -> str:
    """Remove memory figures from CARD-DERIVED text only.

    Never call this on a SKU's own `Модель` or memory value:
    docs/parsers/uzum.md section 5b strips memory from the *card title*
    precisely because the SKU's own value is the trustworthy one. Applying
    it to `Модель` deleted the figure the whole section exists to preserve
    ("A16 8/256" -> "A16").
    """
    text = _MEMORY_PAIR_RE.sub(" ", text)
    text = _MEMORY_SINGLE_RE.sub(" ", text)
    text = _EMPTY_BRACKETS_RE.sub(" ", text)
    text = _ORPHAN_SEPARATOR_RE.sub(" ", text)
    return _collapse(text)


def _has_memory(text: str) -> bool:
    return bool(_MEMORY_PAIR_RE.search(text) or _MEMORY_SINGLE_RE.search(text))


# A bare capacity, with neither a unit nor a partner figure: `Память: "128"`,
# `Модель: "17 Pro 256"`. Restricted to real capacities so a model number
# ("17", "Note 14") is never mistaken for one.
_BARE_MEMORY_RE = re.compile(r"(?<![a-zа-я\d])(?:32|64|128|256|512|1024|2048)(?!\d)", re.I)


def _states_memory(text: str) -> bool:
    """Does this text state a memory figure IN ANY SHAPE?

    Distinct from `_has_memory`, which only recognises a separated pair or a
    unit-bearing figure. Both of this module's section-5b decisions ask
    "did the SKU tell us its own memory?", and for a bare figure `_has_memory`
    answered no -- so the card's overall RANGE was substituted for a figure
    the SKU had stated perfectly clearly:

    - the recovery gate appended the range beside the SKU's own capacity,
      turning `Память: "128"` on a "64/128/256 ГБ" card into
      `... 12 128 64/128 Алый`, where 64 becomes a MODEL token;
    - section 5b's strip gate never fired, so `Модель: "17 Pro 256"` on an
      "IPhone 17 Pro / Max 256/512 GB" card kept the card's range and keyed
      as 512 GB, merging three different SKUs onto one variant.

    A failure to RECOGNISE a stated figure is not a licence to substitute
    the card's range for it.
    """
    return bool(_has_memory(text) or _BARE_MEMORY_RE.search(text))


def _memory_from_title(title: str) -> str:
    """First plausible memory figure anywhere in the FULL card title.

    Last resort for cards that state memory after the first comma
    ("Smartfon Samsung Galaxy A16, 4/128 GB, 2 SIM, ...") while the SKU has
    no memory characteristic of its own. Without it those SKUs produce a
    name with neither RAM nor storage, which the clustering stage cannot
    key -- and the figure was sitting in raw["card_title"] all along.
    """
    saw_range = False
    for match in _MEMORY_PAIR_RE.finditer(title):
        figures = [int(f) for f in re.findall(r"\d{1,4}", match.group(0))]
        if not figures or max(figures) < _MIN_PLAUSIBLE_STORAGE_GB:
            continue
        # A range identifies nothing -- see _is_storage_range. Taking one
        # would put a coin-toss capacity on a real product, which is the
        # single defect this project exists to avoid; a name with no
        # capacity is refused by the clustering stage instead.
        if _is_storage_range(figures):
            saw_range = True
            continue
        return _collapse(match.group(0))
    if saw_range:
        # The single-figure fallback below would otherwise pick one HALF of
        # the range it just refused -- "128/256GB" yields "256GB" -- which is
        # the same coin toss with the evidence hidden.
        return ""
    match = _MEMORY_SINGLE_RE.search(title)
    return _collapse(match.group(0)) if match else ""


# "Smartfon Samsung Galaxy A16", "Смартфон Samsung ...", "Telefon ...".
# Harmless while the whole head is the name (it is what the retailer wrote),
# but fatal once the head is cut down to a prefix: it is a product-type noun
# carrying no identity, and keeping it in place of the brand is what made
# ("Smartfon Samsung Galaxy A16, ...", "A16 8/256") parse to
# "Smartfon A16 Qora".
_LEAD_NOUN_RE = re.compile(r"^(?:smartfon|смартфон|telefon|телефон)\w*\b[\s:,-]*", re.I)

_SUBTOKEN_RE = re.compile(r"[^0-9A-Za-zЀ-ӿ]+")


def _prefix_for_model(head: str, model_v: str) -> str:
    """The brand-bearing part of the card head, to sit in front of a Модель.

    A bare Модель value ("17 Pro Max 256 GB", "A16 8/256") carries no brand
    of its own, so the head has to supply it. The head is kept only UP TO
    the first word the Модель value already states, so
    "IPhone 17 Pro/Pro Max" + "17 Pro Max 256 GB" yields "IPhone" while
    "Samsung Galaxy A16" + "A16 8/256" keeps "Samsung Galaxy".

    Truncating rather than filtering is what stops a card lending a SKU the
    model it is NOT. uzum bundles siblings on one card -- "IPhone 17 Pro /
    Max 256/512 GB" carries both the Pro and the Pro Max -- and dropping
    only the words the Модель repeats left "Max" standing in the prefix of
    the plain "17 Pro 256" SKU, which then keyed as a Pro Max. Once a head
    word belongs to the model, everything after it is model territory and
    the Модель value owns it: it is the per-SKU field, and the head is the
    shared one.
    """
    model_tokens = {t for t in _SUBTOKEN_RE.split(model_v.lower()) if t}
    kept = []
    for word in _LEAD_NOUN_RE.sub("", head).split():
        subtokens = [t for t in _SUBTOKEN_RE.split(word.lower()) if t]
        if subtokens and all(t in model_tokens for t in subtokens):
            break
        kept.append(word)
    return " ".join(kept)


def _build_name_raw(card_title: str | None, model_v: str, mem_v: str, color_v: str) -> str:
    """Best-effort faithful name -- and the clustering stage's ONLY handle on
    this product's identity. See the module docstring for the three rules
    and the bug each of them fixes.
    """
    full_title = (card_title or "").strip()
    head = full_title.split(",")[0].strip()

    if model_v:
        # The SKU's own Модель wins outright and is never rewritten.
        spec = model_v
        prefix = _prefix_for_model(head, model_v)
        if mem_v or _states_memory(model_v):
            # ...but the card head in front of it must not smuggle the
            # card's overall storage RANGE in beside it (section 5b).
            prefix = _strip_memory(prefix)
    else:
        prefix = ""
        spec = _strip_memory(head) if mem_v else head

    name = _collapse(" ".join(p for p in (prefix, spec, mem_v) if p))

    # Last resort, and ONLY when this SKU stated no memory of its own. The
    # card title past the first comma is shared across every SKU the card
    # bundles, so reaching into it for a capacity the SKU already supplied
    # replaces a specific figure with a range -- see _states_memory.
    if not _states_memory(name) and not (mem_v or _states_memory(model_v)):
        recovered = _memory_from_title(full_title)
        if recovered:
            name = _collapse(f"{name} {recovered}")
    return _collapse(f"{name} {color_v}" if color_v else name)


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
    (UzumSource._fetch_payload) is what raises on this, so a broken sweep
    call is loud instead of silently looking like an empty brand.
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

    def _post_page(self, text: str, offset: int) -> dict:
        session = self._get_session()
        token, iid = _get_token()
        return post_json(
            session,
            GRAPHQL_URL,
            headers={"Authorization": f"Bearer {token}", "x-iid": iid},
            json={"query": SEARCH_QUERY, "variables": _search_variables(text, offset)},
        )

    def _fetch_payload(self, text: str, offset: int) -> dict:
        """POST one makeSearch page, raising on the errors-key failure mode
        (docs/parsers/uzum.md section 2) rather than treating it as an
        empty/end-of-results page -- see module docstring for why.

        A 401 re-mints the token once and retries. The cached token is only
        refreshed when its locally decoded `exp` passes, which cannot see a
        server-side revocation: without this, a token revoked in the middle
        of a brand sweep propagated an HTTPError all the way out of sweep()
        and ended the run, even though minting a new one takes one request.
        A second 401 is a genuine auth failure and is left to raise.
        """
        try:
            payload = self._post_page(text, offset)
        except requests.HTTPError as exc:
            if getattr(exc.response, "status_code", None) != 401:
                raise
            logger.warning(
                "uzum: 401 for %r@%d -- re-minting the token and retrying once", text, offset
            )
            _invalidate_token()
            payload = self._post_page(text, offset)
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
