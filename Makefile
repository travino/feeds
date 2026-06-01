PYTHON ?= python3

.PHONY: help feeds feeds_jbzd feeds_jbzd_full

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

feeds: feeds_jbzd ## Generate all feeds

feeds_jbzd: ## Generate Atom feed for Jbzd.com.pl (incremental, merges into archive)
	@echo "Generating Jbzd feed (incremental)..."
	$(PYTHON) feed_generators/jbzd_blog.py
	@echo "Jbzd feed generated -> feeds/feed_jbzd.xml"

feeds_jbzd_full: ## Generate Atom feed for Jbzd.com.pl (full reset, ignores cache)
	@echo "Generating Jbzd feed (FULL RESET)..."
	$(PYTHON) feed_generators/jbzd_blog.py --full
	@echo "Jbzd feed regenerated from scratch -> feeds/feed_jbzd.xml"
