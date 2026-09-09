"""Loading the local models once, for the workers to inherit.

Importing `complydoc.warm` is a side effect on purpose. Under the forkserver the
worker processes fork from a server that has imported it, so they start with the
models in memory instead of loading their own copies.
"""

from __future__ import annotations

from complydoc.audit import _pool_context


def test_warming_leaves_the_models_loaded():
    from complydoc.cost.tokenizer import _encoder
    from complydoc.warm import warm

    _encoder.cache_clear()
    warm()
    assert _encoder.cache_info().currsize > 0, "the tokenizer vocabulary is in memory"


def test_warming_never_fails_a_run(monkeypatch):
    """A warm-up is an optimisation; nothing it cannot do is worth stopping for."""
    import complydoc.warm as warm_module

    def explode(*args, **kwargs):
        raise RuntimeError("no model here")

    monkeypatch.setattr("complydoc.cost.tokenizer._encoder", explode)
    monkeypatch.setattr("complydoc.sensitive.detectors.ner._load", explode)
    warm_module.warm()


def test_the_pool_never_forks_this_process():
    """This process may hold the OCR engine's native threads by then.

    Forking one that does is a known way to hang the child, so the pool either
    forks from a clean server process or spawns.
    """
    assert _pool_context().get_start_method() in {"forkserver", "spawn"}
