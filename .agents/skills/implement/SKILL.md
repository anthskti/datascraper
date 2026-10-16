---
name: implement
description: Use when asked to build a feature, make a code change, or carry out an approved plan in this repo. Makes the edits and verifies them.
---

# Implement

1. **Read before writing.** Read `AGENTS.md`, the relevant phase in `01-data-pipeline.md`, and the neighboring modules. Mirror their naming, async style, logging, and error handling.
2. **Make surgical edits.** Respect the layering (orchestrator → scrapper → extractors → `product_taxonomy`). Put shared normalization in `product_taxonomy.py`, merchant selectors in the extractors. Don't reformat or refactor unrelated code.
3. **Honor data and safety conventions.** Keep `OUTPUT_FIELDS` and the skin-type enum consistent; a failed scrape must not overwrite a good value. Keep secrets in env vars or a gitignored `.env`. Make network writes idempotent with `--dry-run`, and backfills resumable.
4. **Verify.** There is no test suite or linter. Run the touched script with `uv run` on a few rows and inspect the output CSV. If you added tests, run `uv run pytest`. Use `uv add` for new dependencies. Fix failures caused by your change; report pre-existing ones without fixing them.
5. **Update docs** only where the change makes them wrong (root or per-scraper `README.md`, the phase notes in `01-data-pipeline.md`).
6. **Report.** Summarize files changed, what was verified, and anything not verified. Stop after the requested phase.

Keep the final report to a few bullets: files changed, what was verified, what wasn't. Don't re-explain the request or narrate edits.
