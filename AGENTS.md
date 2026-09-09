# Using complydoc from an agent

complydoc is a command line tool. It reads a folder of documents and writes a JSON
report and an HTML report. It makes no network calls, so it is safe to run against
material that must not leave the machine.

Point your agent at this file, or paste the block below into its instructions.

## Instruction block

> You have `complydoc` available. It audits a folder of business documents offline and
> reports what they would cost to process with an LLM, how hard they are to extract
> from, and which UK GDPR relevant identifiers they contain.
>
> Run `complydoc audit <path> --print-json` and parse stdout. stdout is JSON and
> nothing else; progress and warnings go to stderr. Exit code 0 means the run
> completed, 2 means the arguments or the config were wrong.
>
> Sensitive values are masked. `masked` shows at most the last four characters. Do not
> pass `--reveal` unless the user explicitly asks for unmasked values, and tell them
> the report will contain them.
>
> Before drawing a conclusion, read `limitations[]` and
> `documents[].sensitive.unreadable_pages`. A count of zero on a page that was never
> read is not an all-clear.

## Commands

| Command | Use |
| --- | --- |
| `complydoc audit <path>` | All three components |
| `complydoc cost <path>` | Cost only |
| `complydoc difficulty <path>` | Extraction difficulty only |
| `complydoc sensitive <path>` | Sensitive identifiers only |
| `complydoc schema` | The shape of the JSON, for parsing |
| `complydoc models` | Which models can be priced against |
| `complydoc doctor` | What is installed and what is missing |

Useful flags: `--print-json`, `--monthly-volume N`, `--model <id>` (repeatable),
`--ocr`, `--out <dir>`, `--quiet`.

## Reading the JSON

```bash
complydoc sensitive ./invoices --print-json --ocr | jq '
  {
    high: [.documents[].sensitive.matches[] | select(.severity=="high")] | length,
    unread: [.documents[] | select(.sensitive.unreadable_pages | length > 0) | .relative_path],
    important: [.limitations[] | select(.severity=="important") | .area]
  }'
```

Fields an agent usually wants:

- `run.components_run` — which of cost, difficulty, sensitive actually ran.
- `run.offline_guard` — `armed` means nothing could have left the machine.
- `run.reveal_used` — `true` means values are **not** masked.
- `aggregate.sensitive_by_category` / `sensitive_by_severity` — folder totals.
- `documents[].difficulty.score` — 0-100, higher is easier; check `low_confidence`.
- `documents[].sensitive.matches[]` — `category`, `page`, `line`, `column`, `masked`,
  `severity`.
- `documents[].sensitive.unreadable_pages` — pages nothing looked at.
- `limitations[]` — what this run could not tell you, generated from the run.

## Things to get right

**Zero is not always zero.** A category under `aggregate.categories_not_scanned` was
never searched for. A page in `unreadable_pages` was never read. Both report zero
findings and neither is an all-clear.

**Masking is the default and should stay that way.** `--reveal` puts real
identifiers into the report file. Categories under `config_masking.never_reveal`
stay masked even then.

**Costs are input only, and prices carry a date.** `documents[].cost.models[]` has
`last_verified` and `is_stale` per model. A stale price is reported, not hidden.

**Nothing is fetched at run time.** Optional OCR and name detection need their
extras installed first (`uv sync --extra ocr --extra ner`); without them, affected
pages and categories are listed in `limitations[]` rather than silently skipped.
