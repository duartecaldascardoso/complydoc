# complydoc

An offline command-line tool that audits a folder of business documents and reports
three things:

1. **Cost** — what the documents would cost to process with an LLM.
2. **Difficulty** — how hard they are to extract structured data from.
3. **Sensitive information** — what UK GDPR relevant identifiers they contain.

It is a **pre-purchase diagnostic**, not a production pipeline. It is intended to be
run by a consultant, or by a UK finance or operations team on their own machine,
while deciding whether document automation is worth buying.

## Trust proposition

**complydoc runs fully offline. No document content leaves the machine, ever.**

There is no hosted API call at runtime, and there is deliberately no opt-in flag to
add one. Tokenisation, layout analysis, OCR and named entity recognition all run
against local libraries and local models.

This is enforced rather than promised. `complydoc.offline` replaces the standard
library's outbound socket entry points before any document is opened, so a stray
network call raises instead of succeeding quietly — and the test suite runs a full
audit with the guard armed to prove the tool still works with the network cut off.
Every report records whether the guard was active.

Tokenizer vocabularies are vendored into the package for the same reason: tiktoken
would otherwise fetch them on first use, which would fail on an air-gapped machine.

## Sensitive values are masked by default

The scan reports **counts and locations**, not values. A tool that flags a leaked
bank account number by printing it in a report that then gets forwarded by email has
made the problem worse.

- Masked output shows at most the last four characters (`••••5678`).
- `--reveal` exists for when someone genuinely needs the values, and any report
  produced with it is stamped prominently.
- Categories under `masking.never_reveal` in `sensitive.yaml` — card numbers and
  National Insurance numbers by default — stay masked **even with `--reveal`**.

Structurally, detectors return character *spans*, never strings. The only function
that turns a span back into readable text is `sensitive.masking.render`, so a report
cannot leak a value by accident.

## Install

Requires Python 3.11–3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

That gives you a working cost and difficulty tool immediately. Two optional extras
add the heavier paths:

```bash
uv sync --extra ocr                          # read scanned pages
uv sync --extra ner                          # detect person and organisation names
uv run python -m spacy download en_core_web_sm
```

Both extras download their models **once, at install time**, exactly like any other
dependency. Nothing is fetched at scan time. When an extra is missing, complydoc
degrades loudly: affected pages and categories are named individually in the report's
limitations rather than being counted as clean.

Check what you have:

```bash
uv run complydoc doctor
```

## Use

```bash
uv run complydoc audit ./invoices --monthly-volume 2500 --out reports
```

Each component also runs on its own, so you can have only the part you want:

```bash
uv run complydoc cost ./invoices --monthly-volume 2500
uv run complydoc difficulty ./invoices
uv run complydoc sensitive ./invoices
```

Useful flags: `--ocr` to read scanned pages, `--reveal` to unmask values,
`--vision-resolution low|medium|high`, `--config-dir` to point at your own config,
`--no-recurse`, `--quiet`.

Supported inputs: PDF (native text and scanned), PNG, JPG, TIFF, BMP, DOCX, XLSX.
Folders are recursed. Anything that cannot be opened is skipped and reported, never
fatal.

## Output

Every run writes both formats:

- **JSON** — machine readable and stable under `diff`, so runs can be compared over
  time. Carries a schema version and a digest of the config that produced it.
- **HTML** — self-contained, no external assets, openable from a USB stick and
  forwardable by email. Has a per-document section and an aggregate section for the
  decision maker.

Both carry a **limitations section generated from the run itself** — which pages
could not be read, which detectors were unavailable, which signals did not apply,
which prices are unverified. It describes that run rather than the tool in general.

## The three components

### Cost

Per document: page count, page dimensions, DPI, whether a text layer exists and what
fraction of the page it covers, text token count from a real tokenizer, and vision
token counts at each resolution preset.

Vision token formulas differ by provider — some tile the image, some use a width by
height formula, some charge a flat count per image — so all three shapes live in
`pricing.yaml`, not in code.

Two paths are costed: text extraction and vision. Where a path does not exist (a
scan has no text layer; a spreadsheet has no fixed page size) complydoc says **not
applicable** rather than quoting a cost of zero.

Only **input** cost is estimated. Output length depends on what you ask the model to
produce, which this tool cannot know.

**Prices carry a `last_verified` date per entry.** The report prints it and warns
past 90 days. An entry with no date is treated as never verified and warned about on
every run. complydoc ships Anthropic prices with a sourcing date, and OpenAI and
Google entries as templates with the formula shape filled in but **no price** —
because those were not sourced when the config was written, and inventing one would
be worse than leaving it blank.

### Difficulty

A table of individually measured signals — 18 of them — each with the measured
value, a rating, and one plain sentence saying why it matters. Not a single opaque
number. A reader must be able to disagree with any one line without rejecting the
report.

Measured: text layer presence and coverage, image area proportion, garbled character
rate (replacement characters, undecomposed ligatures, run-together words), table
count, header depth and merged cells, column layout, page rotation and estimated
skew, scan DPI, font count and embedding, date format consistency, page size
variance, detected language, encryption, and AcroForm fields — which are scored as a
**positive** signal.

A weighted score is included, but only because every weight is visible in
`difficulty.yaml` and printed next to its row. The config schema refuses to load a
configuration that enables scoring while hiding the weights. Signals that cannot be
measured are excluded from the score rather than counted as failures, and a score
resting on too few signals is flagged as low confidence.

### Sensitive information

UK GDPR relevant identifiers: National Insurance numbers, sort codes, bank account
numbers, IBANs, payment cards, postcodes, street addresses, emails, phone numbers,
dates of birth, VAT numbers, UTRs, and person and organisation names via a local NER
model.

Checksums do the heavy lifting against false positives: Luhn for cards, ISO 13616
mod-97 for IBANs, mod-97 for VAT numbers, prefix rules for NI numbers. Patterns too
generic to stand alone — a bare eight-digit account number — are only reported when a
label such as "account number" appears nearby, and the report says which label
justified each one.

Pages with no readable text are listed by number. **Zero findings on a page nobody
could read is not an all-clear**, and the report never implies otherwise.

## Configuration

Three files under `src/complydoc/config/`, overridable wholesale with `--config-dir`:

| File | Holds |
| --- | --- |
| `pricing.yaml` | Model prices, vision token formulas, resolution presets, `last_verified` dates |
| `difficulty.yaml` | Signal weights, rating thresholds, scoring rules |
| `sensitive.yaml` | Detection patterns, validators, severities, masking rules |

Every number a reader might want to argue with lives in YAML. None is hardcoded.

## Extending it

Adding a difficulty signal means adding **one file** under
`src/complydoc/difficulty/signals/` with an `@signal` decorated class, and a weight
block in `difficulty.yaml`. The package is walked at import time; there is no central
switch statement to edit. Sensitive data detectors work the same way via `@detector`,
and file format loaders via `register`.

## Development

```bash
uv sync --group dev
uv run pytest                              # 166 tests
uv run pytest --cov=complydoc              # ~91% coverage
uv run ruff check src tests && uv run mypy src/complydoc
uv run python tests/generate_fixtures.py   # rebuild the committed fixtures
```

Fixtures are committed and include deliberately awkward documents: a scanned page, a
three-row merged header table, a two-column layout, a scan that is both skewed and
rotated 90 degrees, an encrypted PDF, one with a deliberately corrupted ToUnicode
map, one with mixed page sizes, a fillable form, and a corrupt file. Every value in
the synthetic PII fixture is fake — a published test card number, the IBAN from the
ISO specification, an Ofcom fiction-range phone number and invented names.

## Licence

MIT
