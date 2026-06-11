import os
import sys
import subprocess
import json
import asyncio
from datetime import datetime
from typing import List, Dict, Any
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field
# pyrefly: ignore [missing-import]
from bson import ObjectId
# pyrefly: ignore [missing-import]
from google import genai
# pyrefly: ignore [missing-import]
from google.genai import types
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# pyrefly: ignore [missing-import]
from mcp.server.fastmcp import FastMCP

load_dotenv()

from app.database import db, roadmaps_collection
from app.services.roadmap import search_learning_resources

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "chat_workspace"))

# 1. Initialize FastMCP Server natively in Python
mcp_server = FastMCP("MentorOS AI Mentor Database Agent")

class MilestoneItem(BaseModel):
    title: str = Field(description="The short title of the learning milestone/topic, e.g. 'Intro to SQL'")
    description: str = Field(description="Detailed explanation of what the user will learn and build")
    estimatedHours: int = Field(description="Estimated hours required to complete this milestone, e.g. 5")
    difficulty: str = Field(description="Difficulty level. Must be one of: 'beginner', 'intermediate', 'advanced'")
    prerequisites: List[str] = Field(default_factory=list, description="Titles of milestones that should be completed prior to starting this one")
    resources: List[str] = Field(default_factory=list, description="Titles, links, or references of learning resources")
    projects: List[str] = Field(default_factory=list, description="List of mini-projects or hands-on practice items")

def safe_path(base_dir: str, filename: str) -> str:
    abs_base = os.path.abspath(base_dir)
    abs_target = os.path.abspath(os.path.join(base_dir, filename))
    if not abs_target.startswith(abs_base):
        raise ValueError("Directory traversal check failed")
    return abs_target

def add_chat_agent_log(roadmap_id: str, message: str, log_type: str = "info"):
    """
    Append log message to the active running log record for this roadmap.
    """
    db["chat_agent_runs"].update_one(
        {"roadmapId": roadmap_id, "status": "running"},
        {
            "$push": {
                "logs": {
                    "timestamp": datetime.utcnow().isoformat(),
                    "message": message,
                    "type": log_type
                }
            },
            "$set": {
                "updatedAt": datetime.utcnow()
            }
        }
    )

# ---------------------------------------------------------
# Define FastMCP Tools (Natively Decorated in Python)
# ---------------------------------------------------------

@mcp_server.tool()
async def search_resources_mcp(query: str) -> str:
    """
    Queries MongoDB learning resources for verified links matching a topic. Exposes database search via Model Context Protocol.
    """
    try:
        # Load keys & initialize client internally
        api_key = os.getenv("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)
        
        results = search_learning_resources(client, query, limit=2)
        formatted = []
        for r in results:
            formatted.append({
                "title": r.get("title"),
                "description": r.get("description"),
                "url": r.get("url"),
                "category": r.get("category")
            })
        return json.dumps(formatted)
    except Exception as e:
        return json.dumps({"error": f"Search failed: {str(e)}"})

@mcp_server.tool()
async def modify_roadmap_milestones_mcp(roadmap_id: str, updated_roadmap: List[MilestoneItem]) -> str:
    """
    Modifies or updates the roadmap milestone steps in the database.
    
    IMPORTANT: You must pass the COMPLETE list of all milestone items representing the new state of the roadmap. 
    You MUST include all existing milestones that you want to keep, in addition to any new, updated, or reordered milestones. 
    Any milestone omitted from `updated_roadmap` will be permanently deleted from the database.
    """
    try:
        roadmap_obj_id = ObjectId(roadmap_id)
        roadmap_doc = roadmaps_collection.find_one({"_id": roadmap_obj_id})
        if not roadmap_doc:
            return "Error: Roadmap document not found."
            
        current_tasks = roadmap_doc.get("roadmap", [])
        roadmap_dicts = [item.model_dump() for item in updated_roadmap]
        
        # Preserve old notes, statuses, and quiz IDs
        old_tasks_map = {str(t.get("title")).strip().lower(): t for t in current_tasks}

        api_key = os.getenv("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)

        final_tasks = []
        for t in roadmap_dicts:
            title_key = str(t.get("title")).strip().lower()
            old_task = old_tasks_map.get(title_key)
            
            if old_task:
                t["_id"] = old_task.get("_id", str(ObjectId()))
                t["status"] = old_task.get("status", "pending")
                t["notes"] = old_task.get("notes", "")
                t["quizIds"] = old_task.get("quizIds", [])
                # Preserve existing resources without making any API calls
                t["resources"] = old_task.get("resources", [])
            else:
                t["_id"] = str(ObjectId())
                t["status"] = "pending"
                t["notes"] = ""
                t["quizIds"] = []
                
                # Query verified resources using vector search only for new milestones
                topic_query = f"{t.get('title', '')} {t.get('description', '')}"
                try:
                    real_resources = search_learning_resources(client, topic_query, limit=2)
                    real_links = [res["url"] for res in real_resources if "url" in res]
                    t["resources"] = list(set(real_links + t.get("resources", [])))
                except Exception as e:
                    print(f"Error fetching resources for new milestone: {e}")
                    t["resources"] = t.get("resources", [])
            
            final_tasks.append(t)

        completed_count = sum(1 for t in final_tasks if t.get("status") == "completed")
        
        roadmaps_collection.update_one(
            {"_id": roadmap_obj_id},
            {
                "$set": {
                    "roadmap": final_tasks,
                    "progress.completed": completed_count,
                    "progress.total": len(final_tasks),
                    "updatedAt": datetime.utcnow()
                }
            }
        )
        return "Success: Roadmap milestones successfully updated in database."
    except Exception as e:
        return f"Error updating milestones: {str(e)}"

@mcp_server.tool()
async def execute_code_sandbox_mcp(roadmap_id: str, code: str) -> str:
    """
    Writes and executes python code in a temporary workspace directory to test syntax or run calculations.
    """
    try:
        sandbox_dir = os.path.join(WORKSPACE_ROOT, roadmap_id)
        os.makedirs(sandbox_dir, exist_ok=True)
        
        filename = "scratch_script.py"
        target_path = safe_path(sandbox_dir, filename)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(code)
            
        res = subprocess.run(
            ["python3", target_path],
            capture_output=True,
            text=True,
            cwd=sandbox_dir,
            timeout=10
        )
        
        if os.path.exists(target_path):
            os.remove(target_path)
            
        return f"Exit Code: {res.returncode}\n\nSTDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}"
    except subprocess.TimeoutExpired:
        return "Error: Code execution timed out (limit: 10s)."
    except Exception as e:
        return f"Error executing code: {str(e)}"

# ---------------------------------------------------------
# Agent Execution Loop
# ---------------------------------------------------------

async def run_chat_agent_background(roadmap_id: str, user_id: str, user_message: str):
    """
    Background runner for AI Mentor chat queries.
    Executes ReAct loops using native Python FastMCP server tools.
    """
    try:
        roadmap_obj_id = ObjectId(roadmap_id)
    except Exception:
        print(f"Invalid roadmap ID format in chat agent: {roadmap_id}", file=sys.stderr)
        return

    # Check key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        add_chat_agent_log(roadmap_id, "Error: GEMINI_API_KEY is not defined in backend env. Halting agent.", "error")
        db["chat_agent_runs"].update_one({"roadmapId": roadmap_id, "status": "running"}, {"$set": {"status": "failed"}})
        roadmaps_collection.update_one({"_id": roadmap_obj_id}, {"$set": {"status": "idle"}})
        return

    # Fetch roadmap document
    roadmap_doc = roadmaps_collection.find_one({"_id": roadmap_obj_id, "userId": user_id})
    if not roadmap_doc:
        print(f"Roadmap not found or unauthorized: {roadmap_id}", file=sys.stderr)
        return

    current_tasks = roadmap_doc.get("roadmap", [])
    chat_history = roadmap_doc.get("chatHistory", [])
    goal = roadmap_doc.get("goal", "")
    weak_areas = roadmap_doc.get("weakAreas", [])
    reflection_logs = roadmap_doc.get("reflection", [])

    client = genai.Client(api_key=api_key)

    try:
        add_chat_agent_log(roadmap_id, "Initializing Gemini reasoning session with FastMCP tools...", "info")
        
        formatted_history = ""
        for msg in chat_history[:-1]:
            role_name = "User" if msg["role"] == "user" else "AI Mentor"
            formatted_history += f"{role_name}: {msg['content']}\n\n"

        memory_context = ""
        if weak_areas:
            memory_context += "\nAI REFLECTION MEMORY: User struggles with:\n"
            for wa in weak_areas:
                memory_context += f"- {wa['topic']} (struggled {wa['count']} times)\n"
        if reflection_logs:
            memory_context += "\nPast reflections:\n"
            for ref in reflection_logs[-2:]:
                memory_context += f"- {ref['summary']}\n"

        system_instruction = f"""
You are the AI Learning Mentor inside MentorOS.
The user is viewing their personalized roadmap for the goal: "{goal}".
The current roadmap tasks are:
{json.dumps(current_tasks, indent=2)}

Your roadmap ID is: "{roadmap_id}". Pass this ID exactly to any tools that require a roadmap_id argument.

You are having an ongoing chat conversation with the user.
Here is the conversation history:
{formatted_history}
{memory_context}

The user just sent this message: "{user_message}"

You must respond as the AI Mentor.
Work step-by-step:
1. Reason: Decide if you need to fetch resources, test code, or modify their roadmap milestones.
2. Act: Call the relevant tools. Pass your roadmap ID if required.
3. Observe: Review the tool results.
4. Finalize: When you are done, output your final conversational response. You MUST start it with 'FINAL ANSWER: <your text response>'. Keep it friendly, clear, and encouraging.

CRITICAL INSTRUCTIONS FOR TOOL USAGE:
- If the user asks to add, remove, update, or reorganize milestones, you MUST call the modify_roadmap_milestones_mcp tool. You are forbidden from describing the modifications in your FINAL ANSWER without first executing the modify_roadmap_milestones_mcp tool.
- When calling modify_roadmap_milestones_mcp, you MUST pass the COMPLETE list of all milestones (all existing ones you want to keep, plus any new or edited ones). Do NOT just pass the new or edited milestones, otherwise the existing ones will be permanently deleted.
- If the user asks you to run, test, or verify python code, you MUST call the execute_code_sandbox_mcp tool, wait for its observation, and then report the results in your FINAL ANSWER.

Available FastMCP Tools:
- search_resources_mcp(query: str): To get verified links from the database to suggest.
- modify_roadmap_milestones_mcp(roadmap_id: str, updated_roadmap: List[MilestoneItem]): If they ask to add, remove, change, update, or reorganize milestones. IMPORTANT: You must pass the complete list of all milestones (existing + new/modified). Any omitted milestones will be deleted.
- execute_code_sandbox_mcp(roadmap_id: str, code: str): To test python script syntax or perform calculations.
"""

        # Map native Python MCP tools directly to Gemini AsyncClient with fallback models
        models_to_try = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash-lite", "gemini-2.5-pro"]
        
        # Map tools for dynamic call dispatching in ReAct loop
        tool_lookup = {
            "search_resources_mcp": search_resources_mcp,
            "modify_roadmap_milestones_mcp": modify_roadmap_milestones_mcp,
            "execute_code_sandbox_mcp": execute_code_sandbox_mcp
        }

        success = False
        last_error = None

        for model_name in models_to_try:
            try:
                add_chat_agent_log(roadmap_id, f"Initializing session with model: {model_name}...", "info")
                chat_session = client.aio.chats.create(
                    model=model_name,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        tools=[search_resources_mcp, modify_roadmap_milestones_mcp, execute_code_sandbox_mcp],
                        temperature=0.2
                    )
                )

                current_prompt = f"User Query: {user_message}"
                max_steps = 6
                final_answer = ""
                completed = False

                for step in range(max_steps):
                    add_chat_agent_log(roadmap_id, f"[{model_name}] Reasoning step {step + 1}/{max_steps}...", "info")
                    
                    # Send message with retry handling for transient API issues
                    response = None
                    max_attempts = 3
                    for attempt in range(max_attempts):
                        try:
                            response = await chat_session.send_message(current_prompt)
                            break
                        except Exception as send_err:
                            err_str = str(send_err)
                            is_quota_exhausted = "RESOURCE_EXHAUSTED" in err_str or "daily" in err_str or "limit: 20" in err_str or "limit: 15" in err_str
                            if is_quota_exhausted:
                                raise send_err
                                
                            if attempt < max_attempts - 1 and ("503" in err_str or "429" in err_str or "UNAVAILABLE" in err_str):
                                sleep_seconds = 2 ** attempt
                                add_chat_agent_log(roadmap_id, f"Transient error. Retrying in {sleep_seconds}s...", "warning")
                                await asyncio.sleep(sleep_seconds)
                            else:
                                raise send_err
                    
                    if response.function_calls:
                        for call in response.function_calls:
                            tool_name = call.name
                            tool_args = call.args
                            
                            if response.text:
                                add_chat_agent_log(roadmap_id, response.text, "thought")
                                
                            add_chat_agent_log(roadmap_id, f"Executing FastMCP tool call: {tool_name}", "tool_call")
                            
                            tool_func = tool_lookup.get(tool_name)
                            if tool_func:
                                try:
                                    result = await tool_func(**tool_args)
                                except Exception as e:
                                    result = f"Exception executing tool: {str(e)}"
                            else:
                                result = f"Error: Tool {tool_name} not found."
                                
                            add_chat_agent_log(roadmap_id, f"FastMCP Tool observation: {str(result)[:400]}...", "tool_response")
                            
                            current_prompt = types.Part.from_function_response(
                                name=tool_name,
                                response={"result": result}
                            )
                    else:
                        text_out = response.text or ""
                        add_chat_agent_log(roadmap_id, text_out, "thought")
                        
                        if "FINAL ANSWER:" in text_out:
                            completed = True
                            final_answer = text_out.split("FINAL ANSWER:")[-1].strip()
                            break
                            
                        current_prompt = "Please proceed to finalize your thoughts and write the response starting with 'FINAL ANSWER:'."

                if completed and final_answer:
                    # Update chat history in MongoDB
                    new_model_msg = {
                        "role": "model",
                        "content": final_answer,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    roadmaps_collection.update_one(
                        {"_id": roadmap_obj_id},
                        {
                            "$push": {"chatHistory": new_model_msg},
                            "$set": {"updatedAt": datetime.utcnow()}
                        }
                    )
                    
                    # Run offline chat reflection for cognitive profile logs
                    fresh_doc = roadmaps_collection.find_one({"_id": roadmap_obj_id})
                    from app.services.roadmap import reflect_on_chat
                    reflect_on_chat(client, roadmap_id, user_id, fresh_doc.get("chatHistory", []))
                    
                    db["chat_agent_runs"].update_one(
                        {"roadmapId": roadmap_id, "status": "running"},
                        {
                            "$set": {
                                "status": "completed",
                                "summary": final_answer,
                                "updatedAt": datetime.utcnow()
                            }
                        }
                    )
                    success = True
                    break
                else:
                    raise Exception("Agent did not reach FINAL ANSWER.")

            except Exception as model_err:
                last_error = model_err
                add_chat_agent_log(roadmap_id, f"Model {model_name} run failed: {str(model_err)}. Falling back to next model...", "warning")

        if not success:
            raise last_error if last_error else Exception("All models failed to generate response.")
    except Exception as e:
        print(f"Exception executing async FastMCP agent: {e}", file=sys.stderr)
        add_chat_agent_log(roadmap_id, f"Fatal FastMCP client loop error: {str(e)}", "error")
        db["chat_agent_runs"].update_one(
            {"roadmapId": roadmap_id, "status": "running"},
            {"$set": {"status": "failed", "updatedAt": datetime.utcnow()}}
        )
    finally:
        # Release roadmap lock
        roadmaps_collection.update_one({"_id": roadmap_obj_id}, {"$set": {"status": "idle"}})

def clear_workspace(roadmap_id: str):
    sandbox_dir = os.path.join(WORKSPACE_ROOT, roadmap_id)
    if os.path.exists(sandbox_dir):
        import shutil
        shutil.rmtree(sandbox_dir)
