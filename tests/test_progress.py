"""What the terminal says while a folder is being read.

A run over a few hundred documents takes minutes. A terminal that says nothing
for minutes is indistinguishable from one that has hung, and the clock is the
part people want most: not how far along it is, but whether it is worth waiting.

The line these tests hold is that the display suits where it is going — a bar
in a terminal, plain lines in a pipe, and nothing at all when asked to be quiet.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from rich.console import Console

from complydoc import cli


def render(width: int = 100, terminal: bool = True) -> Console:
    return Console(file=io.StringIO(), force_terminal=terminal, width=width)


def drawn(console: Console) -> str:
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", console.file.getvalue())


def test_a_quiet_run_is_given_nothing_to_report_with():
    """Not an empty reporter — none at all, so the audit does not call one."""
    with cli._watching(quiet=True) as progress:
        assert progress is None


def test_a_terminal_gets_a_bar_a_count_and_a_clock(monkeypatch):
    monkeypatch.setattr(cli, "console", render())
    with cli._watching(quiet=False) as progress:
        assert progress is not None
        progress(1, 4, Path("contract.pdf"))
        progress(2, 4, Path("invoice.pdf"))
    out = drawn(cli.console)
    assert "2/4" in out
    assert "elapsed" in out and "left" in out
    assert "invoice.pdf" in out


def test_a_long_filename_does_not_move_the_bar(monkeypatch):
    """A column that resizes makes the bar jump sideways on every document."""
    monkeypatch.setattr(cli, "console", render())
    with cli._watching(quiet=False) as progress:
        progress(1, 2, Path("a.pdf"))
        short = drawn(cli.console).split("\r")[-1]
        progress(2, 2, Path("a_very_much_longer_document_name_than_that_one.pdf"))
        long = drawn(cli.console).split("\r")[-1]
    assert len(short) == len(long)


def test_a_pipe_gets_lines_instead_of_a_bar(monkeypatch):
    """A redrawing bar in a log file is thousands of lines of escape codes."""
    monkeypatch.setattr(cli, "console", render(terminal=False))
    with cli._watching(quiet=False) as progress:
        assert progress is not None
        progress(1, 2, Path("contract.pdf"))
    out = drawn(cli.console)
    assert "(1/2) contract.pdf" in out
    assert "\r" not in out


def test_the_bar_leaves_no_trace_behind_it(monkeypatch):
    """The summary follows it, and a spent progress bar above it is clutter."""
    monkeypatch.setattr(cli, "console", render())
    with cli._watching(quiet=False) as progress:
        progress(1, 1, Path("contract.pdf"))
    assert not drawn(cli.console).rstrip().endswith("contract.pdf")
