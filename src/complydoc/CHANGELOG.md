# Changelog

Notable changes, newest first. Versions follow [semantic versioning](https://semver.org):
the major number changes when a report's JSON shape or a config file's meaning breaks,
the minor number when something is added, the patch number when a measurement is
corrected. `schema_version` in the JSON is versioned separately and is the field to
branch on when reading reports programmatically.

## [Unreleased]

### Fixed

- Two extractors that read a page in a different order are now reported as
  disagreeing. The comparison used to be a character count, which cannot see the
  case it most needs to: on a two-column page, one library reads down the columns
  and another straight across, interleaving every sentence, and both return the
  same number of characters. Readings are now compared in order, and the report
  names the kind of difference rather than only that there was one.

### Added

- A third reader for a PDF's text layer, `pypdf`. It is already a dependency,
  so it costs no install and no measurable time, and it shares no code with
  either of the others — which is the only reason a third reading is worth
  having. It returns text and no geometry, so it reports coverage as not
  measured rather than as nought per cent, and the findings that need boxes say
  the same.


- Extractors are pluggable, and more than one can run in a single pass.
  `--extractor` picks which library reads the text layer; `--compare-extractor`
  reads every page with a second one as well and reports where the two differ.
  Only the first reaches a finding — the rest are measured, never adopted.
  Comparison lives inside a run, so it is the same page on the same machine at the
  same moment rather than two runs that would differ for reasons of their own.
  `complydoc extractors` lists them. With `--extracted-text` on, what each reader made
  of a page is kept, so the Documents page can switch between them and show the text
  itself rather than only how much of it there was.
- pdfium as a second extractor: measured against pdfplumber on a real 392-page book
  the two agree on the text within one to two per cent, and pdfium reads it about
  thirteen times faster. It provides no table structure and a box per line rather
  than per word, so the signals that need those report that they could not measure
  rather than returning a number that means something else.
- OCR engines are pluggable the same way, with `--ocr-engine`,
  `--compare-ocr-engine` and `complydoc engines`. Tesseract is included for anyone who already has it; it is
  not a dependency, because it needs a system binary.

- `--save-text <dir>` keeps the text complydoc read, one file per document. Reading a
  scanned folder is the slow part of an audit and it was being thrown away, so the next
  tool to want the text ran OCR over the same pages again.
- The summary says how long the work took by stage — reading, OCR, signals, identifier
  scan — and what the measured rate means for 100, 1,000, 10,000 and 100,000 documents.

### Added

- A vendored model catalogue from models.dev: every current model from the eight
  first-party providers, so `--model` reaches one without anyone having hand-written an
  entry for it. `complydoc models --new N` lists the most recently released, because an
  alphabetical dump sorts a two-year-old model above this month's. It is data on disk —
  a run still reaches no network — and `make prices` refreshes it. Imported prices are
  marked as imported, kept apart from the handful someone verified against a provider's
  page, and a report that prices against one says so in its limitations.
  Batch prices come from litellm, the only one of the two sources that publishes them.
- The report compares three models per provider rather than whichever ten had been
  written down, so every provider is represented and two of them are no longer missing
  altogether. Each provider is topped up from the catalogue with its most recently
  released models that take images; `compare.per_provider` in `pricing.yaml` sets the
  number. A refreshed catalogue brings a refreshed comparison.
- Batch pricing, where the provider publishes one. The cost page shows what the same
  tokens cost through a batch endpoint beside the interactive price. Never inferred from
  the customary half price: a discount nobody can check does not belong in a budget.

### Fixed

- Pointing at a sensitive mark on the page layout does something. The marks are drawn
  as outlines, and an SVG shape with no fill answers the pointer only along its stroke —
  on a mark six pixels tall that is two hairlines, so hovering the middle of one hit
  nothing. The explanation also appears under the page at once rather than waiting for
  the browser's own tooltip, and the marks can be tabbed to.
- The OCR engine registers its own shutdown cleanup, at the point it creates the
  native threads, instead of relying on another module importing it during
  interpreter teardown — when the import machinery may already be gone, and a run
  that had already succeeded aborts with a mutex error.
- The file list sat in the right place only some of the time. `.spread:not([hidden])` also
  matched a panel hidden along with the whole Pages view, because the attribute sits on the
  container, so the list was being centred on a zero-height ghost whenever the signals tab
  was showing. It also now re-aligns when a page is first shown, which it could not do while
  it was hidden.
- An imported price is no longer reported as a verification that went stale. It was
  never claimed to be verified, and warning once per model buried the run's real
  limitations under a dozen copies of what the provenance entry says once.

### Changed

- `complydoc pricing-import` reads the vendored table, so it works without litellm
  installed, and the entry it generates is marked `price_source: imported` rather than
  being stamped with a `last_verified` date nobody earned.
- The text read off each page is in the report by default. Reading a page beside what
  was extracted from it is the point of the tool, and it was behind a flag. The report
  says on its security page that the masking covers the findings table and not the file,
  since the file now reproduces the pages those values were read off.
  `--no-extracted-text` restores a report with no document content.
- Sensitive marks on the page layout explain themselves on hover: what was found, why it
  was reported, and why that matters. The value itself is never in the explanation.
- The difficulty component is called readiness. A high score always meant a document
  that was easy to process, which read backwards under a name promising the opposite.
  The command is `complydoc readiness`, the config file is `readiness.yaml`, the JSON
  carries `readiness` where it carried `difficulty`, and `schema_version` is 2. The
  score bands read the same way round as the number now: ready, workable, needs work,
  not ready. Signal directions are `higher_is_better` and `lower_is_better`.

### Documentation

- The README is written for someone running the tool: what it does, how to run it, what the
  flags mean. Architecture, adding a signal, fixtures and the release process moved to
  CONTRIBUTING.md, and this changelog now ships inside the package, so an installed copy can
  say what changed in the version you have.

### Performance

Measured on this machine: a folder of 102 documents 17.6s to 10.9s with OCR and
7.4s to 2.9s without, a 392-page book 56.9s to 31.0s.

- Skew was measured by rotating the whole page once per candidate angle. The same
  measurement falls out of projecting the ink pixels, which are a tenth of the page,
  and a coarse pass now finds the degree before the fine pass refines it.
- The entity model loaded a tagger, a dependency parser and a lemmatiser that nothing
  reads, and parsed every page once per category rather than once.
- The whitespace table pass pulled the text out of every candidate before applying the
  geometric test that rejects almost all of them. The cheap test runs first now, and it
  reuses the words the page has already been asked for instead of clustering its
  characters into words a second time.
- Worker processes fork from a server that has loaded the models, instead of each
  loading its own copy, and the number of them is chosen from the size of the folder.

### Changed

- The Documents page is a page viewer rather than a grid of the first twelve pages.
  Every page of a document is reachable, by stepping or by typing a page number, and
  the page sits beside the text that was read off it instead of in a separate tab.
  The two halves are one row of equal height and each scrolls inside its own frame.
- The report is laid out to the width of the window rather than a 60rem reading
  column, so the page and its text get the room.
- Findings on the security page arrive ordered by severity, and every column there
  can be sorted.
- The page heading repeating the folder path, the timestamp and the version is gone.
  All of it is recorded once, in the footer.
- The panels are one fixed frame, identical on every document and every page. Their
  height used to follow whichever page image was loaded, so the workspace resized
  every time you stepped a page or picked another file. A document nobody could open
  now draws the same workspace with the reason inside it, rather than a different
  block that resized the page on arrival.
- The file list sits at the height of the panels, not the column that holds them.
- Every page starts the same distance below the tab bar, whether or not it opens on
  a heading.
- The Documents page is the file list and the two panels, and nothing else. The
  folder-wide table of readiness signals, the per-document summary line and the list
  of poorly rated signals moved to that document's own Signals tab, where they answer
  a question the reader has actually asked.

### Fixed

- DOCX merged cells were counted by object identity, which made the count depend on
  memory reuse and differ between processes reading the same file. They are read from
  the markup now.

## [0.1.0]

First release.

### Audit

- Three independent components — cost, extraction readiness, sensitive data — run
  together or one at a time. The report states which of them ran.
- Cost estimated from measured page geometry and a real tokenizer, across text, OCR and
  vision paths for every priced model. Vision formulas and prices live in
  `pricing.yaml` with a `last_verified` date; a price older than 90 days is reported as
  stale rather than quoted plainly.
- Nineteen readiness signals, each contributing a measured value, a rating and one
  sentence saying why. Weights and thresholds are configuration, not code, and are
  printed alongside any score. A new signal is one new file plus a registration.
- Sensitive data scan covering national identifiers for the UK, US, IE, NL, PT, ES, FR
  and DE, EU VAT numbers, IBANs, payment cards and local NER for names and
  organisations, each with its own checksum or validator.
- Wall-clock time measured per document and projected to a backlog, including the
  observed OCR rate on the machine that ran it.

### Safety

- The network guard replaces the socket module's outbound entry points before any
  document is opened, in every process, and the test suite asserts a full audit
  completes with it armed. `run.offline_guard` records this in every report.
- Matched values are masked to the last four characters at most. `--reveal` prints them
  in full, and the report says on its face that it was used. Categories marked
  `never_reveal` stay masked regardless.

### Reports

- One self-contained HTML file — no network, no bundler, no server — with summary, cost,
  security and per-document pages, and a document browser showing each page beside what
  was extracted from it and what OCR read.
- A JSON report of the same run, and `--print-json` for piping into another tool.
- A limitations section generated from the run's own facts: what could not be opened,
  which pages held no readable text, which detectors were unavailable, which prices are
  unverified.

### Running it

- `complydoc` on its own audits the current directory.
- `--jobs` spreads documents over a process pool, `--sample` reads a deterministic
  type-proportional subset of a large folder, `--password` opens encrypted PDFs.
- A packaged agent skill, installed with the tool, so an agent can be told to use it.

[Unreleased]: https://github.com/duartecaldascardoso/complydoc/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/duartecaldascardoso/complydoc/releases/tag/v0.1.0
