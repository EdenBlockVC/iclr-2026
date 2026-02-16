import requests
import time

def main():
    # Semantic Scholar API (Graph API)
    # Search for an author by name
    author_name = "Evgeny Burnaev"
    print(f"Searching for author: {author_name}")
    
    url = "https://api.semanticscholar.org/graph/v1/author/search"
    params = {
        "query": author_name,
        "fields": "authorId,name,citationCount,hIndex,paperCount"
    }
    
    try:
        r = requests.get(url, params=params)
        data = r.json()
        
        if 'data' in data and len(data['data']) > 0:
            author = data['data'][0]
            print("Found author:", author)
            author_id = author['authorId']
            
            # Now fetch author details including papers with awards?
            # The API might not have a direct "award count". 
            # We might need to fetch papers and check for "journal" or "venue" or attributes?
            # Or look at "highlyInfluential citations"?
            
            print(f"Fetching details for ID: {author_id}")
            # fields=papers.title,papers.venue,papers.year,papers.citationCount
            # Check if there is an 'awards' field? Unlikely in free tier/public docs?
            
            # Let's check some fields
            details_url = f"https://api.semanticscholar.org/graph/v1/author/{author_id}"
            d_params = {
                "fields": "name,papers.title,papers.venue,papers.year,papers.publicationVenue,papers.journal"
            }
            
            r2 = requests.get(details_url, params=d_params)
            details = r2.json()
            
            papers = details.get('papers', [])
            print(f"Retrieved {len(papers)} papers.")
            
            # enhanced checking
            award_keywords = ['best paper', 'award', 'outstanding', 'prize']
            award_count = 0
            
            for p in papers:
                # Check venue/journal strings for awards?
                # Sometimes venue is "CVPR 2023 Best Paper"
                v = p.get('venue') or ''
                pv = p.get('publicationVenue') or {}
                j = p.get('journal') or {}
                
                info_str = f"{v} {pv} {j}".lower()
                
                if any(k in info_str for k in award_keywords):
                    print(f"Potential Award Paper: {p.get('title')} | Venue: {info_str}")
                    award_count += 1
            
            print(f"Estimated Award Count: {award_count}")
            
        else:
            print("Author not found.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
