import os
import time
# pyrefly: ignore [missing-import]
from google import genai
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Append current directory to sys.path to allow imports from app
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# pyrefly: ignore [missing-import]
from app.database import db

# Define dataset of verified resources
resources_data = [
    # Docker
    {
        "title": "Official Docker Documentation",
        "description": "The official guide to containerization, Dockerfiles, volumes, networks, and Docker Compose.",
        "url": "https://docs.docker.com/",
        "category": "Docker",
        "tags": ["docker", "containers", "devops", "orchestration", "volumes"]
    },
    {
        "title": "Docker Tutorial for Beginners (YouTube)",
        "description": "A comprehensive video tutorial covering container basics, Docker images, and multi-container setups.",
        "url": "https://www.youtube.com/watch?v=3c-iMh1YVkU",
        "category": "Docker",
        "tags": ["docker", "containers", "devops", "tutorial", "video"]
    },
    {
        "title": "Docker Compose Guide",
        "description": "Learn how to define and run multi-container Docker applications using a YAML configuration file.",
        "url": "https://docs.docker.com/compose/",
        "category": "Docker",
        "tags": ["docker", "docker-compose", "yaml", "orchestration", "containers"]
    },
    # Python
    {
        "title": "Official Python Tutorial",
        "description": "An introductory guide to Python basics, control flow, functions, data structures, and standard libraries.",
        "url": "https://docs.python.org/3/tutorial/",
        "category": "Python",
        "tags": ["python", "basics", "functions", "programming", "tutorial"]
    },
    {
        "title": "Real Python Learning Path",
        "description": "High-quality Python articles, videos, and quizzes covering web development, backend engineering, and testing.",
        "url": "https://realpython.com/",
        "category": "Python",
        "tags": ["python", "backend", "testing", "articles", "intermediate"]
    },
    # Next.js / React
    {
        "title": "Next.js Learn Platform",
        "description": "Interactive course to learn Next.js, app routing, React Server Components (RSC), page rendering, and deployment.",
        "url": "https://nextjs.org/learn",
        "category": "Frontend",
        "tags": ["nextjs", "react", "frontend", "routing", "rsc", "javascript"]
    },
    {
        "title": "React Documentation (new)",
        "description": "Learn React with hook-based components, state management, props, effects, and interactive UI design guidelines.",
        "url": "https://react.dev/",
        "category": "Frontend",
        "tags": ["react", "frontend", "hooks", "components", "javascript", "ui"]
    },
    # MongoDB
    {
        "title": "MongoDB Atlas Documentation",
        "description": "Guide to building cloud databases, triggers, Atlas Search, Vector Search, and database administration.",
        "url": "https://www.mongodb.com/docs/atlas/",
        "category": "MongoDB",
        "tags": ["mongodb", "atlas", "database", "nosql", "vector-search", "cloud"]
    },
    {
        "title": "MongoDB Developer Center",
        "description": "Articles and tutorials for building modern backend applications with MongoDB, Node.js, Python, and Java.",
        "url": "https://www.mongodb.com/developer/",
        "category": "MongoDB",
        "tags": ["mongodb", "database", "tutorials", "backend", "dev"]
    },
    # Git & GitHub
    {
        "title": "Pro Git Book",
        "description": "The complete, official guide to branching, merging, pull requests, version control, and remote repositories.",
        "url": "https://git-scm.com/book/en/v2",
        "category": "Git",
        "tags": ["git", "github", "version-control", "branching", "tutorial"]
    },
    {
        "title": "Learn Git Branching (Interactive)",
        "description": "An interactive, visual game to master git commands, branching, rebase, cherry-pick, and merge.",
        "url": "https://learngitbranching.js.org/",
        "category": "Git",
        "tags": ["git", "branching", "interactive", "version-control", "game"]
    },
    # System Design
    {
        "title": "System Design Primer",
        "description": "Learn how to build large-scale distributed systems, load balancers, caching, scaling, databases, and microservices.",
        "url": "https://github.com/donnemartin/system-design-primer",
        "category": "System Design",
        "tags": ["system-design", "scaling", "architecture", "distributed-systems", "interview"]
    },
    # Machine Learning
    {
        "title": "Machine Learning Specialization (Andrew Ng)",
        "description": "A fundamental course covering linear regression, logistic regression, neural networks, and decision trees.",
        "url": "https://www.coursera.org/specializations/machine-learning-introduction",
        "category": "Machine Learning",
        "tags": ["ml", "ai", "machine-learning", "regression", "neural-networks"]
    },
    {
        "title": "Fast.ai Practical Deep Learning",
        "description": "A hands-on, code-first course to train neural networks for computer vision, NLP, and tabular data analysis.",
        "url": "https://course.fast.ai/",
        "category": "Machine Learning",
        "tags": ["ml", "deep-learning", "neural-networks", "hands-on", "ai"]
    },
    # FastAPI & REST APIs
    {
        "title": "FastAPI Official Tutorial",
        "description": "Learn how to build high-performance, async Python web APIs with automatic OpenAPI (Swagger) documentation.",
        "url": "https://fastapi.tiangolo.com/tutorial/",
        "category": "FastAPI",
        "tags": ["fastapi", "python", "rest-api", "backend", "async", "swagger"]
    }
]

def seed_database():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY is not defined in the environment variables.")
        sys.exit(1)

    print("Initializing Gemini client...")
    client = genai.Client(api_key=api_key)

    collection = db["learning_resources"]
    print("Clearing existing learning resources...")
    collection.delete_many({})

    print(f"Generating embeddings and seeding {len(resources_data)} resources...")
    for index, item in enumerate(resources_data):
        # We will embed title, description, and tags joined together
        embedding_text = f"Title: {item['title']}\nDescription: {item['description']}\nCategory: {item['category']}\nTags: {', '.join(item['tags'])}"
        
        try:
            print(f"Computing embedding for resource {index + 1}/{len(resources_data)}: {item['title']}")
            response = client.models.embed_content(
                model='gemini-embedding-2',
                contents=embedding_text
            )
            embedding_vector = response.embeddings[0].values
            item["embedding"] = embedding_vector
            
            # Save to database
            collection.insert_one(item)
            time.sleep(0.3)  # Short sleep to respect rate limits
        except Exception as e:
            print(f"Failed to embed resource '{item['title']}': {e}")
            
    print("\nDatabase seeded successfully!")
    print(f"Total seeded resources in MongoDB: {collection.count_documents({})}")
    print("\nNext step: Create a Vector Search Index on the 'learning_resources' collection in MongoDB Atlas.")
    print("Use the following JSON configuration for the index (use name: 'vector_index'):")
    print("""
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 3072,
      "similarity": "cosine"
    }
  ]
}
""")

if __name__ == "__main__":
    seed_database()
