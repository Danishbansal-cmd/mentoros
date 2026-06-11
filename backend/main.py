# pyrefly: ignore [missing-import]
import os
from fastapi import FastAPI
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
from app.api.endpoints import roadmap, auth

load_dotenv()

app = FastAPI(title="MentorOS Backend API")

# Configure CORS
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://danishbansal-mentoros.onrender.com",
]

# Allow additional origins via environment variable
additional_origins = os.getenv("ALLOWED_ORIGINS")
if additional_origins:
    origins.extend([o.strip() for o in additional_origins.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(roadmap.router)

@app.get("/")
async def root():
    return {"message": "Welcome to the MentorOS API"}
