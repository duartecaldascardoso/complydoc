# complydoc

An offline command-line tool that audits a folder of business documents and reports
three things:

1. **Cost** — what the documents would cost to process with an LLM.
2. **Difficulty** — how hard they are to extract structured data from.
3. **Sensitive information** — what UK GDPR relevant identifiers they contain.

It is a **pre-purchase diagnostic**, not a production pipeline. It is intended to be
run by a consultant, or by a UK finance or operations team on their own machine,
while evaluating whether document automation is worth buying.

## Trust proposition

**complydoc runs fully offline. No document content leaves the machine, ever.**

There is no hosted API call at runtime, and there is deliberately no opt-in flag to
add one. All tokenisation, layout analysis, OCR and named entity recognition run
against local libraries and local models. This is the whole point of the tool: it is
pointed at documents that an organisation has not yet decided it is willing to send
anywhere.

## Sensitive values are masked by default

The scan reports **counts and locations**, not values. A tool that flags a leaked
bank account number by printing it in a report that gets forwarded by email has made
the problem worse. Masked output shows at most the last four characters. A
`--reveal` flag exists for the case where someone genuinely needs the values, and any
report produced with it says so prominently.

## Supported inputs

PDF (native text and scanned), PNG, JPG, DOCX, XLSX. Folders are recursed. Files that
cannot be opened are skipped and reported, not fatal.

## Output

Every run produces both a JSON report (machine readable, diffable across runs) and a
self-contained HTML report with no external assets, which a non-technical reader can
open and forward.

Both reports carry a **limitations section generated from the run itself**, stating
what was not or could not be checked for those specific documents.

## Status

Design phase. Module structure and configuration schema are under review; no
implementation code has been written yet.

## Licence

MIT
