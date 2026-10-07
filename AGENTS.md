# AGENTS.md

Local Python tool that scrapes skincare product data (YesStyle, Sephora) for [ClearUp](https://www.clearup.skin) and hands it off as CSV. Solo-dev project; keep things simple.

## Current task: v2 data pipeline

The work plan is [01-data-pipeline.md](./01-data-pipeline.md). Read it before starting. It is the source of truth for decisions, the five phases, and open questions.

- Phase 0 (package restructure) is complete; the package layout below is current.
- Implement **one phase at a time**, in order. Stop after each phase and summarize; don't start the next one unprompted.
- Don't re-litigate the decisions table (scraper stays local, Cloudflare R2, local-only ML, CSV hand-off first).
- If a phase depends on something undecided (an "Open question"), or on the ClearUp backend/DB (e.g. the `skinTypeSource` migration lives in the other repo), ask rather than guess.
- When a phase is done, mark it done in the plan's "Phases" list and add notes on anything that deviated; don't rewrite its decisions.

## Setup and commands

- Python 3.13, managed with **uv**. Add deps with `uv add <pkg>` (never `pip install`). Run everything with `uv run`.
- First-time browser install: `uv run playwright install chromium`.
- Run commands from the repo root:
  ```bash
  uv run datascraper scrape yesstyle --input inputs/yesstyle_input_v2.csv --output outputs/yesstyle_output.csv --workers 5 --delay 5
  uv run datascraper scrape sephora --input inputs/sephora_input.csv --output outputs/sephora_output.csv --workers 4 --delay 8
  uv run datascraper --help
  ```
- There is **no test suite, linter, or CI** yet. Verify changes by running the relevant script on a small input (a few rows) and inspecting the output CSV. If you add tests, use `pytest` (add as a dev dependency) and keep them offline: use saved HTML fixtures, never live sites.
- [main.py](./main.py) is an unused stub.

## Layout

| Path                                                              | Role                                                                                                                                                     |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/datascraper/taxonomy.py`                                     | Shared normalization: category, labels, skin-type synonym mapping, enums. Merchant-agnostic. **Extend this rather than duplicating rules in a scraper.** |
| `src/datascraper/sources/<merchant>/extractors.py`                | Merchant-specific BeautifulSoup selectors (DOM → raw fields). Site markup changes get fixed here.                                                        |
| `src/datascraper/sources/<merchant>/scraper.py`                   | Scrape **one** product (Playwright navigation + extractors + taxonomy).                                                                                  |
| `src/datascraper/sources/<merchant>/scrape.py`                    | Batch orchestration: read input CSV, run scrapers with a semaphore + delay, write output CSV.                                                             |
| `src/datascraper/models.py`                                       | Shared `Product` type and single `OUTPUT_FIELDS` definition.                                                                                              |
| `src/datascraper/cli.py`                                          | `datascraper scrape yesstyle|sephora` command-line interface.                                                                                            |
| `src/datascraper/pipeline/`, `src/datascraper/storage/`            | Extension points for later pipeline phases; Phase 0 adds package markers only.                                                                             |
| `inputs/`, `outputs/`                                             | Data (gitignored). `outputs/master.csv` is the merged dataset; `migration.csv` is the ClearUp import.                                                    |
| `docs/`, `extra/`                                                 | Gitignored scratch notes and sample HTML. Not authoritative; don't commit to them.                                                                       |

Layering: CLI → merchant batch orchestrator → single-product scraper → extractors → `datascraper.taxonomy`. Keep that direction; extractors don't do I/O or navigation.

New data sources (affiliate feeds, Shopify JSON, Open Beauty Facts) should follow the same shape: a source-specific module that produces the common output row, reusing `datascraper.taxonomy`. Put them in their own folder under `src/datascraper/sources/` with a short README.

## Data contract

Output row fields (order matters; the CSV is imported into ClearUp):

`name, brand, category, labels, skinType, country, capacity, price, instructions, ingredients, imageUrls, averageRating, url, merchant, status`

- `skinType` values must come from `ALL_SKIN_TYPES` in `src/datascraper/taxonomy.py` (`oily, dry, combination, sensitive, normal, acne-prone`). Missing is `N/A`; unknown labels are `-` (`LABEL_NA`).
- `status` marks success or failure per row. A failed scrape must **never overwrite** a previously good value; flag it instead.
- Adding or renaming a field is a contract change with the ClearUp repo. Make it additive where possible, update `OUTPUT_FIELDS` in every orchestrator, and call it out in your summary.
- Keep original merchant image URLs only in scraper output. The DB should get R2 URLs (see plan §4).

## Conventions

- Code is `async` (Playwright async API) with `asyncio` + `Semaphore` for concurrency. Keep concurrency conservative and the delay between requests; sites throttle.
- Use `logging` (`logger = logging.getLogger(__name__)`), not `print`, in scraper code.
- Type hints use modern syntax (`str | None`, `list[str]`).
- Paths are built from `Path(__file__).resolve().parent...`, never from the cwd.
- Package imports use `datascraper.*`; do not add `sys.path` hacks.
- Prefer stable structured sources over fragile DOM scraping: affiliate feed > JSON-LD / `__NEXT_DATA__` / Shopify `.json` > Playwright + BS4 > LLM (discovery only). LLMs are never used in the refresh path.
- Be a polite scraper: respect throttling, don't hammer sites, don't bypass logins or paywalls.

## Secrets and safety

- R2/S3 credentials, affiliate API keys, etc. go in environment variables or a gitignored `.env`. Never hardcode or commit them, and add any new secret file to [.gitignore](./.gitignore).
- `inputs/` and `outputs/` are gitignored; don't force-add them. Keep downloaded images and caches out of git too (add a gitignore entry for any new data directory).
- Network writes (R2 uploads, DB upserts) must be idempotent (deterministic keys such as `products/<productId>/<n>.webp`, upsert not insert) and support a `--dry-run`. Don't run a real upload or DB write without being asked.
- Backfills run over ~400 products: make them resumable (skip already-done items) so a failure doesn't mean starting over.

## Working style

- Make surgical changes; don't reformat or refactor unrelated code (the extractors and taxonomy files are large and hand-tuned).
- Read the neighboring module and mirror it before writing new code.
- Update the relevant `README.md` (root or per-scraper) when you add a CLI flag, source, or step.
- Commit messages follow the existing style: `feat:`, `fix:`, `cleanup:` prefix, lowercase summary.
- Report briefly: files changed, how you verified, and anything not verified.

## Skills

[.agents/skills/](./.agents/skills) has `plan`, `implement`, `debug`, and `review` skills tailored to this repo. Use `plan` and `implement` for each phase of the pipeline work.
