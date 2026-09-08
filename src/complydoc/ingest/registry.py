"""Extension to loader mapping.

Adding a format means adding a module under `ingest/` that calls `register`, and
importing it below. There is no switch statement to edit.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Final

from complydoc.ingest.base import Document, IngestOptions, Loader, LoaderError

__all__ = ["load_document", "loader_for", "register", "supported_extensions"]

_LOADERS: Final[dict[str, Loader]] = {}
_discovered = False


def register(loader: Loader) -> Loader:
    for extension in loader.extensions:
        _LOADERS[extension.lower()] = loader
    return loader


def _discover() -> None:
    """Import every sibling module once so their `register` calls run."""
    global _discovered
    if _discovered:
        return
    _discovered = True
    package = importlib.import_module("complydoc.ingest")
    for info in pkgutil.iter_modules(package.__path__):
        if info.name in {"base", "registry", "ocr", "errors"}:
            continue
        importlib.import_module(f"complydoc.ingest.{info.name}")


def supported_extensions() -> tuple[str, ...]:
    _discover()
    return tuple(sorted(_LOADERS))


def loader_for(path: Path) -> Loader | None:
    _discover()
    return _LOADERS.get(path.suffix.lower())


def load_document(path: Path, options: IngestOptions) -> Document:
    loader = loader_for(path)
    if loader is None:
        raise LoaderError(f"no loader registered for extension {path.suffix!r}")
    return loader.load(path, options)
