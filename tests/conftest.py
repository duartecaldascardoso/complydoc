"""Shared fixtures.

Documents are loaded once per session because rasterising a scan is slow enough
to notice if it happens in every test.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from complydoc.config.loader import load_config
from complydoc.config.schema import Config
from complydoc.ingest.base import Document, IngestOptions
from complydoc.ingest.registry import load_document
from tests.helpers import FIXTURES


@pytest.fixture(scope="session")
def config() -> Config:
    return load_config()


@pytest.fixture(scope="session")
def loader() -> Callable[..., Document]:
    """Load a fixture document by filename, cached for the session."""
    cache: dict[tuple[str, bool], Document] = {}

    def _load(name: str, ocr: bool = False) -> Document:
        key = (name, ocr)
        if key not in cache:
            cache[key] = load_document(FIXTURES / name, IngestOptions(ocr=ocr))
        return cache[key]

    return _load
