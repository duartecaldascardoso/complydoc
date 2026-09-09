<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/images/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/images/logo-light.svg">
    <img alt="complydoc" src=".github/images/logo-light.svg" width="42%">
  </picture>
</div>

<div align="center">
  <h3>Offline document audit: LLM cost, extraction difficulty, and personal data.</h3>
</div>

<div align="center">
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/license-MIT-1a7f4b" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-4f5d75" alt="Python versions">
  <img src="https://img.shields.io/badge/network-none%20at%20runtime-1a7f4b" alt="No network at runtime">
  <img src="https://img.shields.io/badge/tests-306-4f5d75" alt="Tests">
</div>

<br>

Point complydoc at a folder of business documents and it answers three questions: what they
would cost to process with an LLM, how hard they are to extract data from, and what personal
or financial information they hold. It is a diagnostic you run before buying a document
automation system, not a pipeline you run in production.

**It makes no network calls.** `offline.py` replaces the standard library's outbound socket
and DNS entry points before any file is opened, and the test suite runs a full audit with
that guard armed. Every report records whether it was active.

<br>

<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/images/complydoc-architecture-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/images/complydoc-architecture.svg">
    <img alt="complydoc pipeline: documents pass through discovery and per-format loaders into three independent analysis components, which emit a JSON report and a self-contained HTML report, all inside a network guard boundary" src=".github/images/complydoc-architecture.svg" width="100%">
  </picture>
</div>

## Install

```bash
uv tool install git+https://github.com/duartecaldascardoso/complydoc
```

If `complydoc: command not found`, add uv's bin directory to your shell:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && exec zsh
```

## Use

```bash
cd ~/invoices
complydoc
```

That audits the folder you are standing in and writes `.complydoc/complydoc.html` and
`.complydoc/complydoc.json`, printing both as clickable links. The output directory is
hidden so a second run does not pick up the first run's reports.

```bash
complydoc audit ~/invoices --monthly-volume 2500   # extrapolate to a monthly bill
complydoc sensitive ~/invoices                     # only the identifier scan
complydoc audit ~/invoices --page-images           # show each page beside the extraction
complydoc models                                   # which models can be priced against
complydoc doctor                                   # what is installed
```

Inputs: PDF (native and scanned), PNG, JPG, TIFF, BMP, DOCX, XLSX. Folders are recursed.
Anything that cannot be opened is skipped and reported. OCR is on by default so scanned
pages are still readable; `--no-ocr` is faster.

## The report

One self-contained HTML file, four pages behind a tab bar.

| Page | Answers |
| --- | --- |
| **Summary** | Cost per 1,000 documents, average quality, preparation time, sensitive items per document |
| **Cost** | Every model across three processing architectures, filterable by provider |
| **Security** | What personal data is in there, by category and by occurrence |
| **Documents** | A file browser: each page, what was extracted, what OCR sees, what makes it hard |

The JSON is sorted and stable, so two runs can be compared with `diff`. It carries a schema
version and a digest of the config that produced it.

## What it measures

**Cost.** Page count, dimensions, DPI, text layer coverage, text tokens from a real
tokenizer, and vision tokens at each resolution. Vision formulas differ by provider — some
tile the image, some use width by height, some charge a flat count — so all three shapes live
in `pricing.yaml`, not in code.

Three architectures are compared: the **text layer** alone, **text plus local OCR**, and
**vision**. Cost alone favours the text layer, but it only reaches documents that have one,
so the number of documents each approach can serve is shown beside every figure.

Input cost only. Output depends on your prompt. Prices carry a `last_verified` date and the
report warns past 90 days.

**Time.** Reading and analysing a document is measured on the machine that runs the audit, so
the report quotes a rate it observed rather than one it assumed — per document, per page, and
the OCR throughput that dominates a folder of scans. That is the work before anything reaches
a model. Time *on* the model is not estimated by default: complydoc cannot benchmark a hosted
endpoint offline. Add `input_tokens_per_second` to a model in `pricing.yaml` from your own
benchmark and it will.

**Difficulty.** Eighteen signals, each with a measured value, a rating, and one sentence on
why it matters. Text layer and coverage, image proportion, garbled characters, tables and
merged cells, columns, rotation and skew, scan DPI, fonts, date consistency, page sizes,
language, encryption, and form fields — which count as a *positive* signal.

A weighted score is produced only because every weight is visible in `difficulty.yaml` and
printed beside its row. Signals that cannot be measured are excluded rather than counted as
failures.

> [!WARNING]
> Tables are found from their ruling lines, so a whitespace-aligned invoice table is not
> detected. A count of zero means "no ruled tables", not "no tabular data".

**Personal data.** Detection is not tied to one jurisdiction. Every national identifier is
checksum-validated, so enabling them all does not flood the report:

| Region | Identifiers |
| --- | --- |
| UK | National Insurance, sort code, account number, postcode, address, phone, VAT, UTR |
| US | Social Security number, EIN, ABA routing number |
| IE · NL · PT · ES · FR · DE | PPS, BSN, NIF, DNI/NIE, NIR, Steuer-ID |
| EU | VAT numbers, per country length rules |
| International | IBAN, payment cards, email, dates of birth, names and organisations |

Pages with no readable text are listed by number and excluded from the counts, so a page
nobody could read is distinguishable from a page with nothing on it.

> [!IMPORTANT]
> Values are masked by default — at most the last four characters. `--reveal` unmasks them
> and stamps the report; categories under `masking.never_reveal` stay masked even then.
> Detectors return character spans, not strings, and `sensitive/masking.py` holds the only
> function that turns one into readable text.

## Configuration

Three files under `src/complydoc/config/`, overridable with `--config-dir`:

| File | Contents |
| --- | --- |
| `pricing.yaml` | Model prices, vision formulas, resolution presets, `last_verified` dates |
| `difficulty.yaml` | Signal weights, rating thresholds, scoring rules |
| `sensitive.yaml` | Patterns, validators, regions, severities, masking rules |

Every number in a report comes from these files. To add models with current prices:

```bash
complydoc pricing-import --provider openai --limit 5
```

That reads litellm's price table and prints YAML to paste under `models:`, stamped with the
date you ran it. litellm is never imported at run time — only its data file is read.

## From an agent

```bash
complydoc audit ./invoices --print-json | jq '.aggregate'
```

`--print-json` puts the report on stdout and nothing else. complydoc ships an agent skill, so
one install gives you the tool and the instructions for driving it:

```bash
complydoc skill --install     # → ~/.claude/skills/complydoc/SKILL.md
```

## Adding a signal

One file under `difficulty/signals/` with an `@signal` decorated class, and a weight block in
`difficulty.yaml`. The package is walked at import time, so there is no central list to
update. Detectors work the same way with `@detector`, loaders with `register`.

```python
@signal
class ScanDpiSignal:
    id = "scan_dpi"
    name = "Scan resolution"
    unit = "DPI"
    why = "Below about 200 DPI, OCR starts confusing digits in amounts and accounts."
    applies_to = frozenset({DocumentFormat.PDF, DocumentFormat.IMAGE})

    def measure(self, document: Document) -> Measurement: ...
```

A signal that cannot measure its property returns `Measurement.na(reason)`, and the reason is
carried into the report.

## Development

```bash
make            # list targets
make check      # lint, types, tests
make audit DOCS=~/invoices VOLUME=2500
make fixtures   # rebuild the committed test fixtures
```

Fixtures include a scanned page, a three-row merged header table, a two-column layout, a scan
both skewed and rotated, an encrypted PDF, one with a corrupted ToUnicode map, mixed page
sizes, a fillable form, and a file that is not a valid PDF. Every identifier in the synthetic
PII fixture is fake: a published test card number, the IBAN from the ISO 13616 specification,
an Ofcom fiction-range phone number, and invented names.

## Licence

MIT
