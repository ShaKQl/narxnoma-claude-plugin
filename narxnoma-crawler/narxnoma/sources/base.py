"""Shared vocabulary for every retailer client."""
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, runtime_checkable

# A price outside this range is a unit bug, not a bargain. alifshop reports
# tiyin (1/100 SUM); forgetting the divisor lands 100x high.
PRICE_MIN = 100_000
PRICE_MAX = 100_000_000

AVAILABILITY = ("IN_STOCK", "OUT_OF_STOCK", "UNKNOWN")


def is_plausible_price(price: int | None) -> bool:
    return price is not None and PRICE_MIN <= price <= PRICE_MAX


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


@runtime_checkable
class Source(Protocol):
    slug: str
    can_sweep: bool

    def sweep(self) -> Iterator[Listing]:
        """Every phone the retailer will show us, without a target list."""

    def search(self, query: str) -> Iterator[Listing]:
        """Listings matching a query. Used for sources that cannot be swept."""
