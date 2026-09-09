# Contributing to complydoc

## Getting set up

```bash
make install-all   # dependencies, both optional extras, and the spaCy model
make check         # lint, types, tests — what CI runs
make               # list every target
```

`make tool` installs the working tree as a global `complydoc`. It passes `--reinstall`
as well as `--force`, because uv otherwise reuses the wheel it already built for this
version number and an edit that leaves the version alone is silently ignored.

## How it is put together

Documents pass through discovery and a per-format loader into the normalised `Document`
model, and everything downstream reads that rather than touching a PDF directly. The three
analysis components are independent: asking for only the sensitive scan loads no tokenizer
and computes no cost.

| Path | What lives there |
| --- | --- |
| `ingest/` | Per-format loaders behind one `Loader` protocol |
| `readiness/signals/` | One file per signal, registered by decorator |
| `sensitive/detectors/` | Regex, checksum and NER detectors, same pattern |
| `cost/` | Tokenizers, vision formulas, the price catalogue |
| `report/` | JSON, HTML, the page previews and the generated limitations |
| `config/` | Every number that appears in a report |

`offline.py` replaces the standard library's outbound socket and DNS entry points before any
file is opened. `tests/test_offline_guard.py` runs a full audit with the guard armed. Nothing
may reach the network at run time, and a dependency that tries fails the run loudly rather
than succeeding quietly.

### The scripts folder

Three maintenance programs, none of which ship in the wheel and none of which run during an
audit. Each is reachable through a `make` target:

| Script | Target | What it does |
| --- | --- | --- |
| `build_price_table.py` | `make prices` | Refreshes the vendored model catalogue |
| `build_sbom.py` | `make sbom` | Writes a CycloneDX bill of materials from the lockfile |
| `build_diagram.py` | `make diagrams` | Re-exports the README architecture diagram |

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
carried into the report. That distinction matters more than it looks: a signal that returns
zero because it could not look is a false measurement, and the report is built to keep the
two apart.

## Tests and fixtures

```bash
make test
make fixtures   # rebuild the committed fixtures from tests/generate_fixtures.py
```

The fixtures are committed so the suite does not depend on a PDF writer's output staying
byte-stable; CI checks the generator still produces every one of them. They include a scanned
page, a three-row merged header table, a two-column layout, a whitespace-aligned table, a
scan both skewed and rotated, an encrypted PDF, one with a corrupted ToUnicode map, mixed
page sizes, a fillable form, and a file that is not a valid PDF.

Every identifier in the synthetic PII fixture is fake: a published test card number, the IBAN
from the ISO 13616 specification, an Ofcom fiction-range phone number, and invented names.

Two habits worth keeping, both learned from breaking them:

- Assert on behaviour, not on rendered output. A test that reads the CLI's help text or a
  Rich table passes locally and fails on CI, because both wrap at the width of whatever
  terminal is running them.
- A number in a test that came from tuning against the fixtures is a number that will be
  wrong on real documents. Measure real pages before calibrating a threshold.

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
checksums, signs build provenance for each artefact, and opens a draft release. The tag has
to match `complydoc.__version__` and `src/complydoc/CHANGELOG.md` has to have an entry for
it, or the build stops before producing anything — a report that names a version the artefact
does not carry would be worse than no release. Verify a downloaded artefact with:

```bash
gh attestation verify complydoc-0.2.0-py3-none-any.whl --repo duartecaldascardoso/complydoc
```

GitHub does not store attestations for a user-owned private repository, so while this
repository is private the release ships `SHA256SUMS` and the SBOM without a signed provenance
statement, and says so in its notes.

## Keeping prices current

```bash
make prices    # refresh the vendored catalogue from models.dev and litellm
```

Every entry it writes is marked `imported`, not `verified`, because nobody checked it against
the provider's own page. That distinction is load-bearing: an imported price stays out of
staleness warnings, and a report that prices against one says so in its limitations. To
promote one, check the number at the source and replace `price_source`/`imported_on` with a
`last_verified` date.
