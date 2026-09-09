# Changelog

Notable changes, newest first. Versions follow [semantic versioning](https://semver.org):
the major number changes when a report's JSON shape or a config file's meaning breaks,
the minor number when something is added, the patch number when a measurement is
corrected. `schema_version` in the JSON is versioned separately and is the field to
branch on when reading reports programmatically.

## [Unreleased]

### Added

- A vendored model catalogue from models.dev: every current model from the eight
  first-party providers, so `--model` reaches one without anyone having hand-written an
  entry for it. `complydoc models --new N` lists the most recently released, because an
  alphabetical dump sorts a two-year-old model above this month's. It is data on disk —
  a run still reaches no network — and `make prices` refreshes it. Imported prices are
  marked as imported, kept apart from the handful someone verified against a provider's
  page, and a report that prices against one says so in its limitations.
  Batch prices come from litellm, the only one of the two sources that publishes them.
- Batch pricing, where the provider publishes one. The cost page shows what the same
  tokens cost through a batch endpoint beside the interactive price. Never inferred from
  the customary half price: a discount nobody can check does not belong in a budget.

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
