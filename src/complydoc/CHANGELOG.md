# Changelog

Notable changes, newest first. Versions follow [semantic versioning](https://semver.org):
the major number changes when a report's JSON shape or a config file's meaning breaks,
the minor number when something is added, the patch number when a measurement is
corrected. `schema_version` in the JSON is versioned separately and is the field to
branch on when reading reports programmatically.

## [Unreleased]

### Changed

- Cost is off the front page. The tile and the per-1,000 chart move to the Cost
  tab, which is what that tab is for, and the chart leads it. An audit's front
  page should answer whether these documents can be used, not what the pipeline
  would bill — the price only matters once the answer to the first question is
  yes. The only figure left is what a quick win would save, which is the reason
  to act on it rather than a cost breakdown.

### Added

- Global readiness, on the front page as a ring. AI readiness asks whether the
  text can be got off the page; this asks whether the folder can be put through
  a pipeline at all, combining content with the cost path it forces and what it
  carries that should not leave. Weights are in `readiness.yaml` and printed
  beside the score. A factor the run did not measure is dropped and the rest
  renormalised — never counted as nought — and the report says how many of the
  three it was built from.
- The ring shows the composition rather than the score, because the mean hides
  the tail: a folder averaging 71 can still hold two documents nothing can be
  read from, and those two are the ones somebody has to deal with.
- Quick wins: what to do next, ranked by how much of the folder each touches.
  Every entry names the documents it applies to, says whether complydoc can do
  it or a person has to, and where the consequence follows from prices already
  in the report it is computed — the OCR entry quotes what those documents cost
  today on the image path. None of them predicts a score, because signals
  interact and the only honest way to know is to fix the documents and run the
  audit again.
- Every sensitive finding carries an evidence tier: `confirmed` when a checksum
  passed, `corroborated` when a label sits beside it, `pattern` for a shape
  alone, and `model` for a statistical guess. The security table shows it and
  breaks a severity tie on it, so a confirmed card number sorts above a name a
  model thought it saw.

### Changed

- The model detector reports no confidence rather than 1.0. The small English
  pipeline exposes no per-entity score, so recording one put a guess level with
  a passed checksum — the one place this tool was reporting a number that meant
  something other than what it said. `confidence` is now null there, and the
  `min_confidence: 0.5` configured for names and organisations is gone: it
  filtered nothing and implied a threshold that was never applied.
- `schema_version` is 3. The report carries `overall` and `quick_wins`, every
  sensitive match carries `evidence`, and `confidence` on a match may be null.

- The summary quotes Claude Sonnet 5 rather than whichever model happened to be
  cheapest. The cheapest was a moving target — it changed with a catalogue
  refresh rather than with the folder — and it flattered the estimate with a
  model few people would actually run. `compare.headline_model` in
  `pricing.yaml` sets it, and the report falls back to the cheapest priced model
  and still names it when that one is not in the comparison.
- A model that carried its own id as its name now borrows the catalogue's, so
  the chart no longer reads `zai/glm-5.3-flash` beside `Claude Sonnet 5`. The
  seven curated entries that were written that way are fixed as well.
- How many documents each architecture reaches is stated once per architecture
  in the legend, instead of beside every bar. On a dozen models that was ninety
  copies of three numbers, crowding out the figures that differ. It stays on
  each bar's own hover.
- The explanation of a sensitive mark follows the mark instead of appearing
  under the page, and there is one of it. The mark used to carry an SVG
  `<title>` as well, which is the browser's own tooltip, so pointing at a mark
  drew the same words twice in two different boxes. The mark now carries an
  `aria-label`, which says the same thing to a screen reader without drawing
  anything.
- A mark says what was found, masked exactly as the findings table masks it —
  the last few characters, with the separators kept so the shape stays legible.
  A rectangle and a category left the reader hunting for which item it was.
  `--reveal` puts the whole value there as it does everywhere else.
- The summary tiles say one thing each. The heading above the first chart no
  longer repeats the tile directly above it.

### Fixed

- `.complydoc`, where a run writes when nobody passes `--out`, is git-ignored.
  Those reports carry the text read off each page and a picture of every page,
  so a default run inside a repository was leaving document content untracked
  in the working tree.

## [0.2.0] — 2026-09-10

### Added

- `complydoc compare <path>` runs an audit with every reader and every OCR
  engine installed, so comparing does not mean naming each one by hand. It says
  which it is using before it starts, and says so plainly when there is nothing
  installed to compare against.
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
- A third reader for a PDF's text layer, `pypdf`. It is already a dependency,
  so it costs no install and no measurable time, and it shares no code with
  either of the others — which is the only reason a third reading is worth
  having. It returns text and no geometry, so it reports coverage as not
  measured rather than as nought per cent, and the findings that need boxes say
  the same.
- OCR engines are pluggable the same way, with `--ocr-engine`,
  `--compare-ocr-engine` and `complydoc engines`. Tesseract is included for anyone
  who already has it; it is not a dependency, because it needs a system binary.
- Where two readers parted company is now shown, not just measured. Each other
  reader's pane carries its own text with the words only it found underlined
  and the words only the kept reader found struck through, so the difference is
  read in place rather than by flipping between two panes and holding both in
  your head. The page bar gains a control that jumps to the next page the
  readers read differently, which on a long document is a handful of pages
  among hundreds.
- The report tells a reader that walked a page in the wrong order apart from
  one that read different words. They look the same to any similarity score and
  they call for different things: the first scrambled a page it could read, the
  second could not read part of it.
- A live bar, count and clock while a folder is read. A run over a few hundred
  documents takes minutes, and a terminal that says nothing for minutes is
  indistinguishable from one that has hung. A pipe still gets one line per
  document, and `--quiet` still gets nothing.
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
- `--save-text <dir>` keeps the text complydoc read, one file per document. Reading a
  scanned folder is the slow part of an audit and it was being thrown away, so the next
  tool to want the text ran OCR over the same pages again.
- The summary says how long the work took by stage — reading, OCR, signals, identifier
  scan — and what the measured rate means for 100, 1,000, 10,000 and 100,000 documents.

### Changed

- The difficulty component is called readiness. A high score always meant a document
  that was easy to process, which read backwards under a name promising the opposite.
  The command is `complydoc readiness`, the config file is `readiness.yaml`, the JSON
  carries `readiness` where it carried `difficulty`, and `schema_version` is 2. The
  score bands read the same way round as the number now: ready, workable, needs work,
  not ready. Signal directions are `higher_is_better` and `lower_is_better`.
- The Documents page is a page viewer rather than a grid of the first twelve pages.
  Every page of a document is reachable, by stepping or by typing a page number, and
  the page sits beside the text that was read off it instead of in a separate tab.
  The two halves are one row of equal height and each scrolls inside its own frame.
- The Documents page is the file list and the two panels, and nothing else. The
  folder-wide table of readiness signals, the per-document summary line and the list
  of poorly rated signals moved to that document's own Signals tab, where they answer
  a question the reader has actually asked.
- The text read off each page is in the report by default. Reading a page beside what
  was extracted from it is the point of the tool, and it was behind a flag. The report
  says on its security page that the masking covers the findings table and not the file,
  since the file now reproduces the pages those values were read off.
  `--no-extracted-text` restores a report with no document content.
- Sensitive marks on the page layout explain themselves on hover: what was found, why it
  was reported, and why that matters. The value itself is never in the explanation.
- Readings are compared by word rather than by character, and spacing is no
  longer a difference. Every reader breaks lines somewhere slightly different,
  and counting that marked every page of every document. One measure now backs
  both the number in the table and the marks on the page.
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
- `complydoc pricing-import` reads the vendored table, so it works without litellm
  installed, and the entry it generates is marked `price_source: imported` rather than
  being stamped with a `last_verified` date nobody earned.

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

### Fixed

- Two extractors that read a page in a different order are now reported as
  disagreeing. The comparison used to be a character count, which cannot see the
  case it most needs to: on a two-column page, one library reads down the columns
  and another straight across, interleaving every sentence, and both return the
  same number of characters. Readings are now compared in order, and the report
  names the kind of difference rather than only that there was one.
- Pointing at a sensitive mark on the page layout does something. The marks are drawn
  as outlines, and an SVG shape with no fill answers the pointer only along its stroke —
  on a mark six pixels tall that is two hairlines, so hovering the middle of one hit
  nothing. The explanation also appears under the page at once rather than waiting for
  the browser's own tooltip, and the marks can be tabbed to.
- DOCX merged cells were counted by object identity, which made the count depend on
  memory reuse and differ between processes reading the same file. They are read from
  the markup now.
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

### Documentation

- The README is written for someone running the tool: what it does, how to run it, what the
  flags mean. Architecture, adding a signal, fixtures and the release process moved to
  CONTRIBUTING.md, and this changelog now ships inside the package, so an installed copy can
  say what changed in the version you have.
- The README says how to keep an installed copy up to date, and why `--reinstall`
  matters as much as `--force`.

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

[Unreleased]: https://github.com/duartecaldascardoso/complydoc/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/duartecaldascardoso/complydoc/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/duartecaldascardoso/complydoc/releases/tag/v0.1.0
