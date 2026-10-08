---
name: review
description: Use when asked to review a diff, branch, PR, or set of files. Reports high-confidence bugs, security issues, and convention violations without editing code.
---

# Review

1. **Get the change.** Use `git diff` (staged and unstaged) or the branch diff against the base, and read the surrounding code for context. Compare against the relevant phase in `01-data-pipeline.md`.
2. **Check, in priority order:**
   - **Correctness:** logic errors, unhandled edge cases, wrong async handling (missing `await`, unclosed browser/pages, unbounded concurrency), broken type hints
   - **Data integrity:** `OUTPUT_FIELDS` or enum drift between scrapers and `product_taxonomy.py`; failed scrapes overwriting good values; non-idempotent or non-resumable writes
   - **Safety:** hardcoded or logged secrets, new secret/data files not gitignored, real uploads or DB writes without `--dry-run`, aggressive request rates
   - **Contract drift:** output column changes that would break the ClearUp CSV import
   - **Conventions:** layering violations, duplicated taxonomy rules in a scraper, `print` instead of `logging`, cwd-relative paths
3. **Verify claims** by running the script on a few rows or tests where relevant; don't report problems you haven't confirmed.
4. **Report** findings ordered by severity, each with file, line, the problem, and a suggested fix. Skip style nitpicks and pre-existing issues. If nothing significant is found, say so.

Findings only, one short entry each. No summary of the diff and no praise or filler.
