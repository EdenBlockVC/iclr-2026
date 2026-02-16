from pymongo import MongoClient
import pprint

def main():
    try:
        client = MongoClient("mongodb://localhost:27017/")
        db = client["iclr-2026"]
        print("Connected to MongoDB")
        
        # Papers
        p_count = db.papers.count_documents({})
        print(f"Papers in DB: {p_count}")
        
        # Authors
        a_count = db.authors.count_documents({})
        print(f"Authors in DB: {a_count}")
        
        if a_count > 0:
            print("Sample Author (with SS ID if available):")
            adoc = db.authors.find_one({"ss_id": {"$exists": True}})
            if not adoc:
                print("No enriched authors found yet.")
                adoc = db.authors.find_one()
            pprint.pprint(adoc)
            
    except Exception as e:
        print(f"MongoDB connection failed: {e}")

if __name__ == "__main__":
    main()
