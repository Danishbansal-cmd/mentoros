import os
# pyrefly: ignore [missing-import]
import certifi
# pyrefly: ignore [missing-import]
from pymongo import MongoClient
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

load_dotenv()

# Get MONGO_URI from .env
MONGO_URI = os.getenv("MONGO_URI")

# Pass certifi as tlsCAFile to fix macOS SSL Certificate Verify Failed errors
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())

# This selects the 'mentoros' database (or creates it if it doesn't exist)
db = client["mentoros"]

# This selects the 'roadmaps' collection inside the 'mentoros' database
roadmaps_collection = db["roadmaps"]

# This selects the 'users' collection inside the 'mentoros' database
users_collection = db["users"]
