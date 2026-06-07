import os
import sys
# pyrefly: ignore [missing-import]
from google import genai
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Append current directory to sys.path to allow imports from app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# pyrefly: ignore [missing-import]
from app.services.roadmap import get_embedding, query_resources, search_resources_fallback, search_learning_resources
# pyrefly: ignore [missing-import]
from app.database import db

def run_tests():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY is not defined in the environment variables.")
        sys.exit(1)

    print("Initializing Gemini client...")
    client = genai.Client(api_key=api_key)

    # 1. Test Embedding Generation
    print("\n--- Test 1: Generate Embedding ---")
    test_text = "Docker containerization and orchestration basics"
    try:
        embedding = get_embedding(client, test_text)
        print(f"Embedding generated successfully. Length: {len(embedding)}")
        print(f"First 5 dimensions: {embedding[:5]}")
    except Exception as e:
        print(f"Failed to generate embedding: {e}")
        return

    # 2. Check learning_resources collection count
    print("\n--- Test 2: Database Resource Count ---")
    collection = db["learning_resources"]
    count = collection.count_documents({})
    print(f"Total documents in 'learning_resources' collection: {count}")

    # 3. Test Regex Fallback
    print("\n--- Test 3: Test Regex Fallback Search ---")
    fallback_query = "docker containers"
    print(f"Searching fallback for: '{fallback_query}'")
    fallback_results = search_resources_fallback(fallback_query, limit=2)
    print(f"Fallback results found: {len(fallback_results)}")
    for res in fallback_results:
        print(f" - Title: {res.get('title')}")
        print(f"   URL: {res.get('url')}")
        print(f"   Category: {res.get('category')}")

    # 4. Test Vector Search
    print("\n--- Test 4: Test Vector Search aggregation stage ---")
    vector_query = "Docker containerization and orchestration basics"
    print(f"Querying vector search for: '{vector_query}'")
    vector_results = query_resources(client, vector_query, limit=2)
    print(f"Vector search results found: {len(vector_results)}")
    for res in vector_results:
        print(f" - Title: {res.get('title')} (Score: {res.get('score')})")
        print(f"   URL: {res.get('url')}")
        print(f"   Category: {res.get('category')}")

    # 5. Test Unified Search
    print("\n--- Test 5: Test Unified search_learning_resources API ---")
    unified_query = "React hooks and state management"
    print(f"Querying unified search for: '{unified_query}'")
    unified_results = search_learning_resources(client, unified_query, limit=2)
    print(f"Unified results found: {len(unified_results)}")
    for res in unified_results:
        print(f" - Title: {res.get('title')}")
        print(f"   URL: {res.get('url')}")
        print(f"   Category: {res.get('category')}")

if __name__ == "__main__":
    run_tests()
