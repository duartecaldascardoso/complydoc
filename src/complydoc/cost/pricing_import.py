"""Generate pricing.yaml entries from litellm's model price table.

complydoc will not invent a price, which left the OpenAI and Google entries in
the shipped config as empty templates. litellm maintains a table of several
thousand models with real per-token prices, and ships it inside the package as
`model_prices_and_context_window_backup.json`.

This reads that file and emits YAML. litellm is not a runtime dependency and is
never imported by the audit path: it is a 165 MB client library for calling
hosted APIs, which is the wrong shape for a tool that never calls one. Only the
data is used, and only when you ask for it.

The table carries per-token prices but no vision token formulas, because those
are provider-specific tiling rules rather than a number. complydoc keeps those
in `vision_formulas`, and this maps each provider onto the right shape.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

__all__ = ["ImportedModel", "find_litellm_table", "load_table", "select", "to_yaml"]

_FILENAME = "model_prices_and_context_window_backup.json"
_SOURCE_URL = "https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json"

# Which of complydoc's vision formula shapes each provider's images are counted by.
_VISION_FORMULA = {
    "anthropic": "width_height_area",
    "bedrock": "width_height_area",
    "bedrock_converse": "width_height_area",
    "openai": "tiled_512",
    "azure": "tiled_512",
    "azure_ai": "tiled_512",
    "gemini": "flat_then_tiled",
    "vertex_ai-language-models": "flat_then_tiled",
    "vertex_ai": "flat_then_tiled",
}

# Providers whose text tokenizer complydoc can count exactly with a vendored encoding.
_EXACT_TOKENIZER = {"openai", "azure", "azure_ai"}


@dataclass(frozen=True, slots=True)
class ImportedModel:
    id: str
    provider: str
    input_per_mtok_usd: float
    output_per_mtok_usd: float | None
    supports_vision: bool
    vision_formula: str | None


class PricingImportError(RuntimeError):
    """The litellm price table could not be found or read."""


def find_litellm_table() -> Path | None:
    """The bundled JSON inside an installed litellm, if there is one."""
    spec = importlib.util.find_spec("litellm")
    if spec is None or not spec.submodule_search_locations:
        return None
    candidate = Path(next(iter(spec.submodule_search_locations))) / _FILENAME
    return candidate if candidate.is_file() else None


def load_table(path: Path | None = None) -> dict[str, dict[str, object]]:
    source = path or find_litellm_table()
    if source is None:
        raise PricingImportError(
            "litellm is not installed and no --from path was given. Either install it "
            "(uv pip install litellm) or point --from at a copy of "
            f"{_FILENAME}."
        )
    if not source.is_file():
        raise PricingImportError(f"no such file: {source}")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PricingImportError(f"could not read {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise PricingImportError(f"{source} does not contain a JSON object")
    return data


def select(
    table: dict[str, dict[str, object]],
    ids: list[str] | None = None,
    provider: str | None = None,
    vision_only: bool = True,
    limit: int | None = None,
) -> list[ImportedModel]:
    """Pick models out of the table, cheapest first within each provider."""
    chosen: list[ImportedModel] = []
    wanted = set(ids or [])

    for name, entry in table.items():
        if not isinstance(entry, dict):
            continue
        if wanted and name not in wanted:
            continue
        if entry.get("mode") != "chat":
            continue
        this_provider = str(entry.get("litellm_provider") or "")
        if provider and this_provider != provider:
            continue
        supports_vision = bool(entry.get("supports_vision"))
        if vision_only and not wanted and not supports_vision:
            continue

        input_cost = entry.get("input_cost_per_token")
        if not isinstance(input_cost, int | float) or input_cost <= 0:
            continue
        output_cost = entry.get("output_cost_per_token")

        chosen.append(
            ImportedModel(
                id=name,
                provider=this_provider,
                input_per_mtok_usd=round(float(input_cost) * 1_000_000, 6),
                output_per_mtok_usd=(
                    round(float(output_cost) * 1_000_000, 6)
                    if isinstance(output_cost, int | float)
                    else None
                ),
                supports_vision=supports_vision,
                vision_formula=_VISION_FORMULA.get(this_provider),
            )
        )

    missing = wanted - {m.id for m in chosen}
    if missing:
        raise PricingImportError(
            "not found in the price table, or carries no usable chat price: "
            + ", ".join(sorted(missing))
        )

    chosen.sort(key=lambda m: (m.provider, m.input_per_mtok_usd))
    return chosen[:limit] if limit else chosen


def to_yaml(models: list[ImportedModel], today: dt.date | None = None) -> str:
    """A YAML fragment to paste under `models:` in pricing.yaml."""
    stamp = (today or dt.date.today()).isoformat()
    lines = [
        f"  # Imported from the litellm price table on {stamp}.",
        "  # Prices are per million tokens, USD. Check anything that matters before",
        "  # relying on it; complydoc records the import date, not an audit.",
    ]
    for model in models:
        formula = model.vision_formula
        out_cost = model.output_per_mtok_usd if model.output_per_mtok_usd is not None else "null"
        lines += [
            "",
            f"  - id: {model.id}",
            f"    provider: {model.provider}",
            f'    display_name: "{model.id}"',
            "    enabled: true",
            f"    input_per_mtok_usd: {model.input_per_mtok_usd}",
            f"    output_per_mtok_usd: {out_cost}",
            f"    supports_vision: {str(model.supports_vision).lower()}",
            f"    vision_formula: {formula if formula else 'null'}",
            "    tokenizer:",
            "      encoding: o200k_base",
        ]
        if model.provider in _EXACT_TOKENIZER:
            lines.append("      fidelity: exact")
        else:
            lines += [
                "      fidelity: approximate",
                "      approximate_ratio: 1.0",
                "      approximation_note: >",
                f"        {model.provider} does not publish an offline tokenizer; token counts are",
                "        approximated with the o200k_base encoding.",
            ]
        lines += [
            f"    last_verified: {stamp}",
            f"    source_url: {_SOURCE_URL}",
        ]
        if formula is None and model.supports_vision:
            lines.append(
                "    notes: >\n"
                "      No vision token formula is configured for this provider, so the vision\n"
                "      path is reported as not applicable. Add one under vision_formulas."
            )
    return "\n".join(lines) + "\n"
