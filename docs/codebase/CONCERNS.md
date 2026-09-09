# Codebase Concerns

## Core Sections (Required)

### 1) Top Risks (Prioritized)

| Severity | Concern | Evidence | Impact | Suggested action |
|----------|---------|----------|--------|------------------|
| high | Critical shared helper has a large blast radius | `feed_generators/utils.py` is 958 lines and patches Feedgen file-writing methods | A small regression can affect most generated feeds, cache state or serialization | Keep moving reusable concerns into focused modules while preserving one source of truth; require invariant tests for each extraction |
| medium | Feed richness cannot be represented by one universal checklist | Sources range from APIs/weather to newsrooms and native feeds; `validate_feeds.py` intentionally gates structural invariants only | An overly strict validator could reward invented metadata or reject legitimate sparse sources | Keep structural invariants hard and source-dependent enrichment evidence-based and best-effort |
| medium | Batch duration depends on upstream latency and source count | `feed_generators/run_all_feeds.py` uses bounded concurrency and reports the slowest generators | Slow or rate-limited upstreams can still consume workflow headroom as the registry grows | Track per-generator duration and tune the bounded worker count only from measured need, preserving per-source isolation and rate limits |
| medium | Public proxy fetches arbitrary public-looking HTTPS destinations | `feeds-proxy/src/index.js` | Proxy abuse/SSRF-like behavior is the main exposed network-security surface | Verify Cloudflare's resolved-address guarantees; if needed add an explicit destination policy beyond syntactic hostname checks |

### 2) Technical Debt

| Debt item | Why it exists | Where | Risk if ignored | Suggested fix |
|-----------|---------------|-------|-----------------|---------------|
| Large source-specific modules | Feed adapters accumulated source variants and defensive parsing | `skillsllm.py` 870 lines, `daily_digest.py` 854, `saas.py` 736 | Harder review and source-specific regressions | Extract only genuinely shared provider/parser policies into maintained helpers |
| Legacy generator compatibility layer | Generators expose several historical `main()` signatures and output habits | `invoke_generator.py` | Compatibility patches can hide inconsistent adapters indefinitely | Migrate generators toward one contract, then shrink the adapter deliberately |
| Site builder mixes data parsing, SEO assets and HTML rendering | Static site grew in one script | `site/build_site.py` 696 lines | Changes to metadata can accidentally affect rendering or discovery output | Split pure parsing/rendering helpers when a concrete change benefits from it; avoid parallel configuration sources |

### 3) Security Concerns

| Risk | OWASP category (if applicable) | Evidence | Current mitigation | Gap |
|------|--------------------------------|----------|--------------------|-----|
| User-controlled proxy target | A10 SSRF | `feeds-proxy/src/index.js` | HTTPS-only, no credentials/non-443 ports, blocks localhost/local suffixes/literal IPs, redirects revalidated, 8s/2MiB/3-redirect limits | Application code does not explicitly resolve hostnames and reject private resolved addresses; platform behavior is not documented here |
| Secret leakage through generation/logging | A02 Cryptographic Failures / N/A | `.github/workflows/update-feeds.yml`, `AGENTS.md` | Secrets injected from GitHub; repository policy forbids committing/logging them | No automated secret-scanner policy specific to generated feeds/cache was identified beyond platform/repo security tooling |
| Dependency/supply-chain drift | A06 Vulnerable and Outdated Components | `.github/dependabot.yml`, `uv.lock`, `package-lock.json`, `codeql.yml` | Locked dependencies, weekly Dependabot, CodeQL | External source behavior still changes independently of package locks |

### 4) Performance and Scaling Concerns

| Concern | Evidence | Current symptom | Scaling risk | Suggested improvement |
|---------|----------|-----------------|-------------|-----------------------|
| Network-bound feed batch | `run_all_feeds.py` uses a bounded worker pool with per-generator timing | Independent network waits are overlapped while concurrency remains capped | More sources or slower upstreams can still stretch the scheduled job or trigger rate limits | Keep the current bound conservative and tune it from measured slowest-generator data rather than adding unbounded parallelism |
| Enrichment fans out network requests | `article_image.py`, `google_news.py` | Potentially many article/page lookups | Upstream load and CI duration | Keep current per-feed lookup/time/attempt budgets; tune from measured backlog |
| Persistent cache growth | `utils.DEFAULT_CACHE_LIMIT`, R2 128 MiB ceiling | Historical caches previously grew without bound | Oversized cache can prevent fresh R2 backup | Retain bounded trimming/fair-share policy and monitor archive size |
| Large static render script | `site/build_site.py` | Re-parses selected feed XML during each build | Mostly linear and acceptable at current size | Optimize only with measured build pressure; correctness is more important than premature indexing |

### 5) Fragile/High-Churn Areas

| Area | Why fragile | Churn signal | Safe change strategy |
|------|-------------|-------------|----------------------|
| `README.md` | Registry table and dynamic README sections are automation-sensitive | 150 commits touching path in the last 90 days | Preserve markers and run `tests.test_registry_docs` |
| `feeds.yaml` | Central source registry controls the batch | 49 commits in the last 90 days | One source change at a time; validate generator path and registry docs |
| `.github/workflows/update-feeds.yml` | Owns generation, R2 persistence, commit/push and final health gate | 41 commits in the last 90 days | Keep permissions/failure ordering explicit; test workflow edits narrowly |
| `feed_generators/utils.py` | Shared by many generators | 11 commits in the last 90 days plus 958-line size | Add focused regression tests before changing cross-cutting behavior |
| `feed_generators/skillsllm.py` | Large multi-source adapter with active source growth | 14 commits in the last 90 days | Reuse shared helpers and test source-level boundaries |

The raw scan's churn table is dominated by generated `feeds/` and `cache/` artifacts because the scheduled workflow updates them continuously; those files are not treated as maintained-source fragility.

### 6) `[ASK USER]` Questions

No unresolved intent-dependent questions from this scan. The project direction is clarified and implemented: JSON Feed 1.1 is first-class, dormant Selenium support was removed, and the quality contract enforces universal structural invariants while leaving source-dependent richness adaptive.

### 7) Evidence

- `feed_generators/utils.py`
- `feed_generators/run_all_feeds.py`
- `feed_generators/validate_feeds.py`
- `feed_generators/jsonfeed.py`
- `feed_generators/article_image.py`
- `feeds-proxy/src/index.js`
- `.github/workflows/update-feeds.yml`
- Git history for the listed maintained paths, inspected over the last 90 days
