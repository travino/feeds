# Feedseek for ChatGPT

Feedseek exposes its public feed data as a small read-only remote MCP app for ChatGPT.
The production endpoint is:

```text
https://feeds.trfny.com/mcp
```

## Tools

| Tool | Purpose |
| --- | --- |
| `search` | Standard connector/deep-research search over the recent Feedseek index. |
| `fetch` | Standard connector fetch for the full entry behind a search result id. |
| `recent` | Bulk digest input with optional time, topic and source filters. |

`search` and `fetch` intentionally follow OpenAI's standard read-only connector contract.
`recent` exists so a 24/72-hour digest can retrieve compact summaries in one call instead
of fetching every candidate separately.

## Data path

```text
feeds/feed_*.json
       |
       v
site/build_search_index.py
       |
       v
GitHub Pages: feedseek-search-index.json
       |
       v
feeds.trfny.com/mcp
       |
       v
ChatGPT Feedseek app
```

The index contains at most 5,000 items from the last 14 days plus a small allowance for
undated entries. Search reads that aggregate with one upstream request. `fetch` then reads
only the JSON Feed containing the selected item. This avoids per-request fan-out over the
entire Feedseek registry.

## Security and privacy

- All exposed tools are read-only and non-destructive.
- The app reads only Feedseek's already-public generated feeds; it needs no user account,
  OAuth token or secret.
- Feed/article text is explicitly marked and instructed as untrusted external content.
- Opaque result ids encode only the Feedseek source key and upstream item id needed for
  deterministic lookup.
- The existing constrained fetch proxy remains unchanged; `/mcp` is routed separately.

## ChatGPT testing and installation

For private development, connect the remote MCP endpoint in ChatGPT Developer Mode on an
account or workspace that supports custom MCP apps. ChatGPT scans the server and exposes its
tools after the app is created.

For normal end-user installation, submit the app for review and publish it through the
ChatGPT Plugin Directory. After approval, users can install/connect Feedseek from ChatGPT's
Apps/Plugins UI rather than manually entering the endpoint.

The repository root includes `chatgpt-app-submission.json` with review-facing app metadata,
tool annotations, and positive/negative test cases. Reuse the existing Feedseek app artwork,
including `assets/icons/android-chrome-512x512.png`, for directory submission assets.

## Deployment

`feeds-proxy/` is already deployed from `main` by Cloudflare Workers Builds. Its Wrangler
entry point composes the existing fetch proxy with the new `/mcp` route.

GitHub Pages builds `feedseek-search-index.json` alongside the public Feedseek site. The Pages
workflow also runs after the regular feed-update workflow, so the MCP index follows the same
freshness cycle as the generated feeds.
