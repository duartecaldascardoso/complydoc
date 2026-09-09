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
        "family",
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


def test_every_provider_is_in_the_comparison(config):
    """All of them, not a chosen few. A provider left off the chart is a
    provider nobody can compare against."""
    compared = {m.provider for m in config.pricing.usable_models}
    offered = {m.provider for m in config.pricing.models if m.supports_vision and m.is_priced}
    assert compared == offered


def test_each_provider_contributes_a_spread_of_prices(config):
    """Four models at the same price answer nothing.

    The comparison exists to show the trade being made, so each provider's
    models are picked across its price range — Anthropic contributing haiku,
    sonnet, opus and fable rather than four cuts of opus.
    """
    import collections

    wanted = config.pricing.compare.per_provider
    prices = collections.defaultdict(list)
    for model in config.pricing.usable_models:
        prices[model.provider].append(model.input_per_mtok_usd or 0.0)

    for provider, found in prices.items():
        assert len(found) <= wanted, provider
        assert len(set(found)) == len(found), f"{provider} repeats a price point"
        if len(found) >= 3:
            cheapest, dearest = min(found), max(found)
            assert dearest >= cheapest * 2, f"{provider} spans too narrow a range: {found}"


def test_the_anthropic_ladder_is_the_shape_it_should_be(config):
    """The worked example: the tiers, not four versions of one tier."""
    from complydoc.cost.price_table import family_of

    picked = [m for m in config.pricing.usable_models if m.provider == "anthropic"]
    families = {family_of(m.id.rsplit("/", 1)[-1]) for m in picked}
    assert len(families) == len(picked), "one model per family"
    assert len(picked) == config.pricing.compare.per_provider


def test_the_comparison_never_lists_one_model_twice(config):
    """A curated entry may prefix the provider where the catalogue does not."""
    bare = [m.id.rsplit("/", 1)[-1] for m in config.pricing.usable_models]
    assert len(bare) == len(set(bare)), sorted(bare)


def test_topped_up_models_are_still_marked_imported(config):
    """Being in the comparison does not make a price verified."""
    topped = [m for m in config.pricing.usable_models if m.price_source == "imported"]
    assert topped, "the curated list does not reach three per provider on its own"
    assert all(m.last_verified is None for m in topped)


def test_an_imported_price_is_not_reported_as_a_stale_verification(config):
    """It was never claimed to be verified, so it cannot have gone stale.

    Warning once per model would bury the run's real limitations under a dozen
    copies of what the provenance entry says once.
    """
    from complydoc.config.loader import check_staleness

    warnings = check_staleness(config.pricing)
    imported = {m.id for m in config.pricing.models if m.price_source == "imported"}
    assert not [w for w in warnings if w.entry.removeprefix("model ") in imported]


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
