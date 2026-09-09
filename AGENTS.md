# AGENTS.md

- `feed_generators/`: Python generators and shared feed helpers.
- `feeds.yaml`: source registry.
- `feeds/` and `cache/`: generated output.
- `site/`: static site and reader.
- `feeds-proxy/`: supporting Cloudflare Worker that remains in this repository.

## Project philosophy

- Feedseek is not only a fallback for sites without feeds. It treats RSS, Atom, and JSON Feed as publishing protocols worth improving in their own right.
- A native feed is an upstream source, not automatically the final product. Reuse it when reliable, then normalize, enrich, or repair it when Feedseek can produce more complete, stable, expressive, or interoperable output.
- Prefer protocol-native semantics over ad-hoc payloads: durable entry identity, canonical links, truthful publication/update dates, useful metadata, provenance/categories, content/media, and equivalent JSON Feed sidecars where supported.
- Preserve upstream meaning. Improvements should add fidelity and interoperability, not invent editorial content or silently rewrite source facts.
- Keep the hard quality contract universal and structural; source-dependent richness such as images, authors, categories or dates is best-effort when the upstream data supports it.

## Repository conventions

- Check `main`, open pull requests and recent changes before overlapping work.
- Prefer consuming a reliable native feed over scraping its HTML, but do not pass it through unchanged when shared normalization or enrichment can improve the published feed.
- Keep one maintained source of truth per concern and use shared normalization/deduplication helpers instead of local copies.
- Fix maintained sources and regenerate `feeds/` / `cache/` rather than hand-editing generated output.
- One broken source must not prevent unrelated feeds from updating.
- A failed or empty fetch must not replace the last good feed with empty output.
- Keep secrets in provider/GitHub secret storage, never in feeds, caches, logs or examples.
- Treat `megalinter-reports/updated_sources` as suggestions: inspect the diff and apply only intended fixes.

## Cloudflare

- `feeds-proxy` is deployed by Cloudflare Workers Builds from `feeds-proxy/`; GitHub Actions only checks it.
- Feedseek's persistent generation-cache backup is the private R2 bucket `feedseek-cache`, object `snapshots/cache.tar.gz`; keep that storage contract stable.
- `.github/workflows/deploy-cloudflare-pages.yml` is dormant direct-upload fallback infrastructure and uses the `feedseek` Pages project name.
- A GitHub rename or transfer is not by itself a reason to recreate KV/R2/D1 resources. Verify the Workers Builds Git connection after repository identity changes instead of assuming either that it survived or broke from the displayed slug alone.
