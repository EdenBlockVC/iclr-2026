import typer
import os
import re
import requests
import time
import arxiv
from datetime import datetime
from pymongo import MongoClient
from openreview.api import OpenReviewClient
from tqdm import tqdm
from dotenv import load_dotenv
from ddgs import DDGS

# Load environment variables
load_dotenv()

app = typer.Typer()

# Constants
OPENREVIEW_BASEURL = 'https://api2.openreview.net'
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "iclr-2026"
COLLECTION_NAME = "papers"
AUTHORS_COLLECTION = "authors"
PDF_DIR = "pdfs"

def download_pdf(url, save_path):
    """Downloads PDF from url to save_path."""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"Error downloading PDF from {url}: {e}")
        return False

@app.command()
def process_papers():
    """
    Scrapes ICLR 2026 'Accept (Oral)' papers,
    downloads PDFs, and stores metadata in MongoDB.
    """
    print(f"Connecting to MongoDB at {MONGO_URI}...")
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    collection = db[COLLECTION_NAME]

    # Create PDF directory if it doesn't exist
    if not os.path.exists(PDF_DIR):
        os.makedirs(PDF_DIR)

    print("Initializing OpenReview Client...")
    try:
        client = OpenReviewClient(
            baseurl=OPENREVIEW_BASEURL,
            username=os.getenv('OPENREVIEW_USERNAME'),
            password=os.getenv('OPENREVIEW_PASSWORD')
        )
    except Exception as e:
        print(f"Failed to initialize client: {e}")
        return

    print("Fetching 'Accept (Oral)' papers...")
    # Efficient query using venue content
    papers = client.get_all_notes(content={'venue': 'ICLR 2026 Oral'})
    print(f"Found {len(papers)} Accept (Oral) papers.")

    processed_count = 0
    new_count = 0

    for paper in tqdm(papers, desc="Processing Papers"):
        try:
            paper_id = paper.id
            content = paper.content
            
            title = content.get('title', {}).get('value', 'Untitled')
            authors = content.get('authors', {}).get('value', [])
            authorids = content.get('authorids', {}).get('value', [])
            
            # Timestamp handling
            ts = paper.pdate if paper.pdate else paper.cdate
            published_date = datetime.fromtimestamp(ts / 1000.0) if ts else datetime.now()
            
            # PDF handling
            # PDF value is usually relative path e.g. /pdf/id.pdf
            pdf_suffix = content.get('pdf', {}).get('value', '')
            if pdf_suffix.startswith('/'):
                pdf_url = f"https://openreview.net{pdf_suffix}"
            else:
                 # fallback if it's full url or empty
                 pdf_url = pdf_suffix if pdf_suffix else f"https://openreview.net/pdf?id={paper_id}"

            pdf_filename = f"{paper_id}.pdf"
            pdf_path = os.path.join(PDF_DIR, pdf_filename)
            
            # Download PDF if not exists
            if not os.path.exists(pdf_path):
                # print(f"Downloading PDF: {title}")
                success = download_pdf(pdf_url, pdf_path)
                if not success:
                    print(f"Failed to download PDF for {paper_id}")
            
            # Upsert into MongoDB
            doc = {
                "_id": paper_id,
                "title": title,
                "authors": authors,
                "authorids": authorids,  # Added author IDs
                "published_date": published_date,
                "decision": "Accept (Oral)",
                "venue": "ICLR 2026 Oral",
                "pdf_url": pdf_url,
                "pdf_path": os.path.abspath(pdf_path),
                "forum_url": f"https://openreview.net/forum?id={paper.forum}",
                "processed_at": datetime.now()
            }
            
            result = collection.update_one(
                {"_id": paper_id},
                {"$set": doc},
                upsert=True
            )
            
            processed_count += 1
            if result.upserted_id:
                new_count += 1
                
        except Exception as e:
            print(f"Error processing paper {paper.id}: {e}")

    print(f"Finished processing.")
    print(f"Total Papers Found: {len(papers)}")
    print(f"Processed: {processed_count}")
    print(f"New Insertions: {new_count}")

@app.command()
def process_authors():
    """
    Analyzes authors from stored papers.
    Fetches profile from OpenReview (if available) and publication stats from arXiv.
    """
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    papers_col = db[COLLECTION_NAME]
    authors_col = db[AUTHORS_COLLECTION]
    
    print("Initializing OpenReview Client...")
    try:
        or_client = OpenReviewClient(
            baseurl=OPENREVIEW_BASEURL,
            username=os.getenv('OPENREVIEW_USERNAME'),
            password=os.getenv('OPENREVIEW_PASSWORD')
        )
    except Exception as e:
        print(f"Failed to initialize OpenReview client: {e}")
        return

    # 1. Collect all unique authors from papers
    print("Collecting authors from papers...")
    all_papers = list(papers_col.find({}, {"authors": 1, "authorids": 1}))
    
    # Map author ID to Name (preferred) or Name to ID
    # We use a dictionary to deduplicate by ID if available, else by name.
    # Key: Author ID (if ~...) or Name. Value: {name, ids: set()}
    author_map = {}
    
    for p in all_papers:
        p_authors = p.get('authors', [])
        p_ids = p.get('authorids', [])
        
        # Zip them safely
        for i, name in enumerate(p_authors):
            aid = p_ids[i] if i < len(p_ids) else None
            
            # Use ID as key if it looks like a profile ID (~...)
            # Otherwise use name.
            key = aid if (aid and aid.startswith('~')) else name
            
            if key not in author_map:
                author_map[key] = {
                    "names": {name},
                    "ids": {aid} if aid else set(),
                    "papers_in_dataset": 0
                }
            else:
                author_map[key]["names"].add(name)
                if aid:
                    author_map[key]["ids"].add(aid)
            
            author_map[key]["papers_in_dataset"] += 1

    print(f"Found {len(author_map)} unique authors to process.")
    
    # Process each author
    for key, data in tqdm(author_map.items(), desc="Processing Authors"):
        # Check if already processed recently?
        # For now, simplistic upsert.
        
        primary_name = list(data["names"])[0]
        primary_id = list(data["ids"])[0] if data["ids"] else None
        
        # OpenReview Profile
        or_profile = {}
        author_institution = None
        author_email = None
        if primary_id and primary_id.startswith('~'):
            try:
                # API V2 get_profile
                p = or_client.get_profile(primary_id)
                if p:
                    author_institution = p.content.get('history', [{}])[0].get('institution', {}).get('name') if p.content.get('history') else None
                    # Preferred email first, then fall back to first in emails list
                    author_email = p.content.get('preferredEmail') or (p.content.get('emails', [None])[0])
                    or_profile = {
                        "id": p.id,
                        "preferred_name": p.get_preferred_name(),
                        "institution": author_institution,
                        "email": author_email,
                    }
            except Exception:
                pass
        
        # arXiv Stats
        arxiv_stats = {"total_hits": 0, "papers": []}
        try:
            # Search by name.
            # Note: Searching by name is ambiguous.
            search_query = f'au:"{primary_name}"'
            search = arxiv.Client().results(
                arxiv.Search(
                    query=search_query,
                    max_results=100, # Limit to avoid overload
                    sort_by=arxiv.SortCriterion.SubmittedDate
                )
            )

            papers_found = []

            # Collect all results (generator).
            for result in search:
                papers_found.append({
                    "title": result.title,
                    "date": result.published,
                    "url": result.entry_id
                })

            count = len(papers_found)
            arxiv_stats["total_hits"] = "50+" if count == 50 else count
            arxiv_stats["papers"] = papers_found

        except Exception as e:
            # print(f"arXiv error for {primary_name}: {e}")
            pass

        # Prepare doc
        author_doc = {
            "_id": key, # ~ID or Name
            "names": list(data["names"]),
            "ids": list(data["ids"]),
            "iclr_2026_count": data["papers_in_dataset"],
            "institution": author_institution,
            "email": author_email,
            "openreview": or_profile,
            "arxiv": arxiv_stats,
            "updated_at": datetime.now()
        }
        
        try:
            authors_col.update_one(
                {"_id": key},
                {"$set": author_doc},
                upsert=True
            )
        except Exception as e:
            print(f"Error saving author {key}: {e}")

    print("Author processing complete.")

@app.command()
def top_papers(limit: int = 10, export: str = None):
    """
    Lists papers from the top prolific authors (based on arXiv stats).
    """
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    authors_col = db[AUTHORS_COLLECTION]
    papers_col = db[COLLECTION_NAME] # iclr-2026.papers

    print("Fetching top authors...")
    authors = list(authors_col.find({}))
    
    # Sort authors by arXiv total_hits
    def get_hits(a):
        hits = a.get('arxiv', {}).get('total_hits', 0)
        if isinstance(hits, str) and "50+" in hits:
            return 50 # Treat as high number
        return int(hits) if isinstance(hits, int) else 0

    authors.sort(key=get_hits, reverse=True)
    
    top_authors = authors[:limit]
    
    print(f"\n--- Top {limit} Authors (by arXiv count) ---")
    for i, author in enumerate(top_authors):
        hits = author.get('arxiv', {}).get('total_hits', 0)
        name = author.get('names', ['Unknown'])[0]
        print(f"{i+1}. {name} ({hits} papers)")

    # Collect papers for these authors
    print("\n--- Papers by Top Authors ---")
    
    top_author_names = set()
    for ta in top_authors:
        top_author_names.update(ta.get('names', []))
    
    # Find papers
    # Since MongoDB stored 'authors' as list of strings, we use $in
    query = {"authors": {"$in": list(top_author_names)}}
    papers = list(papers_col.find(query))
    
    # Organize by author to show clearly? Or list papers.
    # Let's list papers and mention which top author(s) are on it.
    
    results = []

    for p in papers:
        p_authors = p.get('authors', [])
        # find intersection
        intersect = [a for a in p_authors if a in top_author_names]
        
        paper_info = {
            "title": p.get('title'),
            "top_authors_on_paper": intersect,
            "all_authors": p_authors,
            "pdf_url": p.get('pdf_url'),
            "local_pdf": p.get('pdf_path')
        }
        results.append(paper_info)

        print(f"\nTitle: {paper_info['title']}")
        print(f"Top Authors: {', '.join(intersect)}")
        print(f"PDF: {paper_info['local_pdf']}")

    if export:
        import json
        with open(export, 'w') as f:
            # datetime not serializable, convert if needed but we constructed dicts with strings
            json.dump(results, f, indent=2)
        print(f"\nExported {len(results)} papers to {export}")

def make_request_with_backoff(url, params=None, max_retries=5, backoff_factor=1.0):
    """
    Makes a GET request with exponential backoff for 429 situations.
    """
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params)
            if r.status_code == 200:
                return r
            elif r.status_code == 429:
                sleep_time = backoff_factor * (2 ** attempt)
                print(f"Rate limited (429). Retrying in {sleep_time}s...")
                time.sleep(sleep_time)
            else:
                # Other errors, maybe transient?
                if r.status_code >= 500:
                    sleep_time = backoff_factor * (2 ** attempt)
                    time.sleep(sleep_time)
                else:
                     return r # Return error response
        except Exception as e:
            print(f"Request exception: {e}")
            sleep_time = backoff_factor * (2 ** attempt)
            time.sleep(sleep_time)
            
    return None


# ---------------------------------------------------------------------------
# LinkedIn helpers
# ---------------------------------------------------------------------------

def search_linkedin_candidates(name: str, institution: str = None, max_results: int = 5) -> list:
    """
    Uses DuckDuckGo to search for the person's LinkedIn profile.
    Returns a list of {title, href, body} dicts (up to max_results).
    """
    parts = [f'"{name}"']
    if institution:
        parts.append(f'"{institution}"')
    parts.append('site:linkedin.com/in')
    query = ' '.join(parts)

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return results
    except Exception as e:
        print(f"  DDGS search error for {name}: {e}")
        return []


def build_llm_client():
    """
    Reads LLM_PROVIDER / LLM_MODEL from env and returns a callable:
        ask(prompt: str) -> str

    Supported providers: ollama, openai, anthropic, vllm
    """
    provider = os.getenv('LLM_PROVIDER', 'ollama').lower()
    model = os.getenv('LLM_MODEL', 'gpt-oss:20b')

    if provider == 'ollama':
        base_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')
        chat_url = f"{base_url}/api/chat"

        def ask(prompt: str) -> str:
            payload = {
                "model": model,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}]
            }
            r = requests.post(chat_url, json=payload, timeout=600)
            r.raise_for_status()
            return r.json().get('message', {}).get('content', '').strip()

        return ask

    elif provider == 'openai':
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

        def ask(prompt: str) -> str:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            return response.choices[0].message.content.strip()

        return ask

    elif provider == 'anthropic':
        import anthropic as anthropic_sdk
        client = anthropic_sdk.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

        def ask(prompt: str) -> str:
            response = client.messages.create(
                model=model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()

        return ask

    elif provider == 'vllm':
        # vLLM serves an OpenAI-compatible API; reuse the openai SDK.
        from openai import OpenAI
        base_url = os.getenv('VLLM_BASE_URL', 'http://localhost:8000/v1').rstrip('/')
        api_key = os.getenv('VLLM_API_KEY', 'EMPTY')  # local vLLM typically needs no key
        client = OpenAI(base_url=base_url, api_key=api_key)

        def ask(prompt: str) -> str:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            return response.choices[0].message.content.strip()

        return ask

    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: '{provider}'. Use ollama, openai, anthropic, or vllm.")


def validate_linkedin_with_llm(ask, author_name: str, institution: str, candidates: list) -> str | None:
    """
    Asks the LLM to identify which (if any) of the DuckDuckGo search results
    corresponds to the target person.

    Returns the LinkedIn URL string on a confident match, or None.
    """
    if not candidates:
        return None

    candidate_lines = []
    for i, c in enumerate(candidates, 1):
        candidate_lines.append(
            f"{i}. Title: {c.get('title', '')}\n"
            f"   URL: {c.get('href', '')}\n"
            f"   Snippet: {c.get('body', '')}"
        )
    candidates_text = "\n".join(candidate_lines)

    institution_hint = f" at {institution}" if institution else ""
    prompt = (
        f"You are verifying LinkedIn profiles for an academic researcher.\n"
        f"Target person: {author_name}{institution_hint}\n\n"
        f"Below are DuckDuckGo search results. Identify which result is the official "
        f"LinkedIn profile for this exact person.\n\n"
        f"{candidates_text}\n\n"
        f"Rules:\n"
        f"- Reply with ONLY the full LinkedIn URL (e.g. https://linkedin.com/in/...) "
        f"if you are confident it matches the target person.\n"
        f"- Reply with NONE if no result is a confident match.\n"
        f"- Do not include any explanation or extra text."
    )

    try:
        response = ask(prompt)
        # Extract a linkedin.com/in/... URL from the response
        match = re.search(r'https?://(?:www\.)?linkedin\.com/in/[\w\-%.]+', response)
        if match:
            return match.group(0)
        if 'NONE' in response.upper():
            return None
        return None
    except Exception as e:
        print(f"  LLM validation error: {e}")
        return None

@app.command()
def enrich_authors(limit: int = 0, force: bool = False):
    """
    Enriches author data with award estimates from Semantic Scholar
    and LinkedIn profile URLs via DuckDuckGo + LLM validation.
    Uses ICLR 2026 papers to resolve Author IDs accurately.
    Pass --force to re-fetch LinkedIn profiles for already-enriched authors.
    """
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    try:
        authors_col = db[AUTHORS_COLLECTION]
        papers_col = db[COLLECTION_NAME]
    except Exception as e:
        print(f"DB Error: {e}")
        return

    # Get authors who need enrichment (or all if we want to update)
    # targeting those without 'ss_id' or force update?
    # For now, process all or limit.
    query = {}
    total_authors = authors_col.count_documents(query)
    print(f"Found {total_authors} authors to enrich.")
    
    cursor = authors_col.find(query)
    if limit > 0:
        cursor = cursor.limit(limit)

    # Build LLM client once (reused across all authors)
    print("Initializing LLM client...")
    try:
        ask = build_llm_client()
    except Exception as e:
        print(f"Failed to build LLM client: {e}")
        return

    processed = 0
    updated = 0

    for author_doc in tqdm(list(cursor), desc="Enriching Authors"):
        processed += 1
        name = author_doc.get('names', [''])[0]
        aid = author_doc.get('_id')
        
        # Check if already has SS data? verify update strategy.
        # if 'ss_id' in author_doc: continue 
        
        # 1. Find a paper they authored to resolve ID
        paper = papers_col.find_one({"authors": name})
        if not paper:
            # Should not happen if data is consistent
            continue
            
        paper_title = paper.get('title')
        
        # 2. Search SS for this paper
        ss_author_id = None
        
        try:
            # Search Paper
            search_url = "https://api.semanticscholar.org/graph/v1/paper/search"
            # Use backoff
            r = make_request_with_backoff(search_url, params={"query": paper_title, "fields": "authors", "limit": 1})
            
            if r and r.status_code == 200:
                data = r.json()
                if 'data' in data and data['data']:
                    ss_paper = data['data'][0]
                    # Find matching author
                    for a in ss_paper.get('authors', []):
                        # Simple name match? 
                        # name in DB: "Evgeny Burnaev"
                        # name in SS: "E. Burnaev" or "Evgeny Burnaev"
                        # We use simple inclusion or approximate match?
                        # Let's try flexible match.
                        a_name = a.get('name', '')
                        if not a_name: continue
                        
                        # Check if last names match and first initial?
                        # Normalize
                        db_parts = name.lower().split()
                        ss_parts = a_name.lower().split()
                        
                        if len(db_parts) > 0 and len(ss_parts) > 0:
                            # Last name match
                            if db_parts[-1] == ss_parts[-1]:
                                ss_author_id = a.get('authorId')
                                break
        except Exception as e:
            # print(f"SS Search Error: {e}")
            pass
            
        if not ss_author_id:
            # Fallback: Search author by name? (Less reliable)
            pass
        else:
            # 3. Fetch Author Details (Awards check)
            try:
                # rate limit
                time.sleep(1.0) # be nice to public API
                
                details_url = f"https://api.semanticscholar.org/graph/v1/author/{ss_author_id}"
                # We need papers to scan for awards
                d_params = {
                    "fields": "papers.venue,papers.publicationVenue,papers.title,papers.year",
                    "limit": 500
                }
                
                # Use backoff
                r2 = make_request_with_backoff(details_url, params=d_params)
                
                if r2 and r2.status_code == 200:
                    details = r2.json()
                    papers_list = details.get('papers', [])
                    
                    # 4. Count Awards
                    award_keywords = ['best paper', 'award', 'spotlight', 'oral', 'distinguished', 'prize']
                    # Note: "Oral" might match "Temporal..." if insensitive? -> No, "Oral" is usually a standalone word or "Oral Presentation".
                    # Be careful with "Oral". In ICLR context, we are looking for filtered papers too.
                    # But checking previous history.
                    
                    award_count = 0
                    award_matches = []
                    
                    for p in papers_list:
                        venue_str = (p.get('venue') or '') + " " + (str(p.get('publicationVenue') or ''))
                        venue_lower = venue_str.lower()
                        title_lower = (p.get('title') or '').lower()
                        
                        # Heuristic check
                        found_kw = []
                        for kw in award_keywords:
                            if kw in venue_lower:
                                found_kw.append(kw)
                        
                        if found_kw:
                            award_count += 1
                            award_matches.append({
                                "title": p.get('title'),
                                "venue": venue_str,
                                "year": p.get('year'),
                                "keywords": found_kw
                            })
                            
                    # Update DB
                    authors_col.update_one(
                        {"_id": aid},
                        {"$set": {
                            "ss_id": ss_author_id,
                            "award_estimate_count": award_count,
                            "award_details": award_matches,
                            "enriched_at": datetime.now()
                        }}
                    )
                    updated += 1

            except Exception as e:
                pass

        # --- LinkedIn enrichment ---
        # Skip if already done and not forcing
        if not force and author_doc.get('linkedin_url'):
            continue

        institution = author_doc.get('openreview', {}).get('institution')

        candidates = search_linkedin_candidates(name, institution)
        time.sleep(1.5)  # polite delay between DDGS queries

        if candidates:
            linkedin_url = validate_linkedin_with_llm(ask, name, institution, candidates)
            if linkedin_url:
                try:
                    authors_col.update_one(
                        {"_id": aid},
                        {"$set": {
                            "linkedin_url": linkedin_url,
                            "linkedin_verified_at": datetime.now()
                        }}
                    )
                except Exception as e:
                    print(f"  Error saving LinkedIn URL for {name}: {e}")

    print(f"Enrichment complete. Processed {processed}. Updated {updated}.")

@app.command()
def show_awards():
    """
    Lists authors with detected awards.
    """
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    authors_col = db[AUTHORS_COLLECTION]
    
    # query for award_estimate_count > 0
    query = {"award_estimate_count": {"$gt": 0}}
    authors = list(authors_col.find(query).sort("award_estimate_count", -1))
    
    print(f"Found {len(authors)} authors with potential awards.")
    
    for a in authors:
        name = a.get('names', [''])[0]
        count = a.get('award_estimate_count')
        details = a.get('award_details', [])
        print(f"\nAuthor: {name} (Count: {count})")
        for d in details:
            print(f"  - {d.get('title')} ({d.get('venue')})")

@app.command()
def awarded_papers():
    """
    Lists ICLR 2026 papers authored by individuals who have previously received awards.
    """
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    authors_col = db[AUTHORS_COLLECTION]
    papers_col = db[COLLECTION_NAME]
    
    # 1. Get awarded authors
    query = {"award_estimate_count": {"$gt": 0}}
    awarded_authors_docs = list(authors_col.find(query))
    
    if not awarded_authors_docs:
        print("No authors with detected awards found.")
        return

    # Extract names
    awarded_names = set()
    author_map = {} # Name -> Award Details
    for doc in awarded_authors_docs:
        for name in doc.get('names', []):
            awarded_names.add(name)
            author_map[name] = doc

    print(f"Found {len(awarded_names)} distinct names for {len(awarded_authors_docs)} awarded authors.")

    # 2. Find papers
    paper_query = {"authors": {"$in": list(awarded_names)}}
    papers = list(papers_col.find(paper_query))
    
    print(f"\n--- ICLR 2026 Papers by Awarded Authors ({len(papers)} found) ---")
    
    for p in papers:
        title = p.get('title')
        url = p.get('pdf_url')
        p_authors = p.get('authors', [])
        
        # Identify which authors are the awarded ones
        awards_on_paper = []
        for a in p_authors:
            if a in awarded_names:
                awards_on_paper.append(a)
        
        print(f"\nTitle: {title}")
        print(f"Awarded Authors: {', '.join(awards_on_paper)}")
        print(f"URL: {url}")
        
        for a in awards_on_paper:
            details = author_map[a].get('award_details', [])
            print(f"  * {a}: {len(details)} prior awards detected.")

@app.command()
def generate_synopses(
    limit: int = 0,
    force: bool = False,
    max_pages: int = 0,
    max_chars: int = 0,
):
    """
    Generates a synopsis for each paper in the DB by reading its local PDF.
    Extracts text with pypdf, sends it to the configured LLM, and saves the
    synopsis back to the 'synopsis' field in MongoDB.

    --limit N      Process only N papers (0 = all).
    --force        Re-generate synopses for papers that already have one.
    --max-pages N  Read at most N pages per PDF (0 = all pages).
    --max-chars N  Truncate extracted text to N characters before sending to
                   the LLM (0 = no truncation). A warning is printed when the
                   text is large and no limit is set.
    """
    from pypdf import PdfReader

    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    collection = db[COLLECTION_NAME]

    # Build LLM client
    print("Initializing LLM client...")
    try:
        ask = build_llm_client()
    except Exception as e:
        print(f"Failed to build LLM client: {e}")
        return

    # Fetch papers
    query = {} if force else {"synopsis": {"$exists": False}}
    total = collection.count_documents(query)
    print(f"Found {total} papers {'(all, force mode)' if force else 'without a synopsis'}.")

    cursor = collection.find(query)
    if limit > 0:
        cursor = cursor.limit(limit)

    processed = 0
    skipped = 0
    failed = 0

    for paper in tqdm(list(cursor), desc="Generating Synopses"):
        paper_id = paper.get("_id")
        title = paper.get("title", "Untitled")

        # Resolve PDF path
        pdf_path = paper.get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path):
            # Try to find by paper_id in pdfs dir
            candidate = os.path.join(PDF_DIR, f"{paper_id}.pdf")
            if os.path.exists(candidate):
                pdf_path = candidate
            else:
                # print(f"  PDF not found for: {title}")
                skipped += 1
                continue

        # Extract text from PDF
        try:
            reader = PdfReader(pdf_path)
            total_pages = len(reader.pages)
            pages_to_read = min(total_pages, max_pages) if max_pages > 0 else total_pages

            if max_pages == 0 and total_pages > 10:
                tqdm.write(f"  ⚠  '{title}': {total_pages} pages — consider --max-pages to limit context.")

            pages_text = []
            for i in range(pages_to_read):
                page_text = reader.pages[i].extract_text() or ""
                pages_text.append(page_text)
            full_text = "\n".join(pages_text).strip()
        except Exception as e:
            print(f"  Error reading PDF for '{title}': {e}")
            failed += 1
            continue

        if not full_text:
            skipped += 1
            continue

        # Optionally truncate; warn when text is large and no limit is set
        if max_chars > 0:
            truncated = full_text[:max_chars]
        else:
            truncated = full_text
            if len(full_text) > 20_000:
                tqdm.write(f"  ⚠  '{title}': {len(full_text):,} chars sent to LLM — consider --max-chars to limit context.")

        prompt = (
            f"You are a research analyst summarizing academic papers for a venture capital audience. Use simple language to explain the paper.\n\n"
            f"Paper title: {title}\n\n"
            f"Paper content (first few pages):\n{truncated}\n\n"
            f"Write a concise synopsis (3-5 sentences) covering:\n"
            f"1. What problem this paper addresses.\n"
            f"2. The key method or contribution.\n"
            f"3. The main result or finding.\n"
            f"4. Practical applications or use-cases this research unlocks.\n\n"
            f"Reply with ONLY the synopsis paragraph, no headings or bullet points."
        )

        try:
            synopsis = ask(prompt)
        except Exception as e:
            print(f"  LLM error for '{title}': {e}")
            failed += 1
            continue

        if not synopsis:
            skipped += 1
            continue

        # Save to DB
        try:
            collection.update_one(
                {"_id": paper_id},
                {"$set": {
                    "synopsis": synopsis,
                    "synopsis_generated_at": datetime.now()
                }}
            )
            processed += 1
        except Exception as e:
            print(f"  DB error saving synopsis for '{title}': {e}")
            failed += 1

    print(f"\nSynopsis generation complete.")
    print(f"  Generated : {processed}")
    print(f"  Skipped   : {skipped}  (no PDF or empty text)")
    print(f"  Failed    : {failed}")


@app.command()
def export_authors(
    output: str = "authors_export.csv",
):
    """
    Exports a CSV of authors with their ICLR 2026 paper details and LinkedIn URL.

    Columns: name, paper_title, paper_url, synopsis, linkedin_url

    The file is ready to be imported as a Google Sheet.
    """
    import csv

    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    authors_col = db[AUTHORS_COLLECTION]
    papers_col = db[COLLECTION_NAME]

    authors = list(authors_col.find({}))
    print(f"Found {len(authors)} authors.")

    rows = []

    for author in authors:
        name = author.get("names", [""])[0]
        linkedin_url = author.get("linkedin_url", "")
        institution = author.get("institution") or author.get("openreview", {}).get("institution", "")
        email = author.get("email") or author.get("openreview", {}).get("email", "")

        # Find all ICLR 2026 papers for this author
        author_names = author.get("names", [])
        papers = list(papers_col.find({"authors": {"$in": author_names}}))

        if papers:
            for paper in papers:
                rows.append({
                    "name": name,
                    "institution": institution,
                    "email": email,
                    "paper_title": paper.get("title", ""),
                    "paper_url": paper.get("forum_url", paper.get("pdf_url", "")),
                    "synopsis": paper.get("synopsis", ""),
                    "linkedin_url": linkedin_url,
                })
        else:
            # Author in DB but no paper found (shouldn't normally happen)
            rows.append({
                "name": name,
                "institution": institution,
                "email": email,
                "paper_title": "",
                "paper_url": "",
                "synopsis": "",
                "linkedin_url": linkedin_url,
            })

    fieldnames = ["name", "institution", "email", "paper_title", "paper_url", "synopsis", "linkedin_url"]

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Exported {len(rows)} rows to '{output}'.")


if __name__ == "__main__":
    app()

