# ICLR 2026 Paper Scraper & Analyzer

This project provides tools to scrape accepted **ICLR 2026 (Oral)** papers, download their PDFs, analyze publication history of their authors, generate AI synopses, and export a contact list.

## Features

- **Paper Scraper**: efficiently fetches "Accept (Oral)" papers from OpenReview V2 API.
- **PDF Downloader**: automatically downloads PDFs to a local directory.
- **Author Analysis**: aggregates author metadata and fetches publication statistics from arXiv.
- **Author Enrichment**: resolves Semantic Scholar IDs, detects prior awards, and finds LinkedIn profiles via DuckDuckGo + LLM.
- **Synopsis Generation**: reads each paper's PDF and uses a local/remote LLM to produce a VC-friendly synopsis.
- **CSV Export**: exports a Google Sheets–ready CSV of authors with paper details and LinkedIn URLs.
- **MongoDB Storage**: stores all metadata and analysis results in a MongoDB database.

## Prerequisites

- **Python 3.12+** (managed via `uv`)
- **Docker** (for MongoDB)
- **OpenReview Account** (username/password)
- **LLM** — one of: Ollama (local), OpenAI, Anthropic, or vLLM

## Setup

1. **Clone the repository** and enter the directory.

2. **Environment Variables**:
    Create a `.env` file (see `.env.example`):
    ```bash
    # OpenReview credentials
    OPENREVIEW_USERNAME=your_email@example.com
    OPENREVIEW_PASSWORD=your_password

    # LLM configuration (used by enrich-authors and generate-synopses)
    LLM_PROVIDER=ollama          # ollama | openai | anthropic | vllm
    LLM_MODEL=gpt-oss:20b
    OLLAMA_BASE_URL=http://localhost:11434   # ollama only
    OPENAI_API_KEY=sk-...                   # openai only
    ANTHROPIC_API_KEY=...                   # anthropic only
    VLLM_BASE_URL=http://localhost:8000/v1  # vllm only
    ```

3. **Start MongoDB**:
    Use the provided Makefile to start a MongoDB container:
    ```bash
    make db
    ```
    (Or run `docker compose up -d mongodb` directly.)

4. **Install Dependencies**:
    ```bash
    uv sync
    ```

## Usage

The application is a CLI built with `typer`. Run any command with `--help` for full option details.

### 1. Process Papers

Scrape accepted papers and download PDFs:

```bash
uv run main.py process-papers
```

- Fetches metadata for all "Accept (Oral)" papers from OpenReview.
- Downloads PDFs to the `./pdfs` directory.
- Stores data in MongoDB collection `iclr-2026.papers`.

### 2. Process Authors

Extract and analyse unique authors from saved papers:

```bash
uv run main.py process-authors
```

- Extracts unique authors from the saved papers.
- Fetches profile info from OpenReview (institution, email, preferred name).
- Searches arXiv for total paper counts and publication list.
- Stores data in MongoDB collection `iclr-2026.authors`.

### 3. Enrich Authors

Enrich author records with Semantic Scholar award history and LinkedIn URLs:

```bash
uv run main.py enrich-authors [--limit N] [--force]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--limit N` | `0` (all) | Process only N authors |
| `--force` | `False` | Re-fetch LinkedIn even if already present |

- Resolves Semantic Scholar IDs via paper title search.
- Scans publication history for award keywords (`best paper`, `award`, `spotlight`, `oral`, `distinguished`, `prize`).
- Searches DuckDuckGo for LinkedIn profiles and validates them with the configured LLM.
- Updates `authors` collection with `award_estimate_count`, `award_details`, and `linkedin_url`.
- *Note: rate-limited (~1 s/author for Semantic Scholar, ~1.5 s/author for DuckDuckGo).*

### 4. Generate Synopses

Generate a VC-friendly synopsis for each paper by reading its PDF:

```bash
uv run main.py generate-synopses [--limit N] [--force] [--max-pages N] [--max-chars N]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--limit N` | `0` (all) | Process only N papers |
| `--force` | `False` | Re-generate synopses that already exist |
| `--max-pages N` | `0` (all) | Read at most N pages per PDF |
| `--max-chars N` | `0` (none) | Truncate extracted text to N characters before sending to LLM |

- Extracts text from local PDFs using `pypdf`.
- Sends text to the configured LLM with a VC-focused prompt.
- Saves the result to the `synopsis` field in `iclr-2026.papers`.

### 5. Top Papers

List ICLR 2026 papers from the most prolific authors (by arXiv count):

```bash
uv run main.py top-papers [--limit N] [--export results.json]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--limit N` | `10` | Number of top authors to consider |
| `--export FILE` | — | Save results to a JSON file |

- Ranks authors by arXiv total hits.
- Displays ICLR 2026 papers authored by the top N.

### 6. Show Awards

List all authors with detected prior awards:

```bash
uv run main.py show-awards
```

- Queries the `authors` collection for `award_estimate_count > 0`.
- Prints each author, their count, and the matching publication titles/venues.

### 7. Awarded Papers

List ICLR 2026 papers authored by researchers with a prior award history:

```bash
uv run main.py awarded-papers
```

- Filters current conference papers where at least one author has a detected prior award.
- Useful for finding potentially high-impact work based on author track record.

### 8. Export Authors

Export a Google Sheets–ready CSV of all authors with paper and contact details:

```bash
uv run main.py export-authors [--output FILE]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--output FILE` | `authors_export.csv` | Output CSV file path |

Columns: `name`, `institution`, `email`, `paper_title`, `paper_url`, `synopsis`, `linkedin_url`

## Recommended Workflow

```
process-papers → process-authors → enrich-authors → generate-synopses → export-authors
```

## Data Structure

**Database**: `iclr-2026`

### `papers` Collection
```json
{
  "_id": "PaperID",
  "title": "Paper Title",
  "authors": ["Author 1", "Author 2"],
  "authorids": ["~ID1", "~ID2"],
  "decision": "Accept (Oral)",
  "venue": "ICLR 2026 Oral",
  "pdf_url": "https://openreview.net/pdf?id=...",
  "pdf_path": "/abs/path/to/pdfs/PaperID.pdf",
  "forum_url": "https://openreview.net/forum?id=...",
  "synopsis": "VC-friendly synopsis text...",
  "published_date": "ISODate(...)"
}
```

### `authors` Collection
```json
{
  "_id": "~OpenReviewID_or_Name",
  "names": ["Author Name"],
  "iclr_2026_count": 1,
  "institution": "University Name",
  "email": "author@example.com",
  "openreview": {
    "id": "~ID",
    "preferred_name": "Author Name",
    "institution": "University Name",
    "email": "author@example.com"
  },
  "arxiv": {
    "total_hits": 42,
    "papers": [{ "title": "...", "date": "...", "url": "..." }]
  },
  "ss_id": "SemanticScholar123",
  "award_estimate_count": 2,
  "award_details": [{ "title": "...", "venue": "...", "year": 2023 }],
  "linkedin_url": "https://linkedin.com/in/..."
}
```
