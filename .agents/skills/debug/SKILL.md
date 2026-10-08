---
name: debug
description: Use when investigating a bug, error, failing build, or unexpected behavior in this repo. Finds the root cause with evidence, then applies a minimal fix.
---

# Debug

1. **Reproduce.** Get the exact error, input row, or URL. Run the narrowest script with `uv run` (e.g. `uv run python yesstyle/yesstyle_scrapper.py` for a single product). If you can't reproduce it, say so and list what you need.
2. **Localize.** Trace the path: orchestrator → scrapper → extractors → `product_taxonomy`. For wrong or missing fields, save the page HTML and test the extractor offline against it. For intermittent failures, check throttling, timeouts, and selectors against the current site markup.
3. **Form a hypothesis and test it.** Confirm the root cause with evidence (logs, the saved HTML, a failing run, reading the code path), not by guessing.
4. **Fix minimally.** Change the cause, not the symptom, and don't refactor around it. Add an offline regression check using a saved HTML fixture if a test location exists.
5. **Verify** that the original reproduction now passes and that neighboring outputs didn't change (e.g. rerun a couple of other rows).
6. **Report:** root cause, fix, verification, and any related risk you noticed but didn't change.

Never print `.env` contents while debugging. Don't hammer live sites with repeated runs; reuse saved HTML. Don't run real uploads or DB writes.

Keep the report to root cause, fix, and verification, one or two lines each. Don't narrate the investigation.
