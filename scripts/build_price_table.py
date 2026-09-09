"""Vendor a model price table into the package.

complydoc never reaches the network during an audit, so the prices have to be on
disk before a run starts. Keeping them in `pricing.yaml` by hand meant the tool
knew about ten models; this pulls the direct providers out of litellm's
maintained table and writes the subset complydoc can actually price.

Only first-party providers are kept. The upstream table also carries the same
models re-exposed through routing layers — Bedrock, Azure, OpenRouter, Vertex —
which would list one model half a dozen times under names that price the same
request differently depending on who fronts it.

Run it to refresh:

    uv run python scripts/build_price_table.py            # fetches the latest
    uv run python scripts/build_price_table.py --from x.json

Nothing here runs during an audit. The result is data, and every entry it writes
is marked as imported rather than verified, because nobody checked it against
the provider's own page.
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

SOURCE_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
SOURCE_HOME = "https://github.com/BerriAI/litellm"
SOURCE_LICENCE = "MIT"

DIRECT_PROVIDERS = {
    "anthropic",
    "openai",
    "gemini",
    "deepseek",
    "moonshot",
    "zai",
    "mistral",
    "xai",
}

_PER_MTOK = 1_000_000


def _rate(entry: dict[str, Any], key: str) -> float | None:
    value = entry.get(key)
    if not isinstance(value, int | float) or value <= 0:
        return None
    return round(float(value) * _PER_MTOK, 6)


def build(table: dict[str, Any]) -> dict[str, Any]:
    models: dict[str, Any] = {}
    for name, entry in sorted(table.items()):
        if not isinstance(entry, dict):
            continue
        provider = entry.get("litellm_provider")
        if provider not in DIRECT_PROVIDERS or not entry.get("supports_vision"):
            continue
        inp = _rate(entry, "input_cost_per_token")
        if inp is None:
            continue
        models[name] = {
            "provider": provider,
            "input_per_mtok_usd": inp,
            "output_per_mtok_usd": _rate(entry, "output_cost_per_token"),
            # Only where the provider publishes one. A batch price is not assumed
            # from the usual half-price convention: an assumed discount in a
            # budget is a number nobody can check.
            "batch_input_per_mtok_usd": _rate(entry, "input_cost_per_token_batches"),
            "max_input_tokens": entry.get("max_input_tokens"),
        }
    return {
        "source_url": SOURCE_HOME,
        "source_licence": SOURCE_LICENCE,
        "imported": dt.date.today().isoformat(),
        "upstream_entries": len(table),
        "models": models,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", type=Path, help="A local copy of the table.")
    parser.add_argument("--out", type=Path, default=OUT)
    arguments = parser.parse_args()

    if arguments.source:
        table = json.loads(arguments.source.read_text(encoding="utf-8"))
    else:
        print(f"fetching {SOURCE_URL}")
        with urllib.request.urlopen(SOURCE_URL, timeout=60) as response:
            table = json.loads(response.read().decode("utf-8"))

    built = build(table)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(built, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    providers: dict[str, int] = {}
    for entry in built["models"].values():
        providers[entry["provider"]] = providers.get(entry["provider"], 0) + 1
    batch = sum(1 for e in built["models"].values() if e["batch_input_per_mtok_usd"])
    size = arguments.out.stat().st_size / 1024
    print(
        f"{arguments.out}: {len(built['models'])} models, {size:.0f} KB, {batch} with a batch price"
    )
    for provider, count in sorted(providers.items()):
        print(f"  {provider:12s} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
