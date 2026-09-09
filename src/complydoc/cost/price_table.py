"""The vendored model price table.

`pricing.yaml` is the curated layer: a short list of models someone has checked
against the provider's own page, and the only ones a report compares by default.
This is the long tail behind it — a few hundred models with prices taken from a
maintained third-party table, so that asking for one by name works without
anybody having hand-written an entry for it first.

The file is data on disk. Nothing here reaches the network; `scripts/build_price_table.py`
refreshes it, and that is a maintenance step, not part of an audit.

Imported prices are marked as imported. They are not presented as verified,
because nobody verified them.
"""

from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from complydoc.config.schema import ModelPricing, TokenizerSpec

__all__ = ["TABLE_PATH", "imported_models", "table_provenance"]

TABLE_PATH = Path(__file__).parent.parent / "config" / "model_prices.json"

# Which of complydoc's vision formulas counts each provider's images. A provider
# missing here is priced for text only rather than guessed at.
_VISION_FORMULA = {
    "anthropic": "width_height_area",
    "openai": "tiled_512",
    "gemini": "flat_then_tiled",
    # These serve an OpenAI-compatible vision API, so the tiling convention is
    # taken to match it. That is an assumption, and each entry says so.
    "deepseek": "tiled_512",
    "moonshot": "tiled_512",
    "zai": "tiled_512",
    "mistral": "tiled_512",
    "xai": "tiled_512",
}

_ASSUMED_FORMULA = frozenset({"deepseek", "moonshot", "zai", "mistral", "xai"})

_EXACT_TOKENIZER = frozenset({"openai"})
"""Providers whose text tokens complydoc can count exactly, with a vendored encoding."""

_APPROXIMATE_NOTE = (
    "{provider} does not publish an offline tokenizer; token counts are "
    "approximated with the o200k_base encoding."
)


def _tokenizer(provider: str) -> TokenizerSpec:
    if provider in _EXACT_TOKENIZER:
        return TokenizerSpec(encoding="o200k_base", fidelity="exact")
    return TokenizerSpec(
        encoding="o200k_base",
        fidelity="approximate",
        approximate_ratio=1.0,
        approximation_note=_APPROXIMATE_NOTE.format(provider=provider),
    )


@lru_cache(maxsize=1)
def _table() -> dict[str, Any]:
    if not TABLE_PATH.exists():  # pragma: no cover - the file ships with the package
        return {"models": {}, "imported": None, "source_url": None}
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def table_provenance() -> tuple[str | None, dt.date | None, int]:
    """Where the table came from, when it was taken, and how many models it holds."""
    table = _table()
    imported = table.get("imported")
    return (
        table.get("source_url"),
        dt.date.fromisoformat(imported) if imported else None,
        len(table.get("models", {})),
    )


@lru_cache(maxsize=1)
def imported_models() -> tuple[ModelPricing, ...]:
    """Every model in the table, switched off.

    Off because a report that compared three hundred models would answer nobody's
    question. They are here so that naming one with `--model` works, and so that
    `complydoc models` can show what is available to name.
    """
    source_url, imported, _ = table_provenance()
    models: list[ModelPricing] = []
    for name, entry in sorted(_table().get("models", {}).items()):
        provider = str(entry.get("provider", "unknown"))
        formula = _VISION_FORMULA.get(provider)
        notes = None
        if provider in _ASSUMED_FORMULA:
            notes = (
                f"The vision token formula is assumed to follow the OpenAI tiling "
                f"convention; {provider} does not publish one."
            )
        models.append(
            ModelPricing(
                id=name,
                provider=provider,
                display_name=name,
                enabled=False,
                input_per_mtok_usd=entry.get("input_per_mtok_usd"),
                output_per_mtok_usd=entry.get("output_per_mtok_usd"),
                batch_input_per_mtok_usd=entry.get("batch_input_per_mtok_usd"),
                supports_vision=formula is not None,
                vision_formula=formula,
                tokenizer=_tokenizer(provider),
                price_source="imported",
                imported_on=imported,
                source_url=source_url,
                notes=notes,
            )
        )
    return tuple(models)
