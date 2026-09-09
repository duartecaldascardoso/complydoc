"""Vendor a model price table into the package.

complydoc never reaches the network during an audit, so the prices have to be on
disk before a run starts. Keeping them in `pricing.yaml` by hand meant the tool
knew about ten models.

The catalogue comes from models.dev, which is curated per provider and carries a
release date for every model — so complydoc can say which are current rather
than dumping an alphabetical list where a two-year-old model sorts above this
month's. Batch prices come from litellm, which is the only one of the two that
publishes them.

Only first-party providers are kept. Both sources also carry the same models
re-exposed through routing layers — Bedrock, Azure, OpenRouter, Vertex — which
would list one model half a dozen times under names that price the same request
differently depending on who fronts it.

    uv run python scripts/build_price_table.py                 # fetch both
    uv run python scripts/build_price_table.py --offline       # keep batch prices as they are

Nothing here runs during an audit. Every entry it writes is marked imported
rather than verified, because nobody checked it against the provider's own page.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "complydoc" / "config" / "model_prices.json"

CATALOGUE_URL = "https://models.dev/api.json"
CATALOGUE_HOME = "https://models.dev"
BATCH_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)

# models.dev names some providers differently from the rest of the ecosystem.
# complydoc's own vision formulas are keyed on the names used here.
PROVIDERS = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "gemini",
    "deepseek": "deepseek",
    "moonshotai": "moonshot",
    "zai": "zai",
    "mistral": "mistral",
    "xai": "xai",
}

_PER_MTOK = 1_000_000


def _fetch(url: str) -> Any:
    print(f"fetching {url}")
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _batch_prices(table: dict[str, Any]) -> dict[str, float]:
    """Published batch input prices, keyed by the bare model id.

    litellm prefixes some ids with their provider; the catalogue does not, so the
    prefix is dropped to let the two line up.
    """
    prices: dict[str, float] = {}
    for name, entry in table.items():
        if not isinstance(entry, dict):
            continue
        rate = entry.get("input_cost_per_token_batches")
        if not isinstance(rate, int | float) or rate <= 0:
            continue
        prices[name.split("/")[-1]] = round(float(rate) * _PER_MTOK, 6)
    return prices


def build(catalogue: dict[str, Any], batch: dict[str, float]) -> dict[str, Any]:
    models: dict[str, Any] = {}
    for source_provider, provider in PROVIDERS.items():
        entry = catalogue.get(source_provider)
        if not entry:
            print(f"  warning: {source_provider} is not in the catalogue")
            continue
        for model_id, model in sorted(entry.get("models", {}).items()):
            cost = model.get("cost") or {}
            price = cost.get("input")
            if not isinstance(price, int | float) or price <= 0:
                continue
            inputs = (model.get("modalities") or {}).get("input") or []
            models[model_id] = {
                "provider": provider,
                "display_name": model.get("name") or model_id,
                "input_per_mtok_usd": round(float(price), 6),
                "output_per_mtok_usd": (
                    round(float(cost["output"]), 6)
                    if isinstance(cost.get("output"), int | float)
                    else None
                ),
                # Only where the provider publishes one. The customary half price
                # is not assumed: a discount nobody can check does not belong in
                # a budget.
                "batch_input_per_mtok_usd": batch.get(model_id),
                # An explicit list of what the model accepts, rather than a
                # single "supports vision" flag that says nothing about PDFs.
                "accepts_image": "image" in inputs,
                "accepts_pdf": "pdf" in inputs,
                "release_date": model.get("release_date"),
                "max_input_tokens": (model.get("limit") or {}).get("context"),
            }
    return {
        "source_url": CATALOGUE_HOME,
        "source_licence": "MIT",
        "batch_source_url": "https://github.com/BerriAI/litellm",
        "imported": dt.date.today().isoformat(),
        "models": models,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", type=Path, help="A local copy of models.dev's api.json.")
    parser.add_argument("--batch", type=Path, help="A local copy of litellm's price table.")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not fetch: reuse the batch prices already in the vendored table.",
    )
    parser.add_argument("--out", type=Path, default=OUT)
    arguments = parser.parse_args()

    catalogue = (
        json.loads(arguments.catalogue.read_text(encoding="utf-8"))
        if arguments.catalogue
        else _fetch(CATALOGUE_URL)
    )

    if arguments.batch:
        batch = _batch_prices(json.loads(arguments.batch.read_text(encoding="utf-8")))
    elif arguments.offline and arguments.out.exists():
        previous = json.loads(arguments.out.read_text(encoding="utf-8"))
        batch = {
            name: entry["batch_input_per_mtok_usd"]
            for name, entry in previous.get("models", {}).items()
            if entry.get("batch_input_per_mtok_usd")
        }
    else:
        batch = _batch_prices(_fetch(BATCH_URL))

    built = build(catalogue, batch)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(built, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    entries = built["models"]
    providers: dict[str, int] = {}
    for entry in entries.values():
        providers[entry["provider"]] = providers.get(entry["provider"], 0) + 1
    images = sum(1 for e in entries.values() if e["accepts_image"])
    batched = sum(1 for e in entries.values() if e["batch_input_per_mtok_usd"])
    newest = max((e["release_date"] for e in entries.values() if e["release_date"]), default="?")
    print(
        f"{arguments.out}: {len(entries)} models "
        f"({arguments.out.stat().st_size / 1024:.0f} KB), {images} take images, "
        f"{batched} have a batch price, newest released {newest}"
    )
    for provider, count in sorted(providers.items()):
        print(f"  {provider:12s} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
