# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Start MongoDB
make db  # or: docker compose up -d mongodb

# Run the CLI
uv run main.py <command> [options]

# Clean database and PDFs (destructive)
uv run clean_data.py
```

## Architecture

This is a single-file CLI (`main.py`) built with `typer`. All commands live in `main.py` and share:
- **MongoDB** at `mongodb://localhost:27017/`, database `iclr-2026`
- **Collections**: `papers` and `authors`
- **LLM** configured via env vars (`LLM_PROVIDER`, `LLM_MODEL`, etc.) using `litellm` under the hood

### Workflow

```
process-papers → process-authors → enrich-authors-from-pdf → enrich-authors → generate-synopses → export-authors
```

1. `process-papers` — fetches "Accept (Oral)" papers from OpenReview V2 API, downloads PDFs to `./pdfs/`, upserts into `papers` collection
2. `process-authors` — extracts unique authors from saved papers, fetches profiles from OpenReview, fetches arXiv publication counts, upserts into `authors` collection
3. `enrich-authors-from-pdf` — parses PDF headers with `pypdf` to extract emails/affiliations, does positional+name matching to associate emails to authors
4. `enrich-authors` — resolves Semantic Scholar IDs, detects prior award keywords in publication history, finds LinkedIn profiles via DuckDuckGo + LLM validation
5. `generate-synopses` — reads PDFs with `pypdf`, sends text to LLM with a VC-focused prompt, saves to `papers.synopsis`
6. `export-authors` — writes `authors_export.csv` with columns: `name`, `institution`, `email`, `paper_title`, `paper_url`, `synopsis`, `linkedin_url`

### LLM Configuration (`.env`)

```
LLM_PROVIDER=ollama|openai|anthropic|vllm
LLM_MODEL=<model name>
OLLAMA_BASE_URL=http://localhost:11434
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
VLLM_BASE_URL=http://localhost:8000/v1
```

### Key Rate Limits
- Semantic Scholar: ~1 s/author
- DuckDuckGo: ~1.5 s/author
- arXiv: throttled via `arxiv` library

### MongoDB Document Shape

**papers**: `_id` = OpenReview paper ID, fields: `title`, `authors[]`, `authorids[]`, `pdf_path`, `pdf_url`, `forum_url`, `synopsis`, `published_date`

**authors**: `_id` = OpenReview profile ID (`~Name_1`) or plain name, fields: `names[]`, `institution`, `email`, `openreview{}`, `arxiv{total_hits, papers[]}`, `ss_id`, `award_estimate_count`, `award_details[]`, `linkedin_url`