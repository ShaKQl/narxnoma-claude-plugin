"""Retailer clients. Each implements the Source protocol in base.py."""
from narxnoma.sources.alifshop import AlifshopSource
from narxnoma.sources.asaxiy import AsaxiySource
from narxnoma.sources.beemarket import BeemarketSource
from narxnoma.sources.idea import IdeaSource
from narxnoma.sources.mediapark import MediaparkSource
from narxnoma.sources.olcha import OlchaSource
from narxnoma.sources.texnomart import TexnomartSource
from narxnoma.sources.uzum import UzumSource

SOURCES = {s.slug: s for s in (
    OlchaSource(), TexnomartSource(), IdeaSource(), BeemarketSource(),
    AlifshopSource(), MediaparkSource(), UzumSource(), AsaxiySource(),
)}
