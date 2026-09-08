"""Cost estimation: tokenizer, per-provider vision formulas and extrapolation."""

from __future__ import annotations

import pytest

from complydoc.config.schema import (
    FlatVisionFormula,
    ResolutionPreset,
    TiledVisionFormula,
    TokenizerSpec,
    WidthHeightVisionFormula,
)
from complydoc.cost.estimator import estimate_document, estimate_folder
from complydoc.cost.tokenizer import available_encodings, count_tokens
from complydoc.cost.vision import RenderedSize, rendered_size, vision_tokens

A4_PT = (595.28, 841.89)


# --- tokenizer ------------------------------------------------------------


def test_encodings_are_vendored_so_no_download_is_needed():
    assert len(available_encodings()) >= 2


def test_a_real_tokenizer_is_used_not_a_character_heuristic():
    spec = TokenizerSpec(encoding="o200k_base", fidelity="exact")
    count = count_tokens("Invoice total 5,100.00 due 26/03/2026", spec)
    assert count.fidelity == "exact"
    assert count.is_measured
    assert 5 < count.tokens < 30


def test_empty_text_costs_nothing():
    spec = TokenizerSpec(encoding="o200k_base", fidelity="exact")
    assert count_tokens("", spec).tokens == 0


def test_an_unavailable_encoding_degrades_loudly_rather_than_silently():
    spec = TokenizerSpec(encoding="not-a-real-encoding", fidelity="exact")
    count = count_tokens("some text here", spec)
    assert count.fidelity == "estimated"
    assert not count.is_measured
    assert "will not download it at runtime" in (count.note or "")


def test_approximate_fidelity_requires_an_explanation():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="approximation_note"):
        TokenizerSpec(encoding="o200k_base", fidelity="approximate")


# --- vision formulas ------------------------------------------------------


def test_resolution_preset_sets_the_long_edge():
    size = rendered_size(*A4_PT, ResolutionPreset(long_edge_px=1536))
    assert size.height_px == 1536
    assert size.width_px == pytest.approx(1086, abs=2)


def test_width_height_formula_divides_pixel_area():
    formula = WidthHeightVisionFormula(kind="width_height", divisor=750)
    assert vision_tokens(RenderedSize(750, 1000), formula) == 1000


def test_width_height_formula_respects_its_cap():
    formula = WidthHeightVisionFormula(kind="width_height", divisor=750, cap_tokens=1600)
    assert vision_tokens(RenderedSize(4000, 4000), formula) == 1600


def test_tiled_formula_charges_per_tile():
    formula = TiledVisionFormula(
        kind="tiled",
        base_tokens=85,
        tile_tokens=170,
        tile_px=512,
        max_short_side_px=768,
        max_long_side_px=2000,
    )
    # 512x512 fits in exactly one tile.
    assert vision_tokens(RenderedSize(512, 512), formula) == 85 + 170
    # 1024x512 needs two.
    assert vision_tokens(RenderedSize(1024, 512), formula) == 85 + 2 * 170


def test_flat_formula_is_flat_below_the_threshold():
    formula = FlatVisionFormula(
        kind="flat_per_image", tokens_per_image=258, tile_above_px=384, tile_tokens=258
    )
    assert vision_tokens(RenderedSize(100, 100), formula) == 258
    assert vision_tokens(RenderedSize(384, 384), formula) == 258


def test_flat_formula_tiles_above_the_threshold():
    formula = FlatVisionFormula(
        kind="flat_per_image", tokens_per_image=258, tile_above_px=384, tile_tokens=258
    )
    assert vision_tokens(RenderedSize(768, 384), formula) == 2 * 258


def test_the_three_providers_disagree_as_they_should(config):
    """The whole reason the formulas live in config is that they differ."""
    size = rendered_size(*A4_PT, config.pricing.resolution_presets["medium"])
    results = {
        name: vision_tokens(size, formula)
        for name, formula in config.pricing.vision_formulas.items()
    }
    assert len(set(results.values())) == len(results), results


def test_zero_sized_page_yields_no_tokens(config):
    formula = config.pricing.vision_formulas["width_height_area"]
    assert vision_tokens(RenderedSize(0, 0), formula) == 0


# --- estimates ------------------------------------------------------------


def test_document_facts_are_reported(loader, config):
    estimate = estimate_document(loader("native_text.pdf"), config.pricing)
    assert estimate.page_count == 2
    assert estimate.has_text_layer is True
    assert len(estimate.pages) == 2
    assert estimate.pages[0].size_label.startswith("595 x 842")


def test_dpi_is_reported_for_a_scan_and_not_for_text(loader, config):
    scan = estimate_document(loader("scanned_page.pdf"), config.pricing)
    text = estimate_document(loader("native_text.pdf"), config.pricing)
    assert scan.pages[0].dpi == pytest.approx(200, abs=5)
    assert text.pages[0].dpi is None


def test_a_scan_has_no_text_path(loader, config):
    """Quoting a cost of zero for an impossible path would be a lie."""
    estimate = estimate_document(loader("scanned_page.pdf"), config.pricing)
    model = estimate.models[0]
    assert model.text_path_input_usd is None
    assert "no text layer" in (model.text_path_unavailable_reason or "")


def test_unknown_page_size_gives_no_vision_path_rather_than_zero(loader, config):
    estimate = estimate_document(loader("sample.xlsx"), config.pricing)
    model = estimate.models[0]
    assert model.vision_input_usd_by_resolution == {}
    assert "not a cost of zero" in (model.vision_path_unavailable_reason or "")


def test_cost_scales_with_the_price(loader, config):
    estimate = estimate_document(loader("native_text.pdf"), config.pricing)
    by_id = {m.model_id: m for m in estimate.models}
    opus, haiku = by_id["claude-opus-5"], by_id["claude-haiku-4-5"]
    assert opus.text_path_input_usd == pytest.approx(haiku.text_path_input_usd * 5, rel=1e-6)


def test_monthly_volume_extrapolates(loader, config):
    documents = [loader("native_text.pdf"), loader("two_column.pdf")]
    folder = estimate_folder(documents, config.pricing, monthly_volume=1000)
    volume = folder.volume
    assert volume is not None
    assert volume.monthly_text_usd == pytest.approx(volume.mean_text_path_usd * 1000)
    assert volume.annual_text_usd == pytest.approx(volume.monthly_text_usd * 12)
    assert "representative" in volume.basis


def test_without_a_volume_there_is_no_extrapolation(loader, config):
    folder = estimate_folder([loader("native_text.pdf")], config.pricing)
    assert folder.volume is None


def test_unpriced_models_are_not_costed(loader, config):
    estimate = estimate_document(loader("native_text.pdf"), config.pricing)
    ids = {m.model_id for m in estimate.models}
    assert "openai-vision-model" not in ids, "an unpriced template must not be costed"
