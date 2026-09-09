"""The vendored price table.

`pricing.yaml` is the curated layer — a handful of models someone checked
against the provider's own page. This is the long tail behind it, so that naming
a model works without anyone having hand-written an entry for it first.

The line these tests hold is that an import is never presented as a verification.
"""

from __future__ import annotations

import json

import pytest

from complydoc.audit import run_audit
from complydoc.cost.estimator import estimate_document, resolve_models
from complydoc.cost.price_table import TABLE_PATH, imported_models, table_provenance
from complydoc.ingest.base import IngestOptions
from complydoc.ingest.registry import load_document
from tests.helpers import FIXTURES


def test_the_table_ships_with_the_package():
    assert TABLE_PATH.exists()
    source, imported, total = table_provenance()
    assert source and imported and total > 100


def test_the_table_carries_only_what_is_used():
    """A vendored file grows without anyone deciding to grow it."""
    table = json.loads(TABLE_PATH.read_text())
    allowed = {
        "provider",
        "display_name",
        "input_per_mtok_usd",
        "output_per_mtok_usd",
        "batch_input_per_mtok_usd",
        "accepts_image",
        "accepts_pdf",
        "release_date",
        "max_input_tokens",
    }
    for entry in table["models"].values():
        assert set(entry) <= allowed
    assert TABLE_PATH.stat().st_size < 400_000, "the table should stay small enough to vendor"


def test_every_imported_price_says_it_was_imported():
    for model in imported_models():
        assert model.price_source == "imported"
        assert model.last_verified is None, "an import is not a verification"
        assert model.imported_on is not None


def test_imported_models_are_not_compared_by_default(config):
    """Three hundred models on a chart answers nobody's question."""
    default = config.pricing.usable_models
    assert 0 < len(default) < 30
    assert all(m.price_source == "verified" for m in default)


def test_a_curated_price_is_never_replaced_by_an_imported_one(config):
    curated = {m.id for m in config.pricing.models if m.price_source == "verified"}
    assert curated, "the shipped config carries verified entries"
    for model_id in curated:
        assert config.pricing.model_by_id(model_id).price_source == "verified"


def test_a_model_from_the_table_can_be_named(config):
    """The whole point of the breadth: --model reaches it."""
    chosen = resolve_models(config.pricing, ["gpt-4.1-mini"])
    assert len(chosen) == 1
    assert chosen[0].price_source == "imported"
    assert chosen[0].is_priced


def test_naming_a_model_nobody_has_still_fails(config):
    from complydoc.cost.estimator import UnknownModelError

    with pytest.raises(UnknownModelError):
        resolve_models(config.pricing, ["not-a-model-anyone-ships"])


def test_a_batch_price_is_used_where_published(config):
    document = load_document(FIXTURES / "native_text.pdf", IngestOptions())
    models = resolve_models(config.pricing, ["gpt-4.1-mini"])
    estimate = estimate_document(document, config.pricing, models=models)
    priced = estimate.models[0]
    assert priced.batch_input_per_mtok_usd
    assert priced.batch_text_path_input_usd
    assert priced.batch_text_path_input_usd < priced.text_path_input_usd


def test_a_batch_price_is_never_invented(config):
    """Anthropic runs a batch API; this table does not publish its price.

    The customary half price is not written in, because a discount nobody can
    check does not belong in a budget.
    """
    document = load_document(FIXTURES / "native_text.pdf", IngestOptions())
    models = resolve_models(config.pricing, ["claude-opus-5"])
    priced = estimate_document(document, config.pricing, models=models).models[0]
    assert priced.batch_input_per_mtok_usd is None
    assert priced.batch_text_path_input_usd is None


def test_using_an_imported_price_is_disclosed(config):
    report = run_audit(FIXTURES, config, ("cost",), ocr=False, select_models=["gpt-4.1-mini"])
    entry = next(x for x in report.limitations if x.area == "Price provenance")
    assert entry.severity == "important"
    assert entry.affected, "it names the models it is talking about"
    assert "third-party" in entry.statement


def test_a_verified_only_run_carries_no_provenance_caveat(config):
    report = run_audit(FIXTURES, config, ("cost",), ocr=False, select_models=["claude-opus-5"])
    assert not [x for x in report.limitations if x.area == "Price provenance"]


def test_the_catalogue_knows_when_models_were_released():
    """Recency is the whole reason for preferring this catalogue.

    Without it the only ordering available is alphabetical, which puts a
    two-year-old model above the one released this month.
    """
    import datetime as dt

    from complydoc.cost.price_table import imported_models, released_on

    dated = [d for d in (released_on(m.id) for m in imported_models()) if d]
    assert len(dated) > 50, "most of the catalogue should carry a release date"
    assert max(dated) > dt.date.today() - dt.timedelta(days=365), "and it should be current"


def test_a_text_only_model_is_not_given_a_vision_price():
    """The catalogue says what each model accepts, so nothing is assumed."""
    from complydoc.cost.price_table import imported_models

    text_only = [m for m in imported_models() if not m.supports_vision]
    assert text_only, "the catalogue carries text-only models"
    assert all(m.vision_formula is None for m in text_only)
