---
name: complydoc
description: Audit a folder of documents offline for LLM processing cost, extraction readiness, and personal or financial identifiers (national IDs across the UK, US and EU, payment cards, IBANs, bank details). Use when asked what documents would cost to process with an LLM, how ready they are to extract from, whether a folder contains personal data, or to check documents for PII before sending them anywhere. Runs locally and makes no network calls.
---

# complydoc

`complydoc` audits a folder of business documents and reports three things: what they
would cost to process with an LLM, how ready they are for extracting structured data from,
and which personal or financial identifiers they contain. It makes no network calls, so
it is safe to run on material that must not leave the machine.

## Running it

```bash
complydoc <path> --print-json
```

`--print-json` puts the report on stdout and nothing else; progress goes to stderr.
Parse stdout. Without it, the tool writes `.complydoc/complydoc.{html,json}` and prints
both paths.

Run `complydoc` with no arguments to audit the current directory.

| Command | Scope |
| --- | --- |
| `complydoc audit <path>` | All three components |
| `complydoc cost <path>` | Cost only |
| `complydoc readiness <path>` | Extraction readiness only |
| `complydoc sensitive <path>` | Identifiers only |
| `complydoc models` | Which models can be priced against |
| `complydoc doctor` | What is installed |

Flags worth knowing: `--monthly-volume N` extrapolates cost, `--model <id>` (repeatable)
narrows the comparison, `--no-ocr` is faster, `--out <dir>` moves the reports,
`--password <pw>` is tried on encrypted PDFs, `--no-extracted-text` leaves the
document content out of the report.

On a folder large enough to be slow, `--jobs 0` spreads the work over every CPU and
`--sample N` audits N documents instead of all of them. Prefer `--jobs`: it changes only
how long the run takes. Reach for `--sample` when the user has accepted a partial answer,
and say in your reply that the figures describe a sample.

Exit code 0 means the run completed, 2 means the arguments or config were wrong. A run
that finds problems still exits 0 — the findings are in the JSON.

## Reading the JSON

```bash
complydoc sensitive ./invoices --print-json | jq '{
  high: [.documents[].sensitive.matches[] | select(.severity=="high")] | length,
  unread: [.documents[] | select(.sensitive.unreadable_pages|length>0) | .relative_path],
  important: [.limitations[] | select(.severity=="important") | .area]
}'
```

- `run.components_run` — which components actually ran.
- `run.offline_guard` — `armed` means nothing could have left the machine.
- `aggregate.sensitive_by_category` / `sensitive_by_severity` — folder totals.
- `documents[].readiness.score` — 0-100, higher is better; check `low_confidence`.
- `documents[].sensitive.matches[]` — `category`, `region`, `page`, `line`, `masked`,
  `severity`.
- `documents[].cost.models[]` — token counts and USD per model, with `last_verified`
  and `is_stale` on the price.
- `aggregate.seconds_per_document` / `hours_per_1000_documents` — measured local
  preparation time, and `ocr_pages_per_second` where OCR ran.
- `limitations[]` — what this run could not establish, generated from the run itself.

`complydoc schema` prints the full shape.

## What is easy to get wrong

**Zero is not always zero.** A page in `sensitive.unreadable_pages` was never read. A
category in `aggregate.categories_not_scanned` was never searched for. Both report zero
and neither is an all-clear. Say so when reporting a clean result.

**Values are masked; the report is not.** `masked` shows at most the last four
characters, and that is what to quote. But the report carries the text read off each
page by default, so the file itself holds those values in full whether or not
`--reveal` was passed — treat it as you would treat the documents. `--no-extracted-text`
produces a report with no document content in it. Only pass `--reveal` if the user
explicitly asks for unmasked values in the findings table.

**Costs are input tokens only.** Output cost depends on the prompt, which complydoc
cannot know, so the real bill is higher. Prices carry `last_verified`; report a stale
price as stale rather than quoting it plainly.

**A table found by alignment reports less than a ruled one.** Tables drawn with ruling
lines give up their header depth and merged cells; a table held together by whitespace
alone carries nothing to read those from, so they come back null rather than zero.

**A sampled run does not describe the folder.** When `run.sampled_from` is set, every
total, monthly figure and count covers only the documents that were read. Report them as
a sample of that many out of `run.sampled_from`, never as the folder's totals.

**Timing is local only.** `seconds_per_document` is the cost of reading and analysing a
document on this machine, before anything reaches a model. Time on the model is null
unless someone has configured a measured throughput.

## Reporting back

Lead with the three figures a decision rests on: cost per 1,000 documents, the mean
readiness score, and how many documents hold sensitive data. Then name anything in
`limitations[]` marked `important`, because those are the things that would change the
conclusion. Do not print identifier values.
