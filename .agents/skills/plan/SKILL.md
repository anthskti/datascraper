---
name: plan
description: Use when asked to plan, scope, design, or break down a feature or change before coding. Produces a written plan; makes no code edits.
---

# Plan

1. **Clarify the goal.** Restate it in one or two sentences. If a decision materially changes the approach and can't be inferred from the code or `01-data-pipeline.md`, ask before planning.
2. **Explore.** Read `AGENTS.md`, `01-data-pipeline.md`, and the code involved (`product_taxonomy.py`, the merchant's extractors/scrapper/orchestrator, and its README). Follow the existing pattern for similar work rather than inventing one.
3. **Identify the blast radius.** Note which layers change (orchestrator, scrapper, extractors, `product_taxonomy`), which merchants are affected, and whether the output CSV contract (`OUTPUT_FIELDS`) or the ClearUp import changes.
4. **Write the plan:**
   - Goal and non-goals
   - Ordered steps, each naming the files to change and the intent
   - Data contract changes, new dependencies, new secrets or env vars
   - Scraping risks (throttling, site markup fragility) and open questions
   - How to verify (small run on a few input rows, output CSV inspection, offline fixtures)
5. Keep it short and concrete. Stop and wait for approval before implementation.

Output stays concise: for a complex task start with the approach/example/risks, then the numbered plan. No restating the request.
