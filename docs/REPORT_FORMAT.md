# The report format

`codex-auto-resume-compat-evidence/1` — the same document the maintainer's own tool writes, so a
community report and the maintainer's evidence can be read side by side without translation.

This page is the contract: what the file holds, and what the project checks before it accepts one.
Everything here is enforced on both sides, so a refusal is predictable rather than a surprise.

## The envelope

| Field | What it is |
| --- | --- |
| `format` | exactly `codex-auto-resume-compat-evidence/1` |
| `codex_version` | `codex-cli <version>`, the engine the report is about |
| `verdict` | `PASS` when anything reached Verified here, else `CHECKED`, else `NONE` |
| `recorded_at` | when the file was written, UTC |
| `recorded_by` | a sentence naming the tool; the project replaces it with its own wording |
| `reporter` | `github_login`, `tool`, `tool_version`, `product_version`, `windows` (the OS build number, e.g. `10.0.26200`) |
| `attribution` | the rule by which a record was counted for this version; `window` and `basis` are for a window set by hand and are `null` here |
| `local_checks` | how many times the product's own checks passed on this version here, when first and last, and which capabilities they cover |
| `records` | one entry per interruption this machine handled on this version |
| `capabilities` | per capability: `confirmed`, `missed`, `last_confirmed`, `level` |
| `note` | the file saying what it is |

## A record

```json
{
  "detected_at": "2026-09-21T05:37:22Z",
  "delivered_at": "2026-09-21T09:47:23Z",
  "outcome_at": "2026-09-21T10:06:15Z",
  "category": "usage_limit",
  "state": "recovered",
  "reason": "progress_observed",
  "turn_status": "completed",
  "gates_passed": 13,
  "progress_items": {"agentMessage": 6, "commandExecution": 30, "fileChange": 6, "mcpToolCall": 1}
}
```

Three times, four words and five counts. The words are not free text: `category`, `state`,
`reason` and `turn_status` are passed through the product's own published vocabularies, and a value
the tool does not recognise is written as `other` rather than copied. That is what keeps a message,
a path or a name from ever reaching the file by accident, including from a future product version
this tool has not met.

## What a capability entry means

`confirmed` counts records in which a recovery exercised that capability and it held; `missed`
counts records in which it was exercised and did not. `level` is `VERIFIED` when something was
confirmed, nothing was missed, and at least one recovery was delivered and seen through to an
outcome; `CHECKED` when the product's own local checks passed on this version but no recovery
confirmed it; `null` otherwise. A delivered recovery that did not clear the gate capabilities -
`engine_present` and `exact_thread_recovery` - verifies nothing, and every `VERIFIED` in that file
falls back.

## What the project does with it

1. **Recomputes.** Every derived field - `verdict`, each `level`, the consistency of each count
   against the records - is worked out again from the records in the file. A level edited by hand
   does not survive; it is reported back as a disagreement.
2. **Replaces the prose.** `recorded_by`, `attribution.rule` and `note` are rewritten by the
   receiving side from its own strings. No sentence from a report is ever displayed as written.
3. **Files it apart.** It lands in `docs/evidence/community/<github login>/`, never in the
   product's compatibility data, and never changes a version's tier.

## What gets a report refused

- the format string, a key or a value outside what this page lists;
- a `codex_version` that is not `codex-cli` followed by a version;
- a time in the future, an outcome before its detection, or a count below zero;
- `confirmed` plus `missed` larger than the number of records;
- more than 500 records, or a file over 1 MB;
- a pull request that touches anything outside the sender's own folder, or changes a file already
  there rather than adding one. Reports are add-only.

## Why it is not trusted further

A file can be written by hand. Checking it harder would not change that; it would only make the
result look more authoritative than it is. So community reports are kept apart, are shown as
"reported by", and grant nothing - and a report that a version *failed* is worth as much as one
that says it worked, which is the honest use for a document nobody can prove.
