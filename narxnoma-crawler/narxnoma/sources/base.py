"""Shared vocabulary for every retailer client."""
import logging
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, runtime_checkable

from narxnoma.sources.http import pause

logger = logging.getLogger(__name__)

# A price outside this range is a unit bug, not a bargain. alifshop reports
# tiyin (1/100 SUM); forgetting the divisor lands 100x high.
PRICE_MIN = 100_000
PRICE_MAX = 100_000_000

AVAILABILITY = ("IN_STOCK", "OUT_OF_STOCK", "UNKNOWN")


def is_plausible_price(price: int | None) -> bool:
    return price is not None and PRICE_MIN <= price <= PRICE_MAX


def coerce_price(value: Any) -> int | None:
    """Coerce a retailer's raw price field to an int, or None if unusable.

    Retailer price fields are untyped in practice: olcha returns
    `discount_price` as an int but `total_price` as a string; mediapark
    returns `price` as a string; alifshop returns tiyin. Assuming any of
    these is already an int is how a whole source silently yields nothing --
    every client must run its price fields through this before building a
    Listing.

    `None`, `""`, `0`, `"0"`, and any non-numeric string all return `None`.
    A negative value also returns `None`: a negative price is meaningless
    and the plausibility fences in `Listing` would reject it anyway.
    """
    if value in (None, "", 0, "0"):
        return None
    try:
        price = int(float(value))
    except (TypeError, ValueError):
        return None
    if price < 0:
        return None
    return price


@dataclass(frozen=True)
class Listing:
    """One offer as the retailer stated it. Nothing is inferred here."""

    store_slug: str
    source_key: str
    name_raw: str
    price: int
    url: str
    availability: str = "UNKNOWN"
    image_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        for name in ("store_slug", "source_key", "name_raw", "url"):
            if not getattr(self, name):
                raise ValueError(f"Listing.{name} must not be empty")
        if not is_plausible_price(self.price):
            raise ValueError(f"implausible price {self.price!r} for {self.source_key!r}")
        if self.availability not in AVAILABILITY:
            raise ValueError(f"unknown availability {self.availability!r}")


def try_build_listing(**kwargs) -> Listing | None:
    """Build a Listing, or return None and log why.

    One malformed item must never kill a sweep of several hundred, and all
    seven clients must drop them the same way -- so the handling lives here
    rather than being re-implemented per client.
    """
    source_key = kwargs.get("source_key") or "<no source_key>"
    try:
        return Listing(**kwargs)
    except ValueError as exc:
        logger.warning("dropping malformed listing %r: %s", source_key, exc)
        return None
    except TypeError as exc:
        # Wrong or missing keyword arguments is a bug in the calling client,
        # not bad retailer data -- log it loudly so it doesn't hide next to
        # routine drop-and-count warnings, but still don't kill the sweep.
        logger.error("dropping listing %r built with bad arguments: %s", source_key, exc)
        return None


@runtime_checkable
class Source(Protocol):
    """One retailer.

    CALLER CONTRACT: check `can_sweep` before calling `sweep()`. A source that
    cannot browse a catalogue raises from `sweep()` rather than yielding
    nothing -- returning an empty iterator would let a caller that forgot this
    check record a perfectly successful harvest of zero listings, which is
    indistinguishable from a retailer whose catalogue really is empty. Failing
    loudly is the point.
    """

    slug: str

    #: False when the retailer exposes no catalogue browse (mediapark, whose
    #: only endpoint is a no-pagination autocomplete). Such a source is reached
    #: through `search()` alone.
    can_sweep: bool

    def sweep(self) -> Iterator[Listing]:
        """Every phone the retailer will show us, without a target list.

        Raises NotImplementedError when `can_sweep` is False.
        """

    def search(self, query: str) -> Iterator[Listing]:
        """Listings matching a query. Used for sources that cannot be swept."""


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
    `next_page(payload, page) -> int | None`. **next_page is the only thing
    that ends the sweep.** A page that parses to nothing does NOT: its items
    may simply have been dropped by the price fence or a category filter, and
    stopping there would lose every following page. A client whose end signal
    really is an empty payload (uzum, paginating by offset with no last_page)
    expresses that in its own next_page.

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

        # NOT `if not listings: return`. A page whose items were all dropped
        # by the price fence or a category filter would end the sweep and lose
        # every following page. next_page decides; see the docstring.
        yield from parse_page(payload)

        following = next_page(payload, page)
        if following is None:
            return
        page = following
