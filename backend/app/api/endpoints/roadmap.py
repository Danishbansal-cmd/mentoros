from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
# pyrefly: ignore [missing-import]
from bson import ObjectId
from datetime import datetime
from typing import List, Dict, Any

from app.schemas.roadmap import RoadmapRequest, RoadmapResponse, ChatRequest
from app.services.roadmap import create_roadmap, chat_with_roadmap
from app.services.auth import get_current_user
from app.database import roadmaps_collection, db
from app.services.chat_agent import run_chat_agent_background

router = APIRouter()

@router.post("/generate-roadmap", response_model=RoadmapResponse)
def generate_roadmap(request: RoadmapRequest, current_user: dict = Depends(get_current_user)):
    """
    Generate a roadmap for a specific goal and associate it with the authenticated user.
    """
    user_id = str(current_user["_id"])
    roadmap_content = create_roadmap(request.goal, user_id)
    
    # If the service returns an error in the list, raise HTTP exception or return it
    if roadmap_content and isinstance(roadmap_content, list) and "error" in roadmap_content[0]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=roadmap_content[0]["error"]
        )
        
    return RoadmapResponse(roadmap=roadmap_content)

@router.get("/roadmaps")
def get_roadmaps(current_user: dict = Depends(get_current_user)):
    """
    Fetch all roadmaps created by the logged-in user.
    """
    user_id = str(current_user["_id"])
    user_roadmaps = list(roadmaps_collection.find({"userId": user_id}).sort("createdAt", -1))
    
    # Format _id to string for frontend compatibility
    for r in user_roadmaps:
        r["id"] = str(r["_id"])
        del r["_id"]
        # Convert datetime to ISO string
        if "createdAt" in r and isinstance(r["createdAt"], datetime):
            r["createdAt"] = r["createdAt"].isoformat()
        if "updatedAt" in r and isinstance(r["updatedAt"], datetime):
            r["updatedAt"] = r["updatedAt"].isoformat()
            
    return user_roadmaps

@router.patch("/roadmaps/{roadmap_id}/tasks/{task_id}")
def update_task_details(
    roadmap_id: str,
    task_id: str,
    payload: dict,
    current_user: dict = Depends(get_current_user)
):
    """
    Update the status and/or notes of a specific task in the roadmap by its unique ID.
    """
    user_id = str(current_user["_id"])
    
    try:
        roadmap_obj_id = ObjectId(roadmap_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid roadmap ID format."
        )
        
    roadmap_doc = roadmaps_collection.find_one({"_id": roadmap_obj_id, "userId": user_id})
    if not roadmap_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Roadmap not found or unauthorized access."
        )
        
    tasks = roadmap_doc.get("roadmap", [])
    task_to_update = next((t for t in tasks if t.get("_id") == task_id), None)
    if not task_to_update:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found in this roadmap."
        )
        
    new_status = payload.get("status")
    new_notes = payload.get("notes")
    
    if new_status is not None:
        if new_status not in ["pending", "completed", "in_progress"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Status must be 'pending', 'completed', or 'in_progress'."
            )
        task_to_update["status"] = new_status
        
    if new_notes is not None:
        task_to_update["notes"] = str(new_notes)
        
    # Re-calculate progress stats
    completed_count = sum(1 for t in tasks if t.get("status") == "completed")
    
    roadmaps_collection.update_one(
        {"_id": roadmap_obj_id},
        {
            "$set": {
                "roadmap": tasks,
                "progress.completed": completed_count,
                "progress.total": len(tasks),
                "updatedAt": datetime.utcnow()
            }
        }
    )
    
    return {
        "success": True,
        "status": task_to_update.get("status"),
        "notes": task_to_update.get("notes"),
        "progress": {
            "completed": completed_count,
            "total": len(tasks)
        }
    }

@router.post("/roadmaps/{roadmap_id}/chat")
def chat_under_roadmap(
    roadmap_id: str,
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """
    Interact with the AI Mentor regarding a specific roadmap.
    Triggers an autonomous background agent run.
    """
    user_id = str(current_user["_id"])
    
    try:
        roadmap_obj_id = ObjectId(roadmap_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid roadmap ID format."
        )
        
    roadmap_doc = roadmaps_collection.find_one({"_id": roadmap_obj_id, "userId": user_id})
    if not roadmap_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Roadmap not found or unauthorized access."
        )
        
    # Append the user's message immediately to the chat history
    user_msg = {
        "role": "user",
        "content": request.message,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    roadmaps_collection.update_one(
        {"_id": roadmap_obj_id},
        {
            "$push": {"chatHistory": user_msg},
            "$set": {
                "status": "agent_running",
                "updatedAt": datetime.utcnow()
            }
        }
    )
    
    # Initialize the background agent log entry
    db["chat_agent_runs"].update_many(
        {"roadmapId": roadmap_id, "status": "running"},
        {"$set": {"status": "failed", "summary": "Terminated by new user interaction."}}
    )
    
    db["chat_agent_runs"].insert_one({
        "roadmapId": roadmap_id,
        "status": "running",
        "logs": [
            {
                "timestamp": datetime.utcnow().isoformat(),
                "message": "Initiating AI Mentor background agent...",
                "type": "info"
            }
        ],
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow()
    })
    
    # Trigger the background worker thread
    background_tasks.add_task(
        run_chat_agent_background,
        roadmap_id,
        user_id,
        request.message
    )
    
    # Refetch chat history to return it
    fresh_doc = roadmaps_collection.find_one({"_id": roadmap_obj_id})
    
    return {
        "success": True,
        "status": "agent_running",
        "chatHistory": fresh_doc.get("chatHistory", [])
    }

@router.get("/roadmaps/{roadmap_id}/chat-status")
def get_chat_agent_status(
    roadmap_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Query the running logs and status of the background chat agent.
    """
    user_id = str(current_user["_id"])
    
    try:
        roadmap_obj_id = ObjectId(roadmap_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid roadmap ID format."
        )
        
    roadmap_doc = roadmaps_collection.find_one({"_id": roadmap_obj_id, "userId": user_id})
    if not roadmap_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Roadmap not found or unauthorized access."
        )
        
    # Get the latest run logs for this roadmap
    latest_run = db["chat_agent_runs"].find_one(
        {"roadmapId": roadmap_id},
        sort=[("_id", -1)]
    )
    
    if not latest_run:
        return {"run": None}
        
    latest_run["id"] = str(latest_run["_id"])
    del latest_run["_id"]
    if "createdAt" in latest_run and isinstance(latest_run["createdAt"], datetime):
        latest_run["createdAt"] = latest_run["createdAt"].isoformat()
    if "updatedAt" in latest_run and isinstance(latest_run["updatedAt"], datetime):
        latest_run["updatedAt"] = latest_run["updatedAt"].isoformat()
        
    return {"run": latest_run}
