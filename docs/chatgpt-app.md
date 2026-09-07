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
enabled feeds/feed_*.json
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
          +--> search / recent
          |
          +--> fetch -> immutable feed JSON at the commit encoded in the result id
          |
          v
ChatGPT Feedseek app
```

The index contains at most 5,000 items from the last 14 days plus a small allowance for
undated entries. Feeds explicitly disabled in `feeds.yaml` are not indexed. Search reads
that aggregate with one upstream request.

Each result id also carries the exact Git commit used to build the index. `fetch` reads the
selected JSON Feed at that immutable revision, so a feed update cannot invalidate a result
between `search` and `fetch`. This also avoids per-request fan-out over the registry.

Publication and modification timestamps are both considered for recency; the newer valid
timestamp wins. HTML-only entries are converted to decoded plain text for matching and
display, while literal angle-bracket text in `content_text` is preserved.

## Security and privacy

- All exposed tools are read-only and non-destructive.
- The app reads only Feedseek's already-public generated feeds; it needs no user account,
  OAuth token or secret.
- Feed/article text is explicitly marked and instructed as untrusted external content.
- Opaque result ids encode only the immutable Feedseek revision, source key and upstream
  item id needed for deterministic lookup.
- Tool arguments are validated server-side instead of relying on client validation.
- The existing constrained fetch proxy remains unchanged; `/mcp` is routed separately.
- The public app policy is maintained in [`PRIVACY.md`](../PRIVACY.md); service terms are in
  [`TERMS.md`](../TERMS.md), and user-facing support information is in
  [`SUPPORT.md`](../SUPPORT.md).

## ChatGPT testing and installation

For private development, connect the remote MCP endpoint in ChatGPT Developer Mode on an
account or workspace that supports custom MCP apps. ChatGPT scans the server and exposes its
tools after the app is created.

For normal end-user installation, submit the app for review. Approved apps can be distributed
through a plugin listing in the ChatGPT Plugin Directory, where users install/connect the app
without manually entering its MCP endpoint.

The repository root includes `chatgpt-app-submission.json` with review-facing app metadata,
tool annotations, and exactly five positive plus three negative test cases.

## Directory submission checklist

Open the OpenAI plugin submission portal at `https://platform.openai.com/plugins`, select
**Create plugin**, and choose **With MCP**. Feedseek uses one universal public endpoint.

Use these values when filling the current OpenAI submission form:

| Field | Value |
| --- | --- |
| Display name | `Feedseek` |
| Category | `NEWS` |
| MCP type | Universal |
| MCP server | `https://feeds.trfny.com/mcp` |
| Authentication | None; public read-only data |
| Homepage | `https://trvny.github.io/feedseek/` |
| Source | `https://github.com/trvny/feedseek` |
| Support | `https://github.com/trvny/feedseek/blob/main/SUPPORT.md` |
| Privacy policy | `https://github.com/trvny/feedseek/blob/main/PRIVACY.md` |
| Terms | `https://github.com/trvny/feedseek/blob/main/TERMS.md` |
| App icon | `assets/icons/android-chrome-512x512.png` |
| Submission import | `chatgpt-app-submission.json` |

Before submission:

1. Confirm the submitting OpenAI Platform organization has **Apps Management: Write** and
   select a verified individual or business identity whose public details match the listing.
2. Enter `https://feeds.trfny.com/mcp`, choose no authentication, then select **Scan Tools**.
3. If the portal requests domain verification, copy its exact token into the production
   Cloudflare Worker variable `OPENAI_APPS_CHALLENGE`. The Worker serves that value verbatim at
   `https://feeds.trfny.com/.well-known/openai-apps-challenge`; without a configured token the
   route returns 404. Verify the URL, then retry domain verification in the portal.
4. Verify the production MCP endpoint and the public support/privacy/terms links over HTTPS.
5. Use the five positive and three negative cases from `chatgpt-app-submission.json`, add
   realistic starter prompts, choose the intended countries/regions, and describe this as the
   initial Feedseek submission in the release notes.

The app is tool-only, so it has no widget CSP to declare. All three tools explicitly declare
`readOnlyHint: true`, `openWorldHint: false`, and `destructiveHint: false`, and each tool
declares an `outputSchema`.

### Suggested starter prompts

- `What is new in AI in Feedseek over the last 24 hours?`
- `Search Feedseek for Cloudflare Workers.`
- `Find the newest Audacity item and show me the full entry.`
- `Give me compact Feedseek candidates for a 48-hour tech digest.`

### Review-facing scope

Feedseek should trigger for public feed/news discovery, recent digest candidates, topic
search, and full retrieval of a selected Feedseek entry. It should not trigger for unrelated
actions such as messaging, live weather lookup, local business discovery, purchases, or
mutating external services.

No tool input asks for credentials, payment data, health data, government identifiers, MFA
codes, biometrics, or other sensitive identifiers.

## Deployment

`feeds-proxy/` is already deployed from `main` by Cloudflare Workers Builds. Its Wrangler
entry point composes the existing fetch proxy with the `/mcp` route and the OpenAI domain
verification route.

GitHub Pages builds `feedseek-search-index.json` alongside the public Feedseek site. The Pages
workflow also runs after the regular feed-update workflow, so the MCP index follows the same
freshness cycle as the generated feeds.
