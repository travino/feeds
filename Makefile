# Use `uv` if available, otherwise fall back to plain python.
PY := $(shell command -v uv >/dev/null 2>&1 && echo "uv run" || echo "python")

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Install dependencies (uv sync)
	uv sync

.PHONY: feeds
feeds: ## Generate all feeds (incremental)
	$(PY) feed_generators/run_all_feeds.py

.PHONY: feeds-full
feeds-full: ## Regenerate all feeds from scratch (ignore cache)
	$(PY) feed_generators/run_all_feeds.py --full

.PHONY: feeds_reuters
feeds_reuters: ## Generate only the Reuters feed
	$(PY) feed_generators/reuters_news.py

.PHONY: validate
validate: ## Validate all generated feeds
	$(PY) feed_generators/validate_feeds.py

.PHONY: clean
clean: ## Remove generated feeds and cache
	rm -f feeds/feed_*.xml cache/*_posts.json
