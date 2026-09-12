"""Text out of documents, with the identifiers covered over.

    import complydoc as cd

    result = cd.extract_text("~/contracts")
    for chunk in result.chunks:
        send_to_model(chunk.text)        # identifiers replaced with mask characters
        budget += chunk.tokens

    for gap in result.warnings:
        log.warning("%s: %s", gap.kind, gap.detail)

This is the audit turned around. The report says what a folder is like; this
hands back the folder's own words, ready to go somewhere else, with everything
the scan would have reported replaced by mask characters.

Three things make it trustworthy rather than merely convenient.

**It does not go through the report.** A report truncates long pages, because a
person is going to read it. Dropping the end of a contract without saying so
would be indefensible here, so the documents are loaded and scanned directly
and the text comes back whole.

**Every count says how good it is.** A token figure from the real encoding and
a token figure from dividing by four are both numbers, and only one of them can
be budgeted against. `chunk.token_fidelity` says which this is.

**It says what it could not get, and what it cannot promise.** A page nothing
could be read off, a file that would not open, a category that could not be
scanned at all — and, every time masking runs, that some categories are found
by a statistical model rather than by a rule.

That last warning is the one to read. A card number is masked because it passed
a checksum; a person's name is masked because a model thought it was one, and
models miss. On the sample document that ships with this tool the model finds
"John Smith" and misses "Jane Doe" on the line above it. Masked text is a great
deal safer than the original and it is not a guarantee, so nothing here says it
is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from complydoc.config.schema import Config, TokenizerSpec
from complydoc.cost.tokenizer import count_tokens
from complydoc.discovery import discover
from complydoc.ingest.base import IngestOptions
from complydoc.ingest.registry import load_document
from complydoc.sensitive.base import EVIDENCE_ORDER, SensitiveMatch
from complydoc.sensitive.scanner import scan

__all__ = ["Chunk", "ExtractionWarning", "TextResult", "extract_text"]

MASKING_INCOMPLETE = "masking_incomplete"
"""An identifier category could not be scanned at all, so none were covered.

The most serious of the warnings. Everything else means content is missing;
this means content a caller believes is masked is not.
"""

MASKING_BEST_EFFORT = "masking_best_effort"
"""Some categories are found by a model, which misses.

Raised whenever masking runs at all, because it is always true and it is the
thing a caller most needs to have been told. Names and organisations have no
checksum to pass, so they are recognised statistically: the text that comes
back is far safer than the original and is not certified clean.
"""

UNREADABLE_DOCUMENT = "unreadable_document"
"""A file that could not be opened at all. None of its content is here."""

UNREADABLE_PAGE = "unreadable_page"
"""A page nothing could be read off. Usually a scan with OCR turned off."""

TEXT_ESTIMATED_TOKENS = "estimated_tokens"
"""No local encoding was available, so token counts are a character estimate."""


@dataclass(frozen=True, slots=True)
class Chunk:
    """One piece of a document's text, and what is known about it."""

    document: str
    """Path relative to the folder that was asked for."""
    page: int
    part: int
    """1 unless the page was split to fit `max_tokens`."""
    text: str
    tokens: int
    token_fidelity: str
    """'exact', 'approximate' (a real encoding, another provider's) or 'estimated'."""
    encoding: str
    masked: int
    """How many identifiers were covered over in this chunk."""
    masked_confirmed: int
    """How many of those passed a checksum rather than being a model's guess.

    The difference between the two is the part of the masking that is best
    effort. A chunk where they are equal had nothing guessed in it.
    """
    source: str
    """'native' where the text was on the page, 'ocr' where it was recognised."""


@dataclass(frozen=True, slots=True)
class ExtractionWarning:
    """Something the caller needs to know before using the text."""

    kind: str
    detail: str
    document: str | None = None
    page: int | None = None

    @property
    def hides_content(self) -> bool:
        """Whether this warning means text is missing from the result."""
        return self.kind in {UNREADABLE_DOCUMENT, UNREADABLE_PAGE}


@dataclass(frozen=True, slots=True)
class TextResult:
    """Everything read, in order, with what could not be read alongside it."""

    chunks: list[Chunk] = field(default_factory=list)
    warnings: list[ExtractionWarning] = field(default_factory=list)
    masked: bool = True
    documents_read: int = 0
    documents_skipped: int = 0

    @property
    def text(self) -> str:
        """Every chunk joined, for the common case of wanting the lot."""
        return "\n\n".join(chunk.text for chunk in self.chunks)

    @property
    def tokens(self) -> int:
        return sum(chunk.tokens for chunk in self.chunks)

    @property
    def masked_count(self) -> int:
        return sum(chunk.masked for chunk in self.chunks)

    @property
    def complete(self) -> bool:
        """Whether everything in the folder reached this result.

        False when a file or a page could not be read. Check it before treating
        the text as the whole of what you pointed at.
        """
        return not any(w.hides_content for w in self.warnings)

    @property
    def all_categories_scanned(self) -> bool:
        """Whether every configured identifier category actually ran.

        Deliberately not called `masking_complete`: it says that nothing was
        skipped, not that nothing was missed. The categories a model finds miss
        things even when they run perfectly, which `MASKING_BEST_EFFORT` says
        every time masking happens.
        """
        return not any(w.kind == MASKING_INCOMPLETE for w in self.warnings)

    @property
    def guaranteed(self) -> list[Chunk]:
        """The chunks whose identifiers were all confirmed by a checksum.

        Empty unless `mask` ran. Use it where a wrong answer is expensive
        enough that best effort is not good enough — and read
        `all_categories_scanned` first.
        """
        return [c for c in self.chunks if c.masked and c.masked == c.masked_confirmed]


def _mask_page(text: str, matches: list[SensitiveMatch]) -> tuple[str, int, int]:
    """Replace each found identifier with its masked form.

    Returns the text, how many were replaced, and how many of those passed a
    checksum — the difference being the part of the masking that rests on a
    model's judgement.

    Matches can overlap, and that is the whole difficulty. The detectors are
    independent, so a card number that passed a checksum and a name a model
    thought it saw can claim the same characters: on a line reading
    `Card 4111 1111 1111 1111` the model calls `Card 4111` an organisation.
    Replacing them one after another let the weaker of the two write back over
    the stronger and put four digits of a card number into the clear.

    So this works a character at a time, strongest evidence first, and never
    writes where something has already been masked. Masking preserves length —
    separators are kept so an identifier keeps its shape — which makes each
    masked string index-aligned with the characters it covers, so taking part
    of one is exact. A masked string of some other length would break that, so
    it takes the whole span instead.
    """
    if not matches:
        return text, 0, 0

    lines = text.split("\n")
    covered: dict[int, set[int]] = {}
    replaced = 0
    confirmed = 0

    for match in sorted(matches, key=_strength):
        index = match.line - 1
        if not 0 <= index < len(lines):
            continue
        chars = list(lines[index])
        start = match.column
        end = start + match.length
        if start < 0 or end > len(chars):
            continue

        done = covered.setdefault(index, set())
        free = [position for position in range(start, end) if position not in done]
        if not free:
            # Wholly inside something already masked. Counting it would say two
            # things were covered where one was.
            continue

        if len(match.masked) == match.length:
            for position in free:
                chars[position] = match.masked[position - start]
        else:  # pragma: no cover - masking preserves length today
            chars[start:end] = list(match.masked)
        done.update(range(start, end))
        lines[index] = "".join(chars)
        replaced += 1
        if match.evidence == "confirmed":
            confirmed += 1

    return "\n".join(lines), replaced, confirmed


def _strength(match: SensitiveMatch) -> tuple[int, int, int]:
    """Sort key: the best-evidenced match claims its characters first."""
    rank = EVIDENCE_ORDER.index(match.evidence) if match.evidence in EVIDENCE_ORDER else 99
    return rank, match.line, match.column


def _split(text: str, spec: TokenizerSpec, max_tokens: int) -> list[str]:
    """Break a page into pieces of at most `max_tokens`, at paragraph breaks.

    Paragraphs first, then lines, and a line longer than the budget on its own
    is passed through whole rather than cut mid-sentence: a chunk slightly over
    budget is a smaller problem than a sentence in two halves.
    """
    if count_tokens(text, spec).tokens <= max_tokens:
        return [text]

    pieces: list[str] = []
    current: list[str] = []
    for block in _blocks(text):
        candidate = "\n\n".join([*current, block])
        if current and count_tokens(candidate, spec).tokens > max_tokens:
            pieces.append("\n\n".join(current))
            current = [block]
        else:
            current.append(block)
    if current:
        pieces.append("\n\n".join(current))
    return pieces or [text]


def _blocks(text: str) -> list[str]:
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    return paragraphs if len(paragraphs) > 1 else [ln for ln in text.split("\n") if ln.strip()]


def _tokenizer_for(config: Config, model: str | None) -> TokenizerSpec:
    """The encoding to count with: the named model's, or the headline one's."""
    wanted = model or config.pricing.compare.headline_model
    entry = config.pricing.model_by_id(wanted)
    if entry is not None:
        return entry.tokenizer
    usable = config.pricing.usable_models
    if usable:
        return usable[0].tokenizer
    # Nothing configured to count against. A count from some encoding, labelled
    # as another provider's, beats refusing to give one at all.
    return TokenizerSpec(
        encoding="cl100k_base",
        fidelity="approximate",
        approximation_note="no model is configured, so this is another provider's encoding",
    )


def extract_text(
    target: str | Path,
    *,
    config: Config | None = None,
    mask: bool = True,
    reveal: bool = False,
    ocr: bool = True,
    recurse: bool = True,
    password: str = "",
    extractor: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> TextResult:
    """Read a folder's text, masked, with token counts and what went wrong.

    `ocr` is on here, unlike the audit: somebody asking for the text of a
    folder wants the scanned pages read too, and a silently empty page is the
    thing this is meant to warn about rather than produce.

    `mask=False` returns the text as the page says it, with no scan run at all.
    `reveal=True` runs the scan and reports the counts while leaving the values
    in place — a combination worth being deliberate about.
    """
    from complydoc.config.loader import load_config

    settings = config or load_config()
    root = Path(target).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"no such file or folder: {root}")

    files, skipped = discover(root, recurse=recurse)
    spec = _tokenizer_for(settings, model)
    warnings: list[ExtractionWarning] = [
        ExtractionWarning(
            kind=UNREADABLE_DOCUMENT,
            detail=record.reason,
            document=_relative(record.path, root),
        )
        for record in skipped
    ]

    chunks: list[Chunk] = []
    read = 0
    options = IngestOptions(ocr=ocr, password=password, extractor=extractor or "pdfplumber")
    seen_categories: set[str] = set()

    for path in files:
        relative = _relative(path, root)
        try:
            document = load_document(path, options)
        except Exception as exc:
            warnings.append(
                ExtractionWarning(
                    kind=UNREADABLE_DOCUMENT,
                    detail=f"{type(exc).__name__}: {exc}",
                    document=relative,
                )
            )
            continue
        read += 1

        found = scan(document, settings.sensitive, reveal=reveal) if mask or reveal else None
        if found is not None:
            for entry in found.unscanned_categories:
                if entry.category in seen_categories:
                    continue
                seen_categories.add(entry.category)
                warnings.append(
                    ExtractionWarning(
                        kind=MASKING_INCOMPLETE,
                        detail=(
                            f"{entry.label} was not scanned for ({entry.reason}), so the "
                            f"text may still carry identifiers of that kind"
                        ),
                    )
                )

        by_page: dict[int, list[SensitiveMatch]] = {}
        for match in found.matches if found is not None else []:
            by_page.setdefault(match.page, []).append(match)

        for page in document.pages:
            text = page.text or page.ocr_text
            if not text.strip():
                warnings.append(
                    ExtractionWarning(
                        kind=UNREADABLE_PAGE,
                        detail=(
                            "nothing could be read off this page"
                            + ("" if ocr else "; OCR was not run")
                        ),
                        document=relative,
                        page=page.number,
                    )
                )
                continue

            body, replaced, confirmed = (
                _mask_page(text, by_page.get(page.number, [])) if mask else (text, 0, 0)
            )
            parts = _split(body, spec, max_tokens) if max_tokens else [body]
            for index, part in enumerate(parts, start=1):
                counted = count_tokens(part, spec)
                chunks.append(
                    Chunk(
                        document=relative,
                        page=page.number,
                        part=index,
                        text=part,
                        tokens=counted.tokens,
                        token_fidelity=counted.fidelity,
                        encoding=counted.encoding,
                        masked=replaced if index == 1 else 0,
                        masked_confirmed=confirmed if index == 1 else 0,
                        source=page.text_source,
                    )
                )

    # Said every time masking runs, because it is true every time and it is the
    # thing a caller most needs to have been told before sending the text on.
    guessed = sorted(
        entry.label
        for entry in settings.sensitive.enabled_categories.values()
        if entry.detector == "ner"
    )
    if mask and guessed and chunks:
        warnings.append(
            ExtractionWarning(
                kind=MASKING_BEST_EFFORT,
                detail=(
                    f"{', '.join(guessed).lower()} are recognised by a statistical model "
                    f"rather than by a rule, so some will have been missed. The text is "
                    f"much safer than the original and is not certified free of them"
                ),
            )
        )

    if chunks and chunks[0].token_fidelity == "estimated":
        warnings.append(
            ExtractionWarning(
                kind=TEXT_ESTIMATED_TOKENS,
                detail=(
                    f"no local encoding for {spec.encoding}, so token counts are "
                    f"a character estimate rather than a measurement"
                ),
            )
        )

    return TextResult(
        chunks=chunks,
        warnings=warnings,
        masked=mask and not reveal,
        documents_read=read,
        documents_skipped=len(skipped),
    )


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root if root.is_dir() else root.parent))
    except ValueError:  # pragma: no cover - a path from outside the folder
        return str(path)
