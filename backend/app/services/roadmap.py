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
from app.database import roadmaps_collection, db

# Load environment variables from .env file
load_dotenv()

def _generate_content_with_fallback(client: genai.Client, prompt: str, response_mime_type: str = "application/json") -> str:
    """
    Query Gemini client with fallback models and retry mechanism on 503/transient/quota errors.
    """
    models_to_try = [
        'gemini-2.0-flash', 
        'gemini-2.0-flash-lite', 
        'gemini-flash-latest',
        'gemini-2.5-flash-lite'
    ]
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
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    print(f"Quota exhausted for {model}. Skipping remaining attempts.")
                    break
                if attempt < 2:
                    time.sleep(2 ** attempt)
        if response_text:
            break
            
    if not response_text:
        raise last_error if last_error else Exception("Failed to generate content with all fallback models.")
        
    return response_text

def get_embedding(client: genai.Client, text: str) -> List[float]:
    """
    Generate a 3072-dimension vector embedding using gemini-embedding-2.
    """
    response = client.models.embed_content(
        model='gemini-embedding-2',
        contents=text,
    )
    return response.embeddings[0].values

def query_resources(client: genai.Client, query: str, limit: int = 2) -> List[Dict[str, Any]]:
    """
    Perform a semantic vector search query on MongoDB Atlas using the $vectorSearch stage.
    """
    try:
        query_vector = get_embedding(client, query)
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": 100,
                    "limit": limit
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "title": 1,
                    "description": 1,
                    "url": 1,
                    "category": 1,
                    "score": {"$meta": "vectorSearchScore"}
                }
            }
        ]
        results = list(db["learning_resources"].aggregate(pipeline))
        return results
    except Exception as e:
        print(f"Vector search failed (index might not be created or ready): {e}")
        return []

def search_resources_fallback(query: str, limit: int = 2) -> List[Dict[str, Any]]:
    """
    Fuzzy word-matching regex search fallback if Atlas Vector Search index is not yet built.
    Filters out common stop words to ensure relevant matches.
    """
    try:
        # Common English stop words
        STOP_WORDS = {
            "and", "or", "the", "a", "an", "to", "in", "for", "of", "with", "on", 
            "at", "by", "from", "is", "your", "this", "that", "it", "are", "be", 
            "as", "how", "what", "why", "who", "whom", "which", "whose", "when", 
            "where", "here", "there", "i", "you", "he", "she", "they", "we"
        }
        
        words = [w.strip().lower() for w in query.split() if w.strip()]
        cleaned_words = []
        for w in words:
            # Keep only alphanumeric characters
            cleaned = "".join(c for c in w if c.isalnum())
            if cleaned and cleaned not in STOP_WORDS and len(cleaned) > 2:
                cleaned_words.append(cleaned)
                
        if not cleaned_words:
            # Try original words without stop words
            cleaned_words = [w for w in words if w not in STOP_WORDS]
        if not cleaned_words:
            # Fallback to all input words
            cleaned_words = words
            
        if not cleaned_words:
            return []
            
        regex_query = "|".join(cleaned_words)
        cursor = db["learning_resources"].find(
            {"$or": [
                {"title": {"$regex": regex_query, "$options": "i"}},
                {"description": {"$regex": regex_query, "$options": "i"}},
                {"tags": {"$regex": regex_query, "$options": "i"}}
            ]}
        ).limit(limit)
        
        results = []
        for doc in cursor:
            results.append({
                "title": doc.get("title"),
                "description": doc.get("description"),
                "url": doc.get("url"),
                "category": doc.get("category")
            })
        return results
    except Exception as e:
        print(f"Fallback keyword search failed: {e}")
        return []

def search_learning_resources(client: genai.Client, query: str, limit: int = 2) -> List[Dict[str, Any]]:
    """
    Find relevant verified resources using Vector Search, falling back to regex matching if needed.
    """
    results = query_resources(client, query, limit)
    if not results:
        print("Vector search returned no results. Falling back to keyword regex search...")
        results = search_resources_fallback(query, limit)
    return results

def reflect_on_chat(client: genai.Client, roadmap_id: str, user_id: str, chat_history: List[Dict[str, Any]]):
    """
    Analyze the user's chat history to extract concepts they struggled with (weak areas)
    and write a reflection summary with action items. Updates MongoDB.
    """
    try:
        try:
            roadmap_obj_id = ObjectId(roadmap_id)
        except Exception:
            print(f"Invalid roadmap ID format in reflect_on_chat: {roadmap_id}")
            return

        # Format chat history for the prompt
        formatted_history = ""
        for msg in chat_history:
            role_name = "User" if msg.get("role") == "user" else "AI Mentor"
            formatted_history += f"{role_name}: {msg.get('content')}\n\n"

        prompt = f"""
        You are an expert educational psychologist and AI learning mentor.
        Analyze the following chat conversation between the User and the AI Mentor:
        
        {formatted_history}
        
        Identify any specific concepts, topics, or sub-skills the user is struggling with, has asked questions about multiple times, or explicitly said they find difficult (e.g. "Docker volumes", "CSS alignment").
        Also, draft a short reflection summary (1-2 sentences) of their current progress/understanding, and a mentor action item for future guidance.
        
        Return the result strictly as a JSON object with this format:
        {{
          "weak_areas": ["Docker Volumes"], // list of strings, keep them short (e.g. 1-3 words per topic)
          "reflection": {{
            "summary": "User is struggling to understand folder mapping in Docker. They asked for multiple examples.",
            "action_item": "Provide concrete examples showing host path vs container path comparisons."
          }}
        }}
        """

        response_text = _generate_content_with_fallback(client, prompt, "application/json")
        result_json = json.loads(response_text)

        weak_areas_detected = result_json.get("weak_areas", [])
        reflection_data = result_json.get("reflection", {})

        if not reflection_data.get("summary"):
            return

        roadmap_doc = roadmaps_collection.find_one({"_id": roadmap_obj_id, "userId": user_id})
        if not roadmap_doc:
            print(f"Roadmap not found in reflect_on_chat: {roadmap_id}")
            return

        existing_weak_areas = roadmap_doc.get("weakAreas", [])
        existing_reflections = roadmap_doc.get("reflection", [])

        # Update weak areas list
        updated_weak_areas = []
        weak_areas_dict = {item["topic"].lower().strip(): item for item in existing_weak_areas}

        for topic in weak_areas_detected:
            topic_clean = topic.strip()
            topic_key = topic_clean.lower()
            if topic_key in weak_areas_dict:
                weak_areas_dict[topic_key]["count"] += 1
                weak_areas_dict[topic_key]["lastSeen"] = datetime.utcnow().isoformat()
            else:
                weak_areas_dict[topic_key] = {
                    "topic": topic_clean,
                    "count": 1,
                    "lastSeen": datetime.utcnow().isoformat()
                }

        updated_weak_areas = list(weak_areas_dict.values())

        # Append new reflection log
        new_reflection = {
            "timestamp": datetime.utcnow().isoformat(),
            "summary": reflection_data.get("summary", ""),
            "actionItem": reflection_data.get("action_item", "")
        }
        existing_reflections.append(new_reflection)

        roadmaps_collection.update_one(
            {"_id": roadmap_obj_id},
            {
                "$set": {
                    "weakAreas": updated_weak_areas,
                    "reflection": existing_reflections,
                    "updatedAt": datetime.utcnow()
                }
            }
        )
        print(f"Successfully updated reflection logs and weak areas for roadmap {roadmap_id}")

    except Exception as e:
        print(f"Error in reflect_on_chat: {e}")

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
        
        # Aggregate user's weak areas from all past roadmaps
        historical_memory_context = ""
        try:
            past_roadmaps = list(roadmaps_collection.find({"userId": user_id}))
            historical_struggles = {}
            for r in past_roadmaps:
                for wa in r.get("weakAreas", []):
                    topic = wa.get("topic")
                    if topic:
                        topic_lower = topic.strip().lower()
                        historical_struggles[topic_lower] = historical_struggles.get(topic_lower, 0) + wa.get("count", 1)
            
            if historical_struggles:
                historical_memory_context = "\nCOGNITIVE MEMORY: The user has struggled with the following concepts in past roadmaps:\n"
                for topic, count in historical_struggles.items():
                    historical_memory_context += f"- {topic} (struggled {count} times)\n"
                historical_memory_context += "\nIf any of these topics are relevant to their new goal, customize the generated roadmap milestones by adding extra guidance, exercises, or resources for those topics to help them overcome these gaps.\n"
        except Exception as db_err:
            print(f"Failed to query past roadmaps for cognitive memory: {db_err}")

        prompt = f"""
        You are an expert career and learning mentor. 
        A user has provided the following goal: "{goal}"
        {historical_memory_context}
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

        # Initialize metadata on the backend for each task and enrich with real resources from Vector DB
        for item in roadmap_json:
            item["_id"] = str(ObjectId())
            item["status"] = "pending"
            item["quizIds"] = []
            item["notes"] = ""
            
            # Fetch verified resources from MongoDB Vector Search/Fallback matching
            topic_query = f"{item.get('title', '')} {item.get('description', '')}"
            real_resources = search_learning_resources(client, topic_query, limit=2)
            
            # Extract URLs from the matched resources and combine them with the LLM's generated ones
            real_links = [res["url"] for res in real_resources if "url" in res]
            item["resources"] = list(set(real_links + item.get("resources", [])))

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
        weak_areas = roadmap_doc.get("weakAreas", [])
        reflection_logs = roadmap_doc.get("reflection", [])

        # Format past chat history for context
        formatted_history = ""
        for msg in chat_history:
            role_name = "User" if msg["role"] == "user" else "AI Mentor"
            formatted_history += f"{role_name}: {msg['content']}\n\n"

        # Fetch active cognitive reflection/memory from database
        memory_context = ""
        if weak_areas:
            memory_context += "\nAI REFLECTION MEMORY: You have previously identified that the user is struggling with the following concepts:\n"
            for wa in weak_areas:
                memory_context += f"- {wa['topic']} (struggled {wa['count']} times)\n"
        if reflection_logs:
            memory_context += "\nYour past reflection logs for this user:\n"
            for ref in reflection_logs[-3:]:
                memory_context += f"- {ref['summary']}\n"

        # Fetch relevant real learning resources matching the user's message using Vector Search
        relevant_resources = search_learning_resources(client, message, limit=2)
        resources_context = ""
        if relevant_resources:
            resources_context = "\nHere are some verified learning resources from the database that match the user's query topic. You can suggest these links directly if relevant:\n"
            for r in relevant_resources:
                resources_context += f"- [{r['title']}]({r['url']}): {r['description']}\n"

        # Build prompt instructing Gemini how to reply and optionally return updated roadmap tasks
        system_instruction = f"""
You are an expert career and learning mentor.
The user is viewing their personalized roadmap for the goal: "{goal}".
The current roadmap tasks are:
{json.dumps(current_tasks, indent=2)}

You are having an ongoing chat conversation with the user.
Here is the conversation history:
{formatted_history}
{memory_context}
{resources_context}

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
                    
                    # Re-enrich resources just in case, combining with what model outputs
                    topic_query = f"{t.get('title', '')} {t.get('description', '')}"
                    real_resources = search_learning_resources(client, topic_query, limit=2)
                    real_links = [res["url"] for res in real_resources if "url" in res]
                    t["resources"] = list(set(real_links + t.get("resources", [])))
                else:
                    # Initialize new task metadata
                    t["_id"] = str(ObjectId())
                    t["status"] = "pending"
                    t["notes"] = ""
                    t["quizIds"] = []
                    
                    # Enrich resources for new tasks
                    topic_query = f"{t.get('title', '')} {t.get('description', '')}"
                    real_resources = search_learning_resources(client, topic_query, limit=2)
                    real_links = [res["url"] for res in real_resources if "url" in res]
                    t["resources"] = list(set(real_links + t.get("resources", [])))
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

        # Call reflect_on_chat inline to update the cognitive profiles
        reflect_on_chat(client, roadmap_id, user_id, chat_history)

        # Re-fetch the updated roadmap document from database to get the fresh weakAreas and reflection
        updated_doc = roadmaps_collection.find_one({"_id": roadmap_obj_id})
        fresh_weak_areas = updated_doc.get("weakAreas", [])
        fresh_reflection = updated_doc.get("reflection", [])

        return {
            "response": conversational_response,
            "roadmap": current_tasks,
            "chatHistory": chat_history,
            "weakAreas": fresh_weak_areas,
            "reflection": fresh_reflection
        }

    except Exception as e:
        print(f"Error in chat_with_roadmap: {e}")
        raise e
