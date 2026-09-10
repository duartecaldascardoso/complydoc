"""What to do next, and what it would buy.

The audit says what is wrong; this says what to do. Two rules keep it from
becoming a nag, and both are what these tests check: it never predicts a score
it cannot know, and it always says who has to act.
"""

from __future__ import annotations

from complydoc.audit import run_audit
from complydoc.quickwins import quick_wins
from tests.helpers import FIXTURES

ALL = ("cost", "readiness", "sensitive")


def wins(config, ocr=False):
    return quick_wins(run_audit(FIXTURES, config, ALL, ocr=ocr))


def test_every_win_names_the_documents_it_applies_to(config):
    """Advice with no files attached is advice nobody can act on."""
    found = wins(config)
    assert found
    assert all(w.documents for w in found)
    assert all(w.affected == len(w.documents) for w in found)


def test_every_win_says_who_has_to_do_it(config):
    """A list mixing "we can do this" with "you must rescan these" is
    a list nobody works through."""
    assert all(w.actor in {"complydoc", "you"} for w in wins(config))


def test_the_biggest_win_comes_first(config):
    found = wins(config)
    assert [w.affected for w in found] == sorted((w.affected for w in found), reverse=True)


def test_pages_nothing_came_off_are_offered_to_ocr(config):
    """The one the tool can act on itself, and the one that moves the bill."""
    found = {w.id: w for w in wins(config, ocr=False)}
    entry = found.get("ocr_blank_pages")
    assert entry is not None, "the fixtures include scans"
    assert entry.actor == "complydoc"
    assert entry.saving_usd_per_1000 is not None


def test_running_ocr_removes_the_reason_to_run_ocr(config):
    """A quick win that has already been taken should stop being offered."""
    assert "ocr_blank_pages" not in {w.id for w in wins(config, ocr=True)}


def test_a_win_never_predicts_a_score(config):
    """Signals interact; the only honest way to know is to fix and re-run.

    Anything of the shape "this would take you to 84" is a fabrication, so the
    text says what concretely changes instead.
    """
    for win in wins(config):
        assert "/100" not in (win.effect or "")
        assert "/100" not in win.detail


def test_an_unsupported_file_is_not_called_broken(config):
    """A folder holding a text file is normal; a truncated PDF is not."""
    found = {w.id: w for w in wins(config)}
    if "unsupported_types" in found and "unreadable_files" in found:
        assert not set(found["unsupported_types"].documents) & set(
            found["unreadable_files"].documents
        )


def test_the_saving_matches_the_price_the_report_shows(config):
    """A number quoted here that the cost page contradicts is worse than none."""
    from complydoc.report.charts import build_comparison, headline_comparison

    report = run_audit(FIXTURES, config, ALL, ocr=False)
    entry = next(w for w in quick_wins(report) if w.id == "ocr_blank_pages")
    headline = headline_comparison(build_comparison(report), "claude-sonnet-5")
    spread = headline.by_key("vision").per_1000_usd - headline.by_key("text_ocr").per_1000_usd
    share = entry.affected / len(report.documents)
    assert entry.saving_usd_per_1000 == round(spread * share, 4)
