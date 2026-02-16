import requests
import time

def main():
    # Semantic Scholar API (Graph API)
    # Search for an author by name "Evgeny Burnaev" was poor.
    # Try searching for a specific paper title first, get the author ID from there.
    
    paper_title = "Q-RAG: Long Context Multi‑Step Retrieval via Value‑Based Embedder Training"
    print(f"Searching for paper: {paper_title}")
    
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": paper_title,
        "fields": "title,authors"
    }
    
    try:
        r = requests.get(url, params=params)
        data = r.json()
        
        if 'data' in data and len(data['data']) > 0:
            paper = data['data'][0]
            print("Found paper:", paper['title'])
            
            # Find author
            target_author = None
            for a in paper['authors']:
                if "Burnaev" in a['name']:
                    target_author = a
                    break
            
            if target_author:
                print(f"Found Author: {target_author}")
                author_id = target_author['authorId']
                
                # Fetch author papers again with this ID
                details_url = f"https://api.semanticscholar.org/graph/v1/author/{author_id}"
                # Add 'paperCount' to see if it matches expectations
                d_params = {
                    "fields": "name,paperCount,hIndex,papers.title,papers.publicationVenue,papers.year",
                    "limit": 100 # Default is 100
                }
                
                r2 = requests.get(details_url, params=d_params)
                details = r2.json()
                
                print(f"Author: {details.get('name')}")
                print(f"Paper Count (Metadata): {details.get('paperCount')}")
                print(f"Papers Returned: {len(details.get('papers', []))}")
                
            else:
                print("Author not found in paper authors.")
        else:
            print("Paper not found.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
