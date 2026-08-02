"""Is the matcher working? The unresolved rate only means something if watched.

`unresolved_offer` is a quality signal, not a dumping ground. Its count rising
means the matcher is failing to identify things it should — and because we
deliberately refuse rather than guess, that failure is silent by construction.
Nothing else in the system would notice.
"""
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Above this, something is wrong with the matcher rather than with the data.
# Measured baseline on a real five-source catalogue is ~21%, dominated by
# retailer catalogue-parent rows with no memory stated -- see the ledger. This
# threshold is what the plan specifies; treat a breach as "go and read the
# unresolved rows", not as a number to tune away.
MAX_UNRESOLVED_RATE = 0.05

# A variant whose cheapest offer sits far below its median is the shape of the
# card-price-versus-SKU-price bug: one listing that is not really this product,
# dragging the headline down. Worth surfacing permanently.
MIN_DIVERGENCE = 0.12


@dataclass
class QualityReport:
    total_offers: int = 0
    attached: int = 0
    unresolved: int = 0
    variants: int = 0
    single_offer_variants: int = 0
    diverging_variants: int = 0
    reasons: list[tuple[str, int]] = field(default_factory=list)
    unresolved_by_store: list[tuple[str, int]] = field(default_factory=list)

    @property
    def unresolved_rate(self) -> float:
        return self.unresolved / self.total_offers if self.total_offers else 0.0

    @property
    def is_alerting(self) -> bool:
        return self.unresolved_rate > MAX_UNRESOLVED_RATE


def quality_report(conn) -> QualityReport:
    report = QualityReport()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT count(*), count(*) FILTER (WHERE variant_id IS NOT NULL)
              FROM offer
        """)
        report.total_offers, report.attached = cur.fetchone()

        cur.execute("SELECT count(*) FROM unresolved_offer")
        report.unresolved = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM variant")
        report.variants = cur.fetchone()[0]

        cur.execute("""
            SELECT reason, count(*) FROM unresolved_offer
             GROUP BY reason ORDER BY count(*) DESC
        """)
        report.reasons = cur.fetchall()

        cur.execute("""
            SELECT s.slug, count(*) FROM unresolved_offer u
              JOIN offer o ON o.id = u.offer_id
              JOIN store s ON s.id = o.store_id
             GROUP BY s.slug ORDER BY count(*) DESC
        """)
        report.unresolved_by_store = cur.fetchall()

        # A variant nobody else stocks has nothing to compare, which is the
        # honest limit of a comparison site rather than a defect.
        cur.execute("SELECT count(*) FROM variant_price WHERE offer_count = 1")
        report.single_offer_variants = cur.fetchone()[0]

        cur.execute("""
            SELECT count(*) FROM variant_price
             WHERE min_price IS NOT NULL AND median_price IS NOT NULL
               AND median_price > 0
               AND (median_price - min_price)::numeric / median_price > %s
        """, (MIN_DIVERGENCE,))
        report.diverging_variants = cur.fetchone()[0]

    logger.info("quality: %d/%d offers attached, %.1f%% unresolved",
                report.attached, report.total_offers, report.unresolved_rate * 100)
    return report


def render(report: QualityReport) -> str:
    lines = [
        f"offers            {report.total_offers:>8,}",
        f"  attached        {report.attached:>8,}",
        f"  unresolved      {report.unresolved:>8,}   "
        f"({report.unresolved_rate * 100:.1f}%, alert above "
        f"{MAX_UNRESOLVED_RATE * 100:.0f}%)",
        f"canonical variants{report.variants:>8,}",
        f"  single-offer    {report.single_offer_variants:>8,}   "
        f"(nothing to compare -- an honest limit, not a defect)",
        f"  min far below median{report.diverging_variants:>5,}   "
        f"(>{MIN_DIVERGENCE * 100:.0f}%: the shape of a wrong match dragging a headline down)",
    ]
    if report.reasons:
        lines.append("\nunresolved by reason:")
        lines += [f"  {n:>7,}  {reason}" for reason, n in report.reasons]
    if report.unresolved_by_store:
        lines.append("\nunresolved by source:")
        lines += [f"  {n:>7,}  {slug}" for slug, n in report.unresolved_by_store]
    if report.is_alerting:
        lines.append(
            f"\n*** ALERT: {report.unresolved_rate * 100:.1f}% unresolved. "
            f"Read the rows before changing the threshold. ***")
    return "\n".join(lines)
