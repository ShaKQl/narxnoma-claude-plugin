"""The unresolved rate is only a signal if something watches it."""
import pytest

from narxnoma.db import repository as repo
from narxnoma.pipeline.aggregate import recompute_variant_prices
from narxnoma.pipeline.cluster import cluster_offers
from narxnoma.pipeline.extract import identify
from narxnoma.pipeline.quality import (
    MAX_UNRESOLVED_RATE,
    QualityReport,
    quality_report,
    render,
)
from narxnoma.sources.base import Listing

pytestmark = pytest.mark.db

HONOR = "Смартфон Honor X9d 12/256 ГБ, черный"
COLOURS = ["черный", "белый", "синий", "зеленый", "красный",
           "золотой", "серый", "розовый", "фиолетовый"]


def seed(conn, name, key, store="olcha", price=4_839_000):
    ids = repo.store_ids(conn)
    repo.upsert_offers(conn, ids[store], [Listing(
        store_slug=store, source_key=key, name_raw=name, price=price,
        url=f"https://{store}.uz/{key}", availability="IN_STOCK")])


def run_pipeline(conn):
    cluster_offers(conn, (identify(r) for r in repo.load_unattached_offers(conn)))
    recompute_variant_prices(conn)


def test_counts_attached_and_unresolved(db_conn):
    seed(db_conn, HONOR, "good")
    seed(db_conn, "Смартфон Honor X5d Plus", "vague")  # no memory at all
    run_pipeline(db_conn)

    report = quality_report(db_conn)
    assert report.total_offers == 2
    assert report.attached == 1
    assert report.unresolved == 1
    assert report.variants == 1


def test_unresolved_rate_and_alert_threshold(db_conn):
    # Nine identifiable phones and one that is not: 10% unresolved, over the 5%
    # threshold, so this must alert. Colours vary so each is a distinct variant;
    # storage tiers must stay real, or extract_memory rightly refuses them.
    for i, colour in enumerate(COLOURS):
        seed(db_conn, f"Смартфон Honor X9d 12/256 ГБ, {colour}", f"g{i}")
    seed(db_conn, "Смартфон Honor X5d Plus", "vague")
    run_pipeline(db_conn)

    report = quality_report(db_conn)
    assert report.unresolved_rate == pytest.approx(0.1)
    assert report.is_alerting is True


def test_a_clean_catalogue_does_not_alert(db_conn):
    for i, colour in enumerate(COLOURS[:5]):
        seed(db_conn, f"Смартфон Honor X9d 12/256 ГБ, {colour}", f"g{i}")
    run_pipeline(db_conn)

    report = quality_report(db_conn)
    assert report.unresolved == 0
    assert report.unresolved_rate == 0.0
    assert report.is_alerting is False


def test_reasons_are_ranked(db_conn):
    seed(db_conn, "Смартфон Honor X5d Plus", "v1")
    seed(db_conn, "Смартфон Honor X7e", "v2")
    seed(db_conn, "Смартфон Vivo Y31d 256 ГБ, чёрный", "orphan")
    run_pipeline(db_conn)

    report = quality_report(db_conn)
    assert report.reasons, "reasons must be reported, not just a total"
    assert report.reasons[0][1] >= report.reasons[-1][1], "ranked by count"
    assert sum(n for _, n in report.reasons) == report.unresolved


def test_unresolved_is_broken_down_by_source(db_conn):
    # Which retailer is producing unusable names is the actionable question.
    seed(db_conn, "Смартфон Honor X5d Plus", "a", store="olcha")
    seed(db_conn, "Смартфон Honor X7e", "b", store="idea")
    run_pipeline(db_conn)

    by_store = dict(quality_report(db_conn).unresolved_by_store)
    assert by_store == {"olcha": 1, "idea": 1}


def test_single_offer_variants_are_counted(db_conn):
    # A variant only one retailer stocks has nothing to compare. That is the
    # honest limit of a comparison site, not a defect -- but it must be visible.
    seed(db_conn, HONOR, "solo")
    run_pipeline(db_conn)
    assert quality_report(db_conn).single_offer_variants == 1


def test_a_headline_far_below_the_median_is_surfaced(db_conn):
    # This is the shape of the card-price-versus-SKU-price bug: one listing
    # that is not really this product, dragging the headline down.
    seed(db_conn, HONOR, "a", price=5_000_000)
    seed(db_conn, HONOR, "b", store="idea", price=5_100_000)
    seed(db_conn, HONOR, "c", store="uzum", price=1_000_000)
    run_pipeline(db_conn)

    assert quality_report(db_conn).diverging_variants == 1


def test_render_names_the_alert_and_the_threshold(db_conn):
    seed(db_conn, "Смартфон Honor X5d Plus", "vague")
    run_pipeline(db_conn)

    text = render(quality_report(db_conn))
    assert "ALERT" in text
    assert "unresolved" in text


def test_empty_database_does_not_divide_by_zero(db_conn):
    report = quality_report(db_conn)
    assert report.total_offers == 0
    assert report.unresolved_rate == 0.0
    assert report.is_alerting is False


def test_threshold_is_five_percent():
    # Pinned deliberately: a pipeline that "succeeded" while failing to
    # identify a fifth of its offers has not succeeded.
    assert MAX_UNRESOLVED_RATE == 0.05
    assert QualityReport().is_alerting is False
