"""Stage 3: offers become canonical products — or are refused, with a reason.

This is the whole competitive thesis. Everything else in this project is
plumbing around the rule implemented here:

    an offer is attached to a canonical product only when exactly one product
    can possibly be the right one.

The incumbent pools colour variants together, so on 23% of its multi-store
pages the headline price belongs to a different colour than the page's own
title — worst measured case 9.3% understated. That is not a bug in their
matcher; it is what happens when an ambiguous offer gets attached anyway
because attaching produces a fuller-looking catalogue. We refuse instead, and
count the refusals, because a wrong price is worse than a missing one.
"""
import logging
from dataclasses import dataclass, field

from narxnoma.db import repository as default_repo
from narxnoma.matching import resolve_partial
from narxnoma.pipeline.extract import OfferIdentity, identify

logger = logging.getLogger(__name__)


@dataclass
class ClusterResult:
    attached: int = 0
    created_variants: int = 0
    unresolved: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def _note(self, reason: str) -> None:
        self.reasons[reason] = self.reasons.get(reason, 0) + 1


# Reasons are deliberately coarse and stable, so their counts mean something
# when tracked over time. The specifics go in the row itself.
REASON_AMBIGUOUS = "ambiguous: partial key matches several variants"
REASON_NO_CANDIDATE = "no candidate: partial key matches no existing variant"
REASON_NO_IDENTITY = "no identity: name yields neither a full nor a usable partial key"
REASON_MEMORY_IN_MODEL = "bad identity: a memory figure reached the model tokens"

# No phone is named "256". A capacity among the model tokens is always a
# parsing failure, and the variant it would mint is a product that does not
# exist -- so genuinely different SKUs pool behind one headline price, which
# is the incumbent's defect reproduced in our own data.
#
# This is a BACKSTOP, not a repair. It was written for a uzum leak (a card's
# storage RANGE reaching identity, so a 17 Pro 256, a 17 Pro Max 256 and a
# 17 Pro 512 became one variant priced at 18,349,000 against a median of
# 31,000,000) which is now fixed in the client. It stays because the failure
# is silent by construction -- a wrong variant is indistinguishable from a
# right one without reading the offers behind it -- and any source can
# reintroduce the same shape.
_CAPACITIES_GB = frozenset({"32", "64", "128", "256", "512", "1024", "2048"})


def is_wellformed(key) -> bool:
    """Could this key describe a real product at all?

    Applied at every point a key can reach the catalogue, not just at
    creation: an offer may also arrive at a malformed variant by PARTIAL
    resolution, and one already sitting on a malformed variant agrees with it
    perfectly, so the drift check alone would keep it there forever. Checking
    once, in three places, is what makes the refusal actually hold.
    """
    return not (_CAPACITIES_GB & set(key.model_tokens))


def _has_usable_partial(identity: OfferIdentity) -> bool:
    """Enough to be worth resolving against existing variants.

    Brand and storage are the floor. Without them a partial key is compatible
    with far too much, and "resolves to exactly one" would start being true by
    accident rather than by evidence.
    """
    p = identity.partial
    return bool(p.brand and p.storage_gb and p.model_tokens)


def detach_drifted_offers(conn, repo=default_repo) -> int:
    """Detach offers whose stored variant contradicts what their name now says.

    Clustering only ever loads offers with `variant_id IS NULL`, so an offer
    attached in an earlier cycle is never reconsidered. That is correct while
    `name_raw` is stable — and wrong the moment a source fix changes it, which
    is precisely when the catalogue is most likely to be wrong. The uzum
    card-range repair rewrote 217 stored names; without this the offers behind
    them would have sat on their old, incorrect variants indefinitely, and
    nothing in the system would have reported it.

    Detaching is all this does. The offer returns to the normal pass and is
    re-attached, or refused, by the same rules as any other — so a fix can only
    move an offer to the right product or park it, never invent a new outcome.

    Two cases are deliberately distinguished:

    - a **full** key that maps to a different variant is a plain contradiction;
    - a **partial** key is judged by compatibility instead, because an offer
      attached by partial resolution never had a full key to compare. Tearing
      those down unconditionally would churn every partial attachment through
      detach and re-attach on every single cycle.
    """
    known = repo.load_variant_keys(conn)
    by_id = {vid: key for key, vid in known.items()}

    drifted = []
    for row in repo.load_attached_offers(conn):
        identity = identify(row)
        stored_key = by_id.get(row["variant_id"])
        if stored_key is None:
            continue
        if not is_wellformed(stored_key):
            # Nothing can legitimately sit here -- see is_wellformed. Without
            # this, an offer whose name still produces the malformed key
            # AGREES with its variant and is kept indefinitely.
            drifted.append(identity.offer_id)
        elif identity.key is not None:
            if identity.key != stored_key:
                drifted.append(identity.offer_id)
        elif resolve_partial(identity.partial, [stored_key]) is None:
            drifted.append(identity.offer_id)

    for offer_id in drifted:
        repo.detach_offer(conn, offer_id)
    if drifted:
        logger.info("detached %d offers whose name no longer matches their variant",
                    len(drifted))
    return len(drifted)


def cluster_offers(conn, identities, repo=default_repo) -> ClusterResult:
    """Attach offers to canonical variants, refusing anything ambiguous.

    Full keys are processed before partials, in the same pass, because a
    partial must be able to resolve against a variant this very run created —
    otherwise the first offer of a new phone would park itself as unresolvable
    against a catalogue that was about to contain it.
    """
    result = ClusterResult()
    identities = list(identities)

    known = repo.load_variant_keys(conn)
    before = len(known)

    # --- pass one: complete identities define the catalogue -----------------
    partials = []
    for identity in identities:
        if identity.key is None:
            partials.append(identity)
            continue
        if not is_wellformed(identity.key):
            # See REASON_MEMORY_IN_MODEL: refusing costs one offer, while
            # cataloguing it corrupts a product other offers then join.
            repo.record_unresolved(conn, identity.offer_id, REASON_MEMORY_IN_MODEL)
            result.unresolved += 1
            result._note(REASON_MEMORY_IN_MODEL)
            continue
        variant_id = known.get(identity.key)
        if variant_id is None:
            variant_id = repo.upsert_variant(conn, identity.key)
            known[identity.key] = variant_id
        repo.attach_offer_to_variant(conn, identity.offer_id, variant_id)
        result.attached += 1

    result.created_variants = len(known) - before

    # --- pass two: incomplete identities resolve against it -----------------
    candidates = [k for k in known if is_wellformed(k)]
    for identity in partials:
        if not _has_usable_partial(identity):
            repo.record_unresolved(conn, identity.offer_id, REASON_NO_IDENTITY)
            result.unresolved += 1
            result._note(REASON_NO_IDENTITY)
            continue

        match = resolve_partial(identity.partial, candidates)
        if match is not None:
            repo.attach_offer_to_variant(conn, identity.offer_id, known[match])
            result.attached += 1
            continue

        # resolve_partial returns None for both zero and two-or-more. The
        # difference matters to whoever reads the quality report: zero is a
        # catalogue gap, several is a genuinely under-specified listing.
        compatible = [known[k] for k in candidates
                      if resolve_partial(identity.partial, [k]) is not None]
        reason = REASON_AMBIGUOUS if len(compatible) > 1 else REASON_NO_CANDIDATE
        repo.record_unresolved(conn, identity.offer_id, reason, compatible)
        result.unresolved += 1
        result._note(reason)

    logger.info(
        "clustered: %d attached, %d variants created, %d unresolved",
        result.attached, result.created_variants, result.unresolved)
    return result
