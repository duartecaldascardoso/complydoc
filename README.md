<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/images/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/images/logo-light.svg">
    <img alt="complydoc" src=".github/images/logo-light.svg" width="42%">
  </picture>
</div>

<div align="center">
  <h3>Offline document audit: LLM cost, extraction readiness, and personal data.</h3>
</div>

<div align="center">
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/license-MIT-1a7f4b" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-4f5d75" alt="Python versions">
  <img src="https://img.shields.io/badge/network-none%20at%20runtime-1a7f4b" alt="No network at runtime">
  <img src="https://img.shields.io/badge/tests-306-4f5d75" alt="Tests">
</div>

<br>

Point complydoc at a folder of business documents and it answers three questions: what they
would cost to process with an LLM, how ready they are to extract data from, and what personal
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

OCR and local name detection are optional extras, because they are a large download
and a diagnostic run is still useful without them. `complydoc doctor` says which of
them are present. To install both:

```bash
uv tool install --force --reinstall --with rapidocr-onnxruntime --with spacy \
  git+https://github.com/duartecaldascardoso/complydoc
uv pip install --python "$(uv tool dir)/complydoc/bin/python" \
  https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
```

The second line installs the spaCy model into the tool's own environment;
`spacy download` cannot, because it shells out to pip and a uv tool environment has
none. `complydoc doctor` says which extras it can see.

`uv tool install` copies the source as it stands, so a global `complydoc` does not
follow this repository — re-run the install to pick up changes, and pass
`--reinstall` as well as `--force`, or uv reuses the wheel it already built for this
version number and the update does nothing. From a checkout, `make tool` does all of
it and puts the extras back.

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
complydoc audit ~/invoices --page-images           # add a picture of each page
complydoc audit ~/invoices --no-extracted-text    # a report carrying no document content
complydoc models                                   # which models can be priced against
complydoc doctor                                   # what is installed
```

Inputs: PDF (native and scanned), PNG, JPG, TIFF, BMP, DOCX, XLSX. Folders are recursed.
Anything that cannot be opened is skipped and reported. OCR is on by default so scanned
pages are still readable; `--no-ocr` is faster.

On a large folder:

```bash
complydoc audit ~/invoices --jobs 1        # one process, for a reproducible profile
complydoc audit ~/invoices --sample 200    # 200 documents, keeping each file type's share
complydoc audit ~/invoices --password s3cret   # try this on encrypted PDFs
```

A folder large enough to be worth it is spread across the machine already: the run
reads how many documents there are and picks a worker count, and small folders stay
in one process because a worker costs more to start than a few documents take to
read. `--jobs N` overrides that. It changes how long the run takes and nothing about
what it finds. `--sample` does
change what it finds, so the report says on its front page that it read a sample and how
many documents it skipped. The choice is deterministic — two runs of the same folder pick
the same documents, so their reports compare.

## The report

One self-contained HTML file, four pages behind a tab bar.

| Page | Answers |
| --- | --- |
| **Summary** | Cost per 1,000 documents, average quality, preparation time, sensitive items per document |
| **Cost** | Every model across three processing architectures, filterable by provider |
| **Security** | What personal data is in there, by category and by occurrence |
| **Documents** | A file browser: every page beside the text read off it, with its signals a tab away |

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

**Readiness.** Nineteen signals, each with a measured value, a rating, and one sentence on
why it matters. Text layer and coverage, image proportion, garbled characters, tables and
merged cells, columns, rotation and skew, scan DPI, fonts, date consistency, page sizes,
language, encryption, and form fields — which count as a *positive* signal.

A weighted score is produced only because every weight is visible in `readiness.yaml` and
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
| `pricing.yaml` | Curated model prices, vision formulas, resolution presets, `last_verified` dates |
| `model_prices.json` | The current first-party models from models.dev, available to `--model` |
| `readiness.yaml` | Signal weights, rating thresholds, scoring rules |
| `sensitive.yaml` | Patterns, validators, regions, severities, masking rules |

Every number in a report comes from these files. To add models with current prices:

```bash
complydoc models --new 15               # the most recently released models
complydoc models gpt                    # or search the catalogue
complydoc models --provider openai      # or list one provider
complydoc pricing-import -m gpt-4.1-mini  # generate an entry to verify and paste
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

One file under `readiness/signals/` with an `@signal` decorated class, and a weight block in
`readiness.yaml`. The package is walked at import time, so there is no central list to
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

## Branches and releases

`main` holds released code and nothing else. Work lands on `development` first and reaches
`main` as one merge per release; both branches run the full check suite on every push.

Versions are semantic, and what each number means is decided by what a reader of an old
report would notice:

| Change | Bump |
| --- | --- |
| The JSON shape breaks, or a config key changes meaning | Major |
| A signal, detector, model or flag is added | Minor |
| A measurement, threshold or price is corrected | Patch |

The JSON carries its own `schema_version`, which is the field to branch on when reading
reports programmatically — it moves only when the shape does.

Releases are cut by tagging `main`:

```bash
make release-check       # version, changelog and working tree agree
git tag -a v0.2.0 -m "complydoc v0.2.0"
git push origin v0.2.0
```

The tag builds the wheel and sdist, writes a CycloneDX SBOM from the lockfile, records
checksums, signs build provenance for each artefact, and opens a draft release. The tag
has to match `complydoc.__version__` and the changelog has to have an entry for it, or
the build stops before it produces anything — a report that names a version the artefact
does not carry would be worse than no release. Verify a downloaded artefact with:

```bash
gh attestation verify complydoc-0.2.0-py3-none-any.whl --repo duartecaldascardoso/complydoc
```

GitHub does not store attestations for a user-owned private repository, so while this
repository is private the release ships `SHA256SUMS` and the SBOM without a signed
provenance statement, and says so in its notes.

## Licence

MIT
