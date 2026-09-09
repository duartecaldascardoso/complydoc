---
name: complydoc
description: Audit a folder of documents offline for LLM processing cost, extraction difficulty, and personal or financial identifiers (national IDs across the UK, US and EU, payment cards, IBANs, bank details). Use when asked what documents would cost to process with an LLM, how hard they are to extract from, whether a folder contains personal data, or to check documents for PII before sending them anywhere. Runs locally and makes no network calls.
---

# complydoc

`complydoc` audits a folder of business documents and reports three things: what they
would cost to process with an LLM, how hard they are to extract structured data from,
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
| `complydoc difficulty <path>` | Extraction difficulty only |
| `complydoc sensitive <path>` | Identifiers only |
| `complydoc models` | Which models can be priced against |
| `complydoc doctor` | What is installed |

Flags worth knowing: `--monthly-volume N` extrapolates cost, `--model <id>` (repeatable)
narrows the comparison, `--no-ocr` is faster, `--out <dir>` moves the reports.

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
- `documents[].difficulty.score` — 0-100, higher is easier; check `low_confidence`.
- `documents[].sensitive.matches[]` — `category`, `region`, `page`, `line`, `masked`,
  `severity`.
- `documents[].cost.models[]` — token counts and USD per model, with `last_verified`
  and `is_stale` on the price.
- `limitations[]` — what this run could not establish, generated from the run itself.

`complydoc schema` prints the full shape.

## Four things that are easy to get wrong

**Zero is not always zero.** A page in `sensitive.unreadable_pages` was never read. A
category in `aggregate.categories_not_scanned` was never searched for. Both report zero
and neither is an all-clear. Say so when reporting a clean result.

**Values are masked and should stay masked.** `masked` shows at most the last four
characters. Only pass `--reveal` if the user explicitly asks for unmasked values, and
tell them the report file will then contain them.

**Costs are input tokens only.** Output cost depends on the prompt, which complydoc
cannot know, so the real bill is higher. Prices carry `last_verified`; report a stale
price as stale rather than quoting it plainly.

**A count of zero tables means no *ruled* tables.** Detection works from ruling lines,
so a whitespace-aligned invoice table is not counted.

## Reporting back

Lead with the three figures a decision rests on: cost per 1,000 documents, the mean
difficulty score, and how many documents hold sensitive data. Then name anything in
`limitations[]` marked `important`, because those are the things that would change the
conclusion. Do not print identifier values.
