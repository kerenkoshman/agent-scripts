---
name: payload-slim
description: "Pre-process large JSON payloads before sending to a model: drop nulls, whitelist keys, truncate strings, report token savings."
---

# Payload Slim

Strip token waste from JSON payloads before they reach a model. Targets cron jobs, DB exports, and API responses that would otherwise consume 100K–570K tokens.

## Quick start

```bash
# See what's costing tokens (field breakdown, before/after)
python3 skills/payload-slim/scripts/payload-slim.py --input payload.json --field-report --report

# Keep only relevant keys, truncate strings to 150 chars
python3 skills/payload-slim/scripts/payload-slim.py --input payload.json \
  --keep id,name,status,updated_at,amount \
  --max-str 150 --report

# Pipe from a command, emit compact JSON
some-db-export-cmd | python3 skills/payload-slim/scripts/payload-slim.py \
  --max-str 120 --compact --report

# Limit to first 200 rows + drop known-irrelevant fields
python3 skills/payload-slim/scripts/payload-slim.py --input rows.json \
  --drop raw_body,html_url,node_id,gravatar_id \
  --max-items 200 --report
```

## Flags

| Flag | Default | Effect |
|---|---|---|
| `--input FILE` | stdin | JSON file to read |
| `--keep KEYS` | (all) | Comma-separated top-level keys to keep; all others dropped |
| `--drop KEYS` | (none) | Comma-separated top-level keys to always remove |
| `--max-str N` | 200 | Truncate strings longer than N chars (appends `…[+N]`) |
| `--max-items N` | (all) | Keep only first N array items; appends `_omitted` marker |
| `--no-drop-nulls` | off | Keep null/empty fields (dropped by default) |
| `--compact` | off | Single-line output (no indentation) |
| `--report` | off | Print before/after token count to stderr |
| `--field-report` | off | Print top fields by token cost (before + after) to stderr |

## What it does

- Drops `null`, `""`, `[]`, `{}` fields by default
- Applies `--keep`/`--drop` only at the top level of each record; nested objects are recursively null-dropped and string-truncated
- For arrays: filters each element, optionally caps length, appends an `_omitted` count entry if truncated
- Token estimate: `ceil(utf8_bytes / 4)` — same formula as `skill-cleaner`

## Typical savings

| Input | After `--max-str 150 --drop raw_body,html` | Reduction |
|---|---|---|
| 500 GitHub issues (570K tokens) | ~35K tokens | ~94% |
| DB export, 1000 rows, wide schema | ~20–60K tokens | ~80–95% |
| Single large API response | ~5–30K tokens | ~60–90% |

## Cron workflow

1. Run with `--field-report` once to identify the token hogs
2. Build a `--keep` list of only what the cron task actually needs
3. Add `--max-str 150` (most models don't need full body text in summaries)
4. Pipe slimmed output to the agent prompt instead of raw JSON

## Notes

- Slimming is lossy — use only when the downstream model task doesn't need the dropped fields
- For tasks needing the full record of specific items, slim first to get IDs, then fetch by ID
- Combine with `payload-delta` (delta tracking) for near-zero tokens on stable cron data
