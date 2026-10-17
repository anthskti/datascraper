# V3 Ideas

Future ideas for the product ingestion pipeline. These are notes only and are not part of the current scope.

## One command from listing to review

Once discovery and scraping are stable, consider replacing the separate `scrape` and `compare` steps with one end-to-end command:

1. Read the YesStyle brand listing input.
2. Discover product URLs.
3. Scrape the discovered products.
4. Prepare a review output for the user.

The run should stop at review. The user can clean the output and decide what to add to the master catalog; automatic appending is not required.

## Review output

Explore a Git diff-style review of the new scrape against the current catalog. It could make changed or potentially matching product fields easier to inspect, including name, brand, capacity, and URL. Keep ambiguous matches visible for manual decisions, such as a Mini product matching a regular or Jumbo product by name.

This is a future workflow idea, not a request to remove current commands or implement a diff now.
