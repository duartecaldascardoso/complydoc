"""Vendored data files that let complydoc run with no network access at all.

`tiktoken_cache/` holds the BPE vocabularies for the tokenizer encodings named in
pricing.yaml. tiktoken normally fetches these over HTTP on first use, which the
offline guard blocks and which would make the tool useless on an air-gapped
machine. Shipping them means token counting works out of the box, offline,
forever.
"""

from __future__ import annotations

from pathlib import Path

TIKTOKEN_CACHE_DIR = Path(__file__).parent / "tiktoken_cache"
