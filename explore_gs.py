from scholarly import scholarly

def main():
    print("Searching for Yoshua Bengio on Google Scholar...")
    try:
        search_query = scholarly.search_author('Yoshua Bengio')
        author = next(search_query)
        print(f"Found author: {author['name']}")
        
        # Fill details
        print("Filling author details...")
        author = scholarly.fill(author)
        
        print(f"Interests: {author.get('interests')}")
        print(f"Cited by: {author.get('citedby')}")
        
        # Check for awards in 'coauthors' or other fields?
        # Usually awards are not in the standard schema.
        # Maybe in the bio? 
        print(f"Keys: {author.keys()}")
        
        # Check publications for "Best Paper" in title or source?
        pubs = author.get('publications', [])
        print(f"Publications count: {len(pubs)}")
        
        award_count = 0
        for i, pub in enumerate(pubs[:50]): # Check first 50
            # Need to fill pub to get details?
            # pub_filled = scholarly.fill(pub) # basic pub object has some info
            source = pub.get('bib', {}).get('citation', '')
            title = pub.get('bib', {}).get('title', '')
            
            if 'award' in source.lower() or 'best paper' in source.lower():
                print(f"Potential Award: {title} | Source: {source}")
                award_count += 1
                
        print(f"Awards found in first 50: {award_count}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
