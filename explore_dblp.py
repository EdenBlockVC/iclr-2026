import requests

def main():
    # DBLP doesn't have a strong python client, but let's try 'dblp' if installed, or raw requests.
    # The 'dblp' package is simple.
    
    author_name = "Yoshua Bengio"
    print(f"Searching DBLP for {author_name}...")
    
    try:
        # Search author
        url = "https://dblp.org/search/author/api"
        params = {"q": author_name, "format": "json"}
        r = requests.get(url, params=params)
        data = r.json()
        
        hits = data.get('result', {}).get('hits', {}).get('hit', [])
        if hits:
            # Get first hit
            first_hit = hits[0]
            print(f"Found author: {first_hit['info']['author']}")
            url_pt = first_hit['info']['url']
            print(f"URL: {url_pt}")
            
            # Now fetch publications XML or JSON?
            # URL is usually like https://dblp.org/pid/b/YoshuaBengio
            # API to get pubs: https://dblp.org/pid/b/YoshuaBengio.xml
            
            pid = url_pt.split('/pid/')[-1]
            print(f"PID: {pid}")
            
            pub_url = f"https://dblp.org/pid/{pid}.xml" # or .json?
            print(f"Fetching pubs from {pub_url}")
            
            # DBLP XML is rich.
            r2 = requests.get(pub_url)
            # Check for "award" strings in the XML content?
            if "award" in r2.text.lower() or "best paper" in r2.text.lower():
                print("FOUND 'award' or 'best paper' in DBLP profile XML!")
                # We would need to parse this properly.
                # Count occurrences?
                count = r2.text.lower().count("best paper") + r2.text.lower().count("award")
                print(f"Rough award count mentions: {count}")
            else:
                 print("No awards mentions found in simple text scan.")

        else:
            print("Author not found.")
            
    except Exception as e:
        print(f"DBLP Error: {e}")

if __name__ == "__main__":
    main()
