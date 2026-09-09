"""The OCR engine registry.

Unlike the PDF extractors, which agree on a page's text to within a per cent,
OCR engines genuinely disagree. The registry exists so a second opinion is
possible; only the one selected produces the text a report is built from.
"""

from __future__ import annotations

from complydoc.ingest import ocr
from complydoc.ingest.engines.registry import DEFAULT_ENGINE, all_engines, engine_by_id


def test_the_registry_finds_the_engines():
    ids = {e.id for e in all_engines()}
    assert DEFAULT_ENGINE in ids
    assert engine_by_id(DEFAULT_ENGINE) is not None


def test_every_engine_can_say_why_it_is_unavailable():
    """An engine that cannot run has to explain itself, or the report says
    a page carried no text when nothing tried to read it."""
    for engine in all_engines():
        if engine.available():
            assert engine.unavailable_reason() is None
        else:
            reason = engine.unavailable_reason()
            assert reason and len(reason) > 10, engine.id


def test_an_engine_ships_that_needs_no_system_binary():
    """The default has to work from a pip install and reach no network."""
    default = engine_by_id(DEFAULT_ENGINE)
    assert default is not None
    assert default.name


def test_selecting_an_unknown_engine_keeps_the_working_one():
    """A typo should not silently leave a run with no OCR at all."""
    before = ocr.engine_name()
    try:
        ocr.select("no-such-engine")
        assert ocr.engine_name() == before
    finally:
        ocr.select(DEFAULT_ENGINE)


def test_selecting_a_known_engine_takes_effect():
    before = ocr.engine_name()
    try:
        for engine in all_engines():
            ocr.select(engine.id)
            assert ocr.engine_name() == engine.name
    finally:
        ocr.select(DEFAULT_ENGINE)
        assert ocr.engine_name() == before


def test_the_facade_still_counts_what_it_read():
    ocr.reset_stats()
    assert ocr.stats() == (0, 0.0)
    ocr.add_stats(4, 2.0)
    assert ocr.stats() == (4, 2.0)
    ocr.reset_stats()
