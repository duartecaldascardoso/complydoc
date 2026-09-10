"""Where two readings of the same page part company.

Knowing that two extractors disagree is most of the measurement and none of the
answer. A page of a contract is two thousand characters; being told that one
reader matches another 87% of the way leaves someone to find the other 13% by
reading both. This turns that into something the eye can land on.

The comparison is by word rather than by character. Character diffs mark the
inside of words and read as noise; a reader looking at a page wants to see which
phrases moved, not which letters did.

Spacing is not a difference. Every reader breaks lines somewhere slightly
different, so a comparison that counted that would mark every page of every
document and be worth nothing. Words are compared; the original spacing is what
gets shown.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Literal

from complydoc.text import MAX_WORDS, reading_similarity, words

__all__ = ["ReadingDiff", "Segment", "compare_readings"]

Kind = Literal["same", "added", "missing"]
"""`added` is in this reading and not the kept one; `missing` is the reverse."""


@dataclass(frozen=True, slots=True)
class Segment:
    kind: Kind
    text: str


@dataclass(frozen=True, slots=True)
class ReadingDiff:
    """One other reader's version of a page, against the one that was kept."""

    reader: str
    similarity: float
    segments: list[Segment] = field(default_factory=list)
    truncated: bool = False

    @property
    def differs(self) -> bool:
        return any(s.kind != "same" for s in self.segments)

    @property
    def added_words(self) -> int:
        return sum(len(s.text.split()) for s in self.segments if s.kind == "added")

    @property
    def missing_words(self) -> int:
        return sum(len(s.text.split()) for s in self.segments if s.kind == "missing")


def compare_readings(kept: str, others: dict[str, str]) -> list[ReadingDiff]:
    """Each other reading against the kept one, in the order given."""
    whole = words(kept)
    left = whole[:MAX_WORDS]
    diffs: list[ReadingDiff] = []
    for reader, text in others.items():
        right = words(text)
        truncated = len(whole) > MAX_WORDS or len(right) > MAX_WORDS
        diffs.append(_one(reader, left, right[:MAX_WORDS], truncated))
    return diffs


def _one(reader: str, left: list[str], right: list[str], truncated: bool) -> ReadingDiff:
    # Matched on the bare words, rendered with the spacing each reader used.
    # The two lists line up index for index, so an opcode over one indexes the
    # other.
    matcher = difflib.SequenceMatcher(
        None, [w.strip() for w in left], [w.strip() for w in right], autojunk=False
    )
    ratio = reading_similarity(left, right)
    segments: list[Segment] = []

    def add(kind: Kind, words: list[str]) -> None:
        if not words:
            return
        # Runs of the same kind are joined so the markup is one span per run
        # rather than one per word.
        if segments and segments[-1].kind == kind:
            segments[-1] = Segment(kind, segments[-1].text + "".join(words))
        else:
            segments.append(Segment(kind, "".join(words)))

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            add("same", right[j1:j2])
        elif tag == "insert":
            add("added", right[j1:j2])
        elif tag == "delete":
            add("missing", left[i1:i2])
        else:  # replace: both sides said something, and they are not the same
            add("missing", left[i1:i2])
            add("added", right[j1:j2])

    return ReadingDiff(
        reader=reader,
        similarity=ratio,
        segments=segments,
        truncated=truncated,
    )
