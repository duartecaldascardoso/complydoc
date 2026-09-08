<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/images/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/images/logo-light.svg">
    <img alt="complydoc" src=".github/images/logo-light.svg" width="42%">
  </picture>
</div>

<div align="center">
  <h3>Offline document audit for LLM cost, extraction difficulty, and UK GDPR identifiers.</h3>
</div>

<div align="center">
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/license-MIT-1a7f4b" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-4f5d75" alt="Python versions">
  <img src="https://img.shields.io/badge/network-none%20at%20runtime-1a7f4b" alt="No network at runtime">
  <img src="https://img.shields.io/badge/tests-237-4f5d75" alt="Tests">
  <img src="https://img.shields.io/badge/mypy-strict-4f5d75" alt="mypy strict">
</div>

<br>

complydoc reads a folder of business documents and reports three things: what they would cost to process with an LLM, how hard they are to extract structured data from, and which UK GDPR relevant identifiers they contain. It is a diagnostic you run before buying a document automation system, not a pipeline you run in production.

It makes no network calls at runtime. `complydoc/offline.py` replaces the standard library's outbound socket and DNS entry points before any file is opened, so a stray call raises instead of succeeding. `tests/test_offline_guard.py` runs a full audit with the guard armed. Every report records whether it was active.

<br>

<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/images/complydoc-architecture-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/images/complydoc-architecture.svg">
    <img alt="complydoc pipeline: documents pass through discovery and per-format loaders into three independent analysis components, which emit a JSON report and a self-contained HTML report, all inside a network guard boundary" src=".github/images/complydoc-architecture.svg" width="100%">
  </picture>
</div>

## Quickstart

```bash
uv sync
uv run complydoc audit ./invoices --monthly-volume 2500 --out reports
```

That writes `reports/complydoc.json` and `reports/complydoc.html`.

Each component also runs on its own:

```bash
uv run complydoc cost ./invoices --monthly-volume 2500
uv run complydoc difficulty ./invoices
uv run complydoc sensitive ./invoices
```

By default every priced model in the config is compared. Narrow it with `--model`,
repeated for each one you want:

```bash
uv run complydoc cost ./invoices -m claude-opus-5 -m claude-haiku-4-5
```

`uv run complydoc models` lists what is configured and how current each price is.
`uv run complydoc doctor` prints what is installed and what is missing.

Inputs: PDF (native text and scanned), PNG, JPG, TIFF, BMP, DOCX, XLSX. Folders are recursed. Files that cannot be opened are skipped and listed in the report.

## Optional extras

The base install covers cost and difficulty. Two extras add the heavier paths:

```bash
uv sync --extra ocr                          # read scanned pages (RapidOCR, no system binary)
uv sync --extra ner                          # person and organisation names
uv run python -m spacy download en_core_web_sm
```

Both download their models once at install time. Nothing is fetched during a scan. When an extra is absent, the affected pages and categories are listed individually in the report's limitations rather than counted as clean.

Tokenizer vocabularies are vendored into the package, because tiktoken otherwise fetches them on first use and the guard blocks that.

## What it measures

### Cost

Per document: page count, page dimensions, DPI, whether a text layer exists and what fraction of the page it covers, text tokens from a real tokenizer, and vision tokens at each resolution preset.

Vision token formulas differ by provider — some tile the image, some use a width by height formula, some charge a flat count per image — so all three shapes live in `pricing.yaml` rather than in code.

Two paths are costed separately: text extraction and vision. Where a path does not exist, complydoc reports it as not applicable rather than as zero. A scan has no text layer; a spreadsheet has no fixed page size.

Only input cost is estimated. Output length depends on the prompt, which this tool does not know.

> [!NOTE]
> Prices carry a `last_verified` date per entry. The report prints it and warns past 90 days; an entry with no date warns on every run. Anthropic prices ship with a sourcing date. OpenAI and Google entries ship as disabled templates with the formula filled in and the price left `null`, because those were not sourced when the config was written.

Prices for other providers can be generated from litellm's model price table, which
covers a few thousand models:

```bash
uv run complydoc pricing-import --provider openai --limit 5
uv run complydoc pricing-import -m gpt-4o -m gemini/gemini-2.0-flash
```

That prints YAML to paste under `models:`, with `last_verified` set to the date you ran it
and `source_url` pointing at litellm. litellm is not a runtime dependency and is never
imported during an audit — only its data file is read, from an installed copy or a path you
give with `--from`. It carries token prices but not vision formulas, so the importer maps
each provider onto one of the three shapes in `vision_formulas`.

### Extraction difficulty

Eighteen signals, each reported as a row with the measured value, a rating, and one sentence on why it matters. The table is the primary output.

Coverage thresholds are calibrated against `tests/fixtures/dense_text.pdf`, a full page of
prose at ordinary density, which measures 65%. A page at 10pt with 22mm margins covers
55-70%; an invoice with a lot of white space sits near 15-25%; below 10% the page is
effectively a picture with a caption.

Measured: text layer presence and coverage, image area proportion, garbled character rate, table count, header depth and merged cells, column layout, page rotation, estimated skew, scan DPI, font count and embedding, date format consistency, page size variance, detected language, encryption, and AcroForm fields, which are rated as a positive signal.

A weighted score is also produced. Every weight lives in `difficulty.yaml` and is printed next to its row; the config schema rejects a configuration that enables scoring with `print_weights_in_report: false`. Signals that cannot be measured are excluded from the score rather than counted as failures, and a score resting on fewer than half the signals is marked low confidence.

### Page layout preview

Each page is drawn in the HTML report as a wireframe: grey blocks where the words are,
amber where images are, and a red or amber outline around every sensitive value that could
be placed. It answers which pages are expensive and where the risk sits, at a glance.

By default it is geometry only — no pixel of the page and no character of its text is
reproduced, because a thumbnail would undo the masking and the report is meant to be
forwardable. `--page-images` puts the rendered page beside the wireframe so you can compare the
document against what was extracted from it. `--extracted-text` adds the text read off each
page, which is where you check whether a low score is the document's fault or the
extractor's. Both put document content into the report and both stamp it at the top.

Matches that cannot be tied back to a position are counted and reported as unplaced rather
than dropped; DOCX and XLSX carry no word geometry, so everything in them is unplaced.

A run of words spanning most of the page width, or several line heights, is rejected as a
placement. On a two-column page the extraction order crosses the gutter, and a box drawn
from that would point at the wrong place.

### Sensitive information

National Insurance numbers, sort codes, bank account numbers, IBANs, payment cards, postcodes, street addresses, emails, phone numbers, dates of birth, VAT numbers, UTRs, and person and organisation names from a local NER model.

Checksums filter false positives: Luhn for cards, ISO 13616 mod-97 for IBANs, mod-97 for VAT numbers, prefix rules for NI numbers. Patterns too generic to stand alone, such as a bare eight-digit account number, are only reported when a label appears within a configurable window, and the report names the label that justified each one.

Pages with no readable text are listed by page number and excluded from the counts, so a page that was never read is distinguishable from a page with nothing on it.

> [!WARNING]
> Tables are found from their ruling lines, so a table whose columns are aligned with
> whitespace alone — which is how most invoices are laid out — is not detected. A count of
> zero means "no ruled tables", not "no tabular data", and the report says so.

> [!IMPORTANT]
> Values are masked by default. The report gives counts and locations, and shows at most the last four characters of any identifier. `--reveal` unmasks them and stamps the report; categories listed under `masking.never_reveal` in `sensitive.yaml` — card numbers and NI numbers by default — stay masked even then.
>
> Detectors return character spans, not strings. `sensitive/masking.py` holds the only function that turns a span into readable text.

## Output

Every run writes both formats.

`complydoc.json` is sorted and stable, so two runs can be compared with `diff`. It carries a schema version and a digest of the config that produced it, so a changed number is attributable to either the documents or the config.

`complydoc.html` is a single file with no external assets. It has a per-document section and an aggregate section.

Both carry a limitations section built from the run itself — which pages could not be read, which detectors were unavailable, which signals did not apply, which prices are unverified. It is generated, not a fixed disclaimer, so it changes when the run changes. Enabling `--ocr` removes the unread-pages entry because those pages were then read.

## Configuration

Three files under `src/complydoc/config/`, overridable together with `--config-dir`:

| File | Contents |
| --- | --- |
| `pricing.yaml` | Model prices, vision token formulas, resolution presets, `last_verified` dates |
| `difficulty.yaml` | Signal weights, rating thresholds, scoring rules |
| `sensitive.yaml` | Detection patterns, validators, severities, masking rules |

Every number that appears in a report comes from these files.

## Adding a signal or a detector

Add one file under `src/complydoc/difficulty/signals/` with an `@signal` decorated class, and a weight block in `difficulty.yaml`. The package is walked at import time, so there is no central list to update. Detectors work the same way with `@detector`, and file format loaders with `register`.

```python
@signal
class ScanDpiSignal:
    id = "scan_dpi"
    name = "Scan resolution"
    unit = "DPI"
    why = (
        "Below roughly 200 DPI the strokes that separate similar characters start to "
        "disappear, so OCR begins confusing digits in exactly the fields — amounts, "
        "account numbers, dates — where a single wrong character matters most."
    )
    applies_to = frozenset({DocumentFormat.PDF, DocumentFormat.IMAGE})

    def measure(self, document: Document) -> Measurement: ...
```

A signal that cannot measure its property returns `Measurement.na(reason)`. The reason is carried into the report's limitations.

## Development

There is a Makefile; `make` on its own lists the targets.

```bash
make install-all      # base, plus OCR and the local NER model
make check            # lint, types, tests — what CI runs
make audit DOCS=~/invoices OUT=~/audit VOLUME=2500
make fixtures         # rebuild the committed test fixtures
make diagrams         # re-export the README diagrams
```

Or directly:

```bash
uv sync --group dev
uv run pytest
uv run ruff check src tests && uv run mypy src/complydoc
```

Fixtures are committed and include a scanned page, a three-row merged header table, a two-column layout, a scan that is both skewed and rotated 90 degrees, an encrypted PDF, one with a deliberately corrupted ToUnicode map, one with mixed page sizes, a fillable form, and a file that is not a valid PDF.

Every identifier in the synthetic PII fixture is fake: a published test card number, the IBAN from the ISO 13616 specification, an Ofcom fiction-range phone number, and invented names.

## Licence

MIT
