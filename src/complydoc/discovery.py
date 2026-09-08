"""Turn a path into a list of documents to audit, plus a list of what was skipped.

Nothing here raises on a bad file. A folder of real business documents always
contains something unreadable, and a diagnostic that dies on the first one is
useless.
"""

from __future__ import annotations

from pathlib import Path

from complydoc.ingest.base import SkipRecord
from complydoc.ingest.registry import loader_for, supported_extensions

__all__ = ["discover"]

_IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def _is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def discover(root: Path, recurse: bool = True) -> tuple[list[Path], list[SkipRecord]]:
    """Return (files to audit, files skipped with a reason)."""
    root = root.expanduser()
    files: list[Path] = []
    skipped: list[SkipRecord] = []

    if not root.exists():
        skipped.append(SkipRecord(path=root, reason="path does not exist"))
        return files, skipped

    candidates: list[Path]
    if root.is_file():
        candidates = [root]
    else:
        pattern = "**/*" if recurse else "*"
        candidates = sorted(p for p in root.glob(pattern) if p.is_file())

    for path in candidates:
        relative = path.relative_to(root if root.is_dir() else root.parent)
        if path.name in _IGNORED_NAMES or _is_hidden(relative):
            continue
        if loader_for(path) is None:
            skipped.append(
                SkipRecord(
                    path=path,
                    reason="unsupported file type",
                    detail=(
                        f"{path.suffix or 'no extension'} is not one of "
                        f"{', '.join(supported_extensions())}"
                    ),
                )
            )
            continue
        try:
            if path.stat().st_size == 0:
                skipped.append(SkipRecord(path=path, reason="file is empty"))
                continue
            with path.open("rb") as handle:
                handle.read(1)
        except OSError as exc:
            skipped.append(SkipRecord(path=path, reason="file could not be read", detail=str(exc)))
            continue
        files.append(path)

    return files, skipped
