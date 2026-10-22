"""What a research run produces, and the JSON that lets a workbook be rebuilt without fetching."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Target:
    """One product the user wants researched."""

    name: str
    category: str | None = None  # a narxnoma category slug, or None when unknown
    our_price: float | None = None  # in `currency`; None when the user has no price for it
    currency: str = "UZS"
    note: str = ""
    extra: dict = field(default_factory=dict)  # any other column of the input, kept as-is


@dataclass
class Offer:
    """One accepted listing for one target. Nothing is reduced here: the workbook keeps them all."""

    target: str
    market: str
    listing_name: str
    price: int
    url: str
    availability: str = "UNKNOWN"
    score: int = 0
    name_delta: str = ""
    source_key: str | None = None


@dataclass
class Research:
    targets: list[Target]
    offers: list[Offer]
    markets: list[str]  # fixed column order
    fetched_at: dict[str, str] = field(default_factory=dict)  # market -> ISO time of its catalogue
    notes: dict[str, str] = field(default_factory=dict)  # market -> why it has no data
    run_at: str = ""
    usd_rate: float | None = None
    usd_rate_date: str = ""
    title: str = "Market research"

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8"
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "Research":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            targets=[Target(**t) for t in d["targets"]],
            offers=[Offer(**o) for o in d["offers"]],
            markets=d["markets"],
            fetched_at=d.get("fetched_at", {}),
            notes=d.get("notes", {}),
            run_at=d.get("run_at", ""),
            usd_rate=d.get("usd_rate"),
            usd_rate_date=d.get("usd_rate_date", ""),
            title=d.get("title", "Market research"),
        )
