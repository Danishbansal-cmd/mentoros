# pyrefly: ignore [missing-import]
from pydantic import BaseModel
from typing import List, Dict, Any

class RoadmapRequest(BaseModel):
    goal: str
    user_id: str = "anonymous_user"  # Defaults to anonymous so frontend doesn't break

class RoadmapResponse(BaseModel):
    roadmap: List[Dict[str, Any]]

class ChatRequest(BaseModel):
    message: str
