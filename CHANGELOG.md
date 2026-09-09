# Changelog

Notable changes, newest first. Versions follow [semantic versioning](https://semver.org):
the major number changes when a report's JSON shape or a config file's meaning breaks,
the minor number when something is added, the patch number when a measurement is
corrected. `schema_version` in the JSON is versioned separately and is the field to
branch on when reading reports programmatically.

## [Unreleased]

### Changed

- The Documents page is a page viewer rather than a grid of the first twelve pages.
  Every page of a document is reachable, by stepping or by typing a page number, and
  the page sits beside the text that was read off it instead of in a separate tab.

### Fixed

- DOCX merged cells were counted by object identity, which made the count depend on
  memory reuse and differ between processes reading the same file. They are read from
  the markup now.

## [0.1.0]

First release.

### Audit

- Three independent components — cost, extraction difficulty, sensitive data — run
  together or one at a time. The report states which of them ran.
- Cost estimated from measured page geometry and a real tokenizer, across text, OCR and
  vision paths for every priced model. Vision formulas and prices live in
  `pricing.yaml` with a `last_verified` date; a price older than 90 days is reported as
  stale rather than quoted plainly.
- Nineteen difficulty signals, each contributing a measured value, a rating and one
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
