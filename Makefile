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

.PHONY: feeds_windows11_release_notes
feeds_windows11_release_notes: ## Generate only the Windows 11 Release notes feed
	$(PY) feed_generators/windows11_release_notes.py

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

.PHONY: feeds_jbzd
feeds_jbzd: ## Generate Atom feed for jbzd.com.pl (incremental)
	$(call check_venv)
	$(call print_info,Generating jbzd feed)
	$(Q)uv run feed_generators/jbzd_blog.py
	$(call print_success,jbzd feed generated)

.PHONY: feeds_jbzd_full
feeds_jbzd_full: ## Generate Atom feed for jbzd.com.pl (full reset)
	$(call check_venv)
	$(Q)uv run feed_generators/jbzd_blog.py --full

.PHONY: feeds_foobar2000
feeds_foobar2000: ## Generate combined Atom feed for foobar2000 (News + change logs, incremental)
	$(call check_venv)
	$(call print_info,Generating foobar2000 feed)
	$(Q)uv run feed_generators/foobar2000_blog.py
	$(call print_success,foobar2000 feed generated)

.PHONY: feeds_foobar2000_full
feeds_foobar2000_full: ## Generate combined Atom feed for foobar2000 (full reset)
	$(call check_venv)
	$(Q)uv run feed_generators/foobar2000_blog.py --full

.PHONY: feeds_anthropic
feeds_anthropic: ## Generate only the Anthropic feed (news/research/engineering)
	$(PY) feed_generators/anthropic.py

.PHONY: feeds_claude
feeds_claude: ## Generate only the Claude feed (blog/changelog/release notes)
	$(PY) feed_generators/claude.py

.PHONY: feeds_openai
feeds_openai: ## Generate only the OpenAI feed (news/release notes/changelogs)
	$(PY) feed_generators/openai.py

.PHONY: feeds_xai
feeds_xai: ## Generate only the xAI feed (news/Grok Build/API release notes)
	$(PY) feed_generators/xai.py

.PHONY: feeds_groq
feeds_groq: ## Generate only the Groq feed (blog/newsroom/changelog)
	$(PY) feed_generators/groq.py

.PHONY: feeds_bitly
feeds_bitly: ## Generate only the Bitly feed (blog/press/MCP changelog)
	$(PY) feed_generators/bitly.py

.PHONY: feeds_cheezburger
feeds_cheezburger: ## Generate only the Cheezburger network feed
	$(PY) feed_generators/cheezburger.py

.PHONY: feeds_euronews
feeds_euronews: ## Generate only the Euronews combined feed
	$(PY) feed_generators/euronews.py

.PHONY: feeds_memedroid
feeds_memedroid: ## Generate only the Memedroid feed
	$(PY) feed_generators/memedroid.py

.PHONY: feeds_9gag
feeds_9gag: ## Generate only the 9GAG feed
	$(PY) feed_generators/ninegag.py

.PHONY: feeds_pap
feeds_pap: ## Generate only the PAP combined feed
	$(PY) feed_generators/pap.py

.PHONY: feeds_microsoft
feeds_microsoft: ## Generate only the Microsoft combined feed
	$(PY) feed_generators/microsoft.py

.PHONY: feeds_lexus_newsroom
feeds_lexus_newsroom: ## Generate only the Lexus Newsroom feed (USA/Europe/Poland/Discover Lexus)
	$(PY) feed_generators/lexus_newsroom.py

.PHONY: feeds_toyota_global
feeds_toyota_global: ## Generate only the Toyota Global feed (USA/Europe/Global/Connected/TRI)
	$(PY) feed_generators/toyota_global.py

.PHONY: feeds_ra
feeds_ra: ## Generate only the RA feed (magazine/features/music, deduped)
	$(PY) feed_generators/ra_magazine.py
.PHONY: feeds_meta_newsroom
feeds_meta_newsroom: ## Generate only the Meta Newsroom feed (Meta.com/About/Engineering/AI)
	$(PY) feed_generators/meta_newsroom.py

.PHONY: feeds_govpl_news
feeds_govpl_news: ## Generate only the Gov.pl feed (KPRM/Cyfryzacja/Zdrowie/MON/MSZ/RCB/PZ/Baza wiedzy)
	$(PY) feed_generators/govpl_news.py

.PHONY: feeds_commoninja
feeds_commoninja: ## Generate only the Common Ninja blog feed
	$(PY) feed_generators/commoninja_blog.py

.PHONY: feeds_canva_newsroom
feeds_canva_newsroom: ## Generate only the Canva Newsroom feed
	$(PY) feed_generators/canva_newsroom.py

.PHONY: feeds_canva_learn
feeds_canva_learn: ## Generate only the Canva Learn feed
	$(PY) feed_generators/canva_learn.py
