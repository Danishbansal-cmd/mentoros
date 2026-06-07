import os
import json
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
# pyrefly: ignore [missing-import]
from bson import ObjectId
# pyrefly: ignore [missing-import]
from google import genai
# pyrefly: ignore [missing-import]
from google.genai import types
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from app.database import roadmaps_collection

# Load environment variables from .env file
load_dotenv()

def _generate_content_with_fallback(client: genai.Client, prompt: str, response_mime_type: str = "application/json") -> str:
    """
    Query Gemini client with fallback models and retry mechanism on 503/transient errors.
    """
    models_to_try = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash']
    response_text = None
    last_error = None
    
    for model in models_to_try:
        for attempt in range(3):
            try:
                print(f"Attempting to generate content with model: {model} (attempt {attempt + 1})")
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type=response_mime_type,
                    ),
                )
                if response and response.text:
                    # Validate that it is valid JSON if we expect JSON
                    if response_mime_type == "application/json":
                        json.loads(response.text)
                    response_text = response.text
                    print(f"Successfully generated content with model: {model}")
                    break
                else:
                    raise ValueError("Empty response text received")
            except Exception as e:
                last_error = e
                print(f"Error with model {model} (attempt {attempt + 1}): {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
        if response_text:
            break
            
    if not response_text:
        raise last_error if last_error else Exception("Failed to generate content with all fallback models.")
        
    return response_text

def create_roadmap(goal: str, user_id: str) -> List[Dict[str, Any]]:
    """
    Generate a rich learning roadmap using Google's Gemini LLM based on the goal
    and save it to MongoDB as a structured learning profile.
    """
    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return [{"error": "Server configuration error: Gemini API key is missing."}]

        client = genai.Client(api_key=api_key)
        
        prompt = f"""
        You are an expert career and learning mentor. 
        A user has provided the following goal: "{goal}"
        
        Please generate a comprehensive roadmap of learning modules/milestones to achieve this goal.
        Return it strictly as a JSON array of objects. 
        Each object should have:
        - "title" (string: short name of the topic/milestone, e.g. "Variables and Data Types")
        - "description" (string: detailed description of what to learn and achieve in this milestone)
        - "estimatedHours" (integer: estimated hours required to complete this milestone, e.g. 4)
        - "difficulty" (string: must be one of "beginner", "intermediate", or "advanced")
        - "prerequisites" (array of strings: titles of topics/milestones that should be completed before this one)
        - "resources" (array of strings: high-quality learning resources, article names, or links)
        - "projects" (array of strings: small project ideas, exercises, or hands-on practice items)
        """
        
        response_text = _generate_content_with_fallback(client, prompt, "application/json")
        roadmap_json = json.loads(response_text)

        # Initialize metadata on the backend for each task
        for item in roadmap_json:
            item["_id"] = str(ObjectId())
            item["status"] = "pending"
            item["quizIds"] = []
            item["notes"] = ""

        # Initialize the unique chat history for this roadmap
        chat_history = [
            {
                "role": "user",
                "content": f"Create a roadmap for: {goal}",
                "timestamp": datetime.utcnow().isoformat()
            },
            {
                "role": "model",
                "content": f"I have successfully generated your personalized learning roadmap for: '{goal}'. You can track your progress here, expand milestones to see detailed projects/resources/notes, or ask me to modify the schedule below!",
                "timestamp": datetime.utcnow().isoformat()
            }
        ]

        # Save to MongoDB learning profile
        document = {
            "userId": user_id,
            "goal": goal,
            "roadmap": roadmap_json,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
            "progress": {
                "completed": 0,
                "total": len(roadmap_json)
            },
            "reflection": [],
            "weakAreas": [],
            "chatHistory": chat_history
        }
        roadmaps_collection.insert_one(document)

        return roadmap_json
    except Exception as e:
        print(f"Error generating roadmap: {e}")
        return [{"error": f"Sorry, there was an error generating your roadmap: {str(e)}"}]

def chat_with_roadmap(roadmap_id: str, user_id: str, message: str) -> Dict[str, Any]:
    """
    Carry out an interactive chat discussion under a specific roadmap.
    Allows asking questions, adding details, or requesting edits to the roadmap.
    Updates MongoDB with the new chat message and any roadmap modifications.
    """
    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise Exception("Gemini API key is missing.")

        client = genai.Client(api_key=api_key)

        try:
            roadmap_obj_id = ObjectId(roadmap_id)
        except Exception:
            raise Exception("Invalid roadmap ID format.")

        roadmap_doc = roadmaps_collection.find_one({"_id": roadmap_obj_id, "userId": user_id})
        if not roadmap_doc:
            raise Exception("Roadmap not found or unauthorized access.")

        # Get existing roadmap data
        current_tasks = roadmap_doc.get("roadmap", [])
        chat_history = roadmap_doc.get("chatHistory", [])
        goal = roadmap_doc.get("goal", "")

        # Format past chat history for context
        formatted_history = ""
        for msg in chat_history:
            role_name = "User" if msg["role"] == "user" else "AI Mentor"
            formatted_history += f"{role_name}: {msg['content']}\n\n"

        # Build prompt instructing Gemini how to reply and optionally return updated roadmap tasks
        system_instruction = f"""
You are an expert career and learning mentor.
The user is viewing their personalized roadmap for the goal: "{goal}".
The current roadmap tasks are:
{json.dumps(current_tasks, indent=2)}

You are having an ongoing chat conversation with the user.
Here is the conversation history:
{formatted_history}

The user just sent the following message:
"{message}"

You must respond as the AI Mentor.
If the user's message is a general question or doesn't require modifying the roadmap structure, answer their question/discuss the topic, and do not provide an updated roadmap.
If the user's message asks to add, remove, change, update, or reorganize tasks/milestones in their roadmap, you should provide the updated roadmap containing the complete and final set of tasks.
To do this, you MUST return a JSON object with the following fields:
- "response": (string) Your conversational text response to the user explaining your answer or the changes you made. Keep it friendly, clear, and encouraging.
- "updated_roadmap": (array of objects, or null) If you modified the roadmap structure or tasks, provide the complete new list of roadmap tasks. If no changes are needed, set this field to null. Each task object in this array MUST contain the fields:
  - "title" (string)
  - "description" (string)
  - "estimatedHours" (integer)
  - "difficulty" (string: "beginner", "intermediate", "advanced")
  - "prerequisites" (array of strings)
  - "resources" (array of strings)
  - "projects" (array of strings)

Return only the JSON object.
"""

        response_text = _generate_content_with_fallback(client, system_instruction, "application/json")
        result_json = json.loads(response_text)

        conversational_response = result_json.get("response", "")
        updated_tasks = result_json.get("updated_roadmap")

        # Update chat history in list
        new_user_msg = {
            "role": "user",
            "content": message,
            "timestamp": datetime.utcnow().isoformat()
        }
        new_model_msg = {
            "role": "model",
            "content": conversational_response,
            "timestamp": datetime.utcnow().isoformat()
        }
        chat_history.append(new_user_msg)
        chat_history.append(new_model_msg)

        update_fields = {
            "chatHistory": chat_history,
            "updatedAt": datetime.utcnow()
        }

        # If roadmap tasks are updated, map status from old tasks to preserve progress
        if updated_tasks is not None and isinstance(updated_tasks, list):
            # Create a lookup map of old tasks to check statuses and metadata: title -> old_task
            old_tasks_map = {}
            for t in current_tasks:
                title_key = str(t.get("title")).strip().lower()
                old_tasks_map[title_key] = t

            final_tasks = []
            for t in updated_tasks:
                title_key = str(t.get("title")).strip().lower()
                old_task = old_tasks_map.get(title_key)
                
                if old_task:
                    # Preserve existing metadata
                    t["_id"] = old_task.get("_id", str(ObjectId()))
                    t["status"] = old_task.get("status", "pending")
                    t["notes"] = old_task.get("notes", "")
                    t["quizIds"] = old_task.get("quizIds", [])
                else:
                    # Initialize new task metadata
                    t["_id"] = str(ObjectId())
                    t["status"] = "pending"
                    t["notes"] = ""
                    t["quizIds"] = []
                final_tasks.append(t)

            completed_count = sum(1 for t in final_tasks if t.get("status") == "completed")
            update_fields["roadmap"] = final_tasks
            update_fields["progress.completed"] = completed_count
            update_fields["progress.total"] = len(final_tasks)
            current_tasks = final_tasks

        # Update DB
        roadmaps_collection.update_one(
            {"_id": roadmap_obj_id},
            {"$set": update_fields}
        )

        return {
            "response": conversational_response,
            "roadmap": current_tasks,
            "chatHistory": chat_history
        }

    except Exception as e:
        print(f"Error in chat_with_roadmap: {e}")
        raise e
