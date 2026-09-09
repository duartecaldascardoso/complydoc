"""Load the local models once, so forked workers inherit them.

Importing this module is a side effect on purpose: it pays for the tokenizer
vocabulary, the language model and the entity model up front. On its own that
saves nothing, but the process pool forks its workers from a server process that
has imported this, so each worker starts with the models already in memory
instead of spending a second and a half loading its own copy of each.

Nothing here reaches the network — every model is local, and the offline guard
is armed before any of it runs.
"""

from __future__ import annotations

__all__ = ["warm"]


def warm() -> None:
    """Load what a worker would otherwise load on its first document."""
    try:
        import py3langid

        py3langid.classify("the quick brown fox jumps over the lazy dog")
    except Exception:  # pragma: no cover - a warm-up must never fail a run
        pass

    try:
        from complydoc.config.loader import load_config
        from complydoc.cost.tokenizer import _encoder

        for name in {m.tokenizer.encoding for m in load_config().pricing.usable_models}:
            _encoder(name)
    except Exception:  # pragma: no cover
        pass

    try:
        from complydoc.sensitive.detectors.ner import _load

        _load("en_core_web_sm")
    except Exception:  # pragma: no cover - the NER extra is optional
        pass


warm()
