"""Which OCR engines exist.

Adding one means adding a module in this package that calls `register`, the same
arrangement the extractors, signals and detectors use.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Final

from complydoc.ingest.engines.base import Engine

__all__ = ["DEFAULT_ENGINE", "all_engines", "engine_by_id", "register"]

DEFAULT_ENGINE: Final = "rapidocr"
"""Pip-installable, models bundled, no system binary, and no network at any point."""

_ENGINES: Final[dict[str, Engine]] = {}
_discovered = False


def register(cls: type) -> type:
    instance = cls()
    if not isinstance(instance, Engine):  # pragma: no cover - programming error
        raise TypeError(f"{cls.__name__} does not satisfy the Engine protocol")
    if instance.id in _ENGINES:
        raise ValueError(f"duplicate engine id {instance.id!r}")
    _ENGINES[instance.id] = instance
    return cls


def _discover() -> None:
    global _discovered
    if _discovered:
        return
    _discovered = True
    package = importlib.import_module("complydoc.ingest.engines")
    for info in pkgutil.iter_modules(package.__path__):
        if info.name in {"base", "registry"}:
            continue
        importlib.import_module(f"complydoc.ingest.engines.{info.name}")


def all_engines() -> list[Engine]:
    _discover()
    return [_ENGINES[key] for key in sorted(_ENGINES)]


def engine_by_id(engine_id: str) -> Engine | None:
    _discover()
    return _ENGINES.get(engine_id)
