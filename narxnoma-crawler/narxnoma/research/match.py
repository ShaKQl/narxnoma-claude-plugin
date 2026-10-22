"""Apply the matching engine to a target list and keep every accepted offer.

The matcher decides identity; this module only runs it at scale. Two choices carry over
from the surveys this was extracted from, because each one was a defect once:

* **Bucket by brand first.** `score_match` hard-rejects on a brand mismatch before anything
  else, so comparing a Samsung target against a store's 400 Apple listings is pure waste. A
  listing whose brand could not be read goes in the `None` bucket and is always considered --
  dropping it would lose every listing whose brand we merely failed to parse.
* **The accept threshold depends on the category.** A phone can score 50 (brand 10 + storage 20
  + RAM 10 + model 15 + colour 5) against ACCEPT_THRESHOLD 30. A television has no storage,
  RAM or identity-colour, so a *perfect* match -- brand plus a bidirectional model-code match
  -- scores exactly 25 and a threshold of 30 empties the category. 25 still demands the brand
  AND the model tokens in both directions, so it is the same identity, not a looser one.
"""

import re
from collections import defaultdict

from narxnoma.matching import ACCEPT_THRESHOLD, extract_features, score_match
from narxnoma.research.model import Offer, Target

NON_PHONE_ACCEPT = 25


def accept_threshold(category: str) -> int:
    return ACCEPT_THRESHOLD if category == "smartphones" else NON_PHONE_ACCEPT


# Words that differ between two listings of the SAME product and carry no identity: the
# category noun, marketing, units, packaging language. Used only for the Name-delta audit
# column, never for matching.
_NOISE = re.compile(
    r"^(?:кондиционер\w*|телевизор\w*|холодильник\w*|морозильник\w*|стиральн\w*|машин\w*|"
    r"смартфон\w*|ноутбук\w*|televizor\w*|konditsioner\w*|muzlatgich\w*|sovutgich\w*|kir|yuvish|"
    r"mashina\w*|автомат|inverter|invertor|инвертор\w*|inv|smart|смарт|android|андроид|tv|тв|"
    r"led|qled|oled|uhd|fhd|hd|4k|8k|btu|вт|kg|кг|л|litr|дюйм\w*|new|новый|воздуха|сплит|"
    r"система|белый|черный|серый|g|dc|full|art|ru|uz|с|и|в|на)$",
    re.I,
)


def name_delta(target: str, matched: str) -> str:
    """Significant words in one name but not the other.

    A non-empty value is NOT an error: the matcher deliberately collapses decorated variants of
    one catalogue code. But `ASW-H12A4/FADR` vs `ASW-H12A4/LR1DI` can be a different indoor unit
    at a different price, and the number alone cannot show it. These are the rows to read.
    """

    def toks(s):
        return {
            t
            for t in re.split(r"[^0-9a-zA-Zа-яА-ЯёЁ]+", (s or "").lower())
            if len(t) > 1 and not _NOISE.match(t)
        }

    a, b = toks(target), toks(matched)
    parts = []
    if a - b:
        parts.append("ours: " + " ".join(sorted(a - b)[:6]))
    if b - a:
        parts.append("theirs: " + " ".join(sorted(b - a)[:6]))
    return " | ".join(parts)


def index_by_brand(listings: list[dict], category: str) -> dict:
    buckets: dict = defaultdict(list)
    for listing in listings:
        feats = extract_features(listing["name_raw"], category)
        buckets[feats.brand].append((listing, feats))
    return buckets


def match_target(
    target: Target, market: str, buckets: dict | None, extra_listings: list[dict] | None = None
) -> list[Offer]:
    """Every accepted offer of one market for one target, cheapest first."""
    if not target.category:
        return []
    tfeat = extract_features(target.name, target.category)
    threshold = accept_threshold(target.category)
    candidates: list = []
    if buckets is not None:
        candidates = list(buckets.get(tfeat.brand, []))
        if tfeat.brand is not None:
            candidates += buckets.get(None, [])
    if extra_listings:
        candidates += [
            (x, extract_features(x["name_raw"], target.category)) for x in extra_listings
        ]

    offers, seen = [], set()
    for listing, cfeat in candidates:
        score = score_match(tfeat, cfeat)
        if score < threshold:
            continue
        ident = (listing.get("source_key"), listing["url"], listing["price"])
        if ident in seen:  # the None bucket can repeat a brand bucket's row
            continue
        seen.add(ident)
        offers.append(
            Offer(
                target=target.name,
                market=market,
                listing_name=listing["name_raw"],
                price=int(listing["price"]),
                url=listing["url"],
                availability=listing.get("availability", "UNKNOWN"),
                score=score,
                name_delta=name_delta(target.name, listing["name_raw"]),
                source_key=listing.get("source_key"),
            )
        )
    offers.sort(key=lambda o: (o.price, -o.score))
    return offers
