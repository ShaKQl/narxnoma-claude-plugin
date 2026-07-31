"""Shared vocabulary for every retailer client."""
import logging
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, runtime_checkable

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
    slug: str
    can_sweep: bool

    def sweep(self) -> Iterator[Listing]:
        """Every phone the retailer will show us, without a target list."""

    def search(self, query: str) -> Iterator[Listing]:
        """Listings matching a query. Used for sources that cannot be swept."""
