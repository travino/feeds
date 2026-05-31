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

.PHONY: feeds_beatport
feeds_beatport: ## Generate only the Beatport Top 100 feed
	$(PY) feed_generators/beatport_top100.py

.PHONY: feeds_daily_digest
feeds_daily_digest: ## Generate only the Daily Digest feed
	$(PY) feed_generators/daily_digest.py

.PHONY: feeds_reuters
feeds_reuters: ## Generate only the Reuters feed
	$(PY) feed_generators/reuters_news.py

.PHONY: validate
validate: ## Validate all generated feeds
	$(PY) feed_generators/validate_feeds.py

.PHONY: clean
clean: ## Remove generated feeds and cache
	rm -f feeds/feed_*.xml cache/*_posts.json

.PHONY: feeds_trojka
feeds_trojka: ## Generate RSS feed for Trójka (incremental)
	$(call check_venv)
	$(call print_info,Generating Trójka feed)
	$(Q)uv run feed_generators/trojka_blog.py
	$(call print_success,Trójka feed generated)

.PHONY: feeds_trojka_full
feeds_trojka_full: ## Generate RSS feed for Trójka (full reset)
	$(call check_venv)
	$(Q)uv run feed_generators/trojka_blog.py --full

.PHONY: feeds_czworka
feeds_czworka: ## Generate RSS feed for Czwórka (incremental)
	$(call check_venv)
	$(call print_info,Generating Czwórka feed)
	$(Q)uv run feed_generators/czworka_blog.py
	$(call print_success,Czwórka feed generated)

.PHONY: feeds_czworka_full
feeds_czworka_full: ## Generate RSS feed for Czwórka (full reset)
	$(call check_venv)
	$(Q)uv run feed_generators/czworka_blog.py --full

.PHONY: feeds_nexusmods_news
feeds_nexusmods_news: ## Generate RSS feed for Nexus Mods News (incremental)
	$(call check_venv)
	$(call print_info,Generating Nexus Mods News feed)
	$(Q)uv run feed_generators/nexusmods_news_blog.py
	$(call print_success,Nexus Mods News feed generated)

.PHONY: feeds_nexusmods_news_full
feeds_nexusmods_news_full: ## Generate RSS feed for Nexus Mods News (full reset)
	$(call check_venv)
	$(Q)uv run feed_generators/nexusmods_news_blog.py --full
