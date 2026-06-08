import os
import sys
# pyrefly: ignore [missing-import]
from fastapi.testclient import TestClient
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Load env before importing other modules
load_dotenv()

from main import app
# pyrefly: ignore [missing-import]
from app.database import users_collection, roadmaps_collection

client = TestClient(app)

def test_chat_under_roadmap_flow():
    # 1. Register a test user
    test_username = "temp_chat_tester_999"
    test_password = "test_password_123"
    
    # Cleanup previous run if any
    users_collection.delete_many({"username": test_username})
    
    reg_response = client.post("/auth/register", json={"username": test_username, "password": test_password})
    assert reg_response.status_code == 201, f"Failed to register: {reg_response.text}"
    user_id = reg_response.json()["id"]
    print("Registered test user:", test_username)
    
    # 2. Login to get Bearer token
    login_response = client.post("/auth/login", json={"username": test_username, "password": test_password})
    assert login_response.status_code == 200, f"Failed to login: {login_response.text}"
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("Log in successful, token acquired")

    try:
        # 3. Generate a roadmap
        goal = "Learn Docker in 7 days"
        gen_response = client.post("/generate-roadmap", json={"goal": goal}, headers=headers)
        assert gen_response.status_code == 200, f"Failed to generate roadmap: {gen_response.text}"
        
        roadmap_tasks = gen_response.json()["roadmap"]
        assert len(roadmap_tasks) > 0
        print("Generated initial roadmap successfully")

        # 4. Get roadmaps list and verify chat history is initialized
        list_response = client.get("/roadmaps", headers=headers)
        assert list_response.status_code == 200, f"Failed to list roadmaps: {list_response.text}"
        user_roadmaps = list_response.json()
        assert len(user_roadmaps) == 1
        
        roadmap = user_roadmaps[0]
        roadmap_id = roadmap["id"]
        assert "chatHistory" in roadmap
        assert len(roadmap["chatHistory"]) == 2
        assert roadmap["chatHistory"][0]["role"] == "user"
        assert roadmap["chatHistory"][1]["role"] == "model"
        print("Initial chat history successfully verified in /roadmaps list")

        # 5. Send message asking a question
        chat_msg = "What is a container image? Keep your answer short."
        chat_response = client.post(
            f"/roadmaps/{roadmap_id}/chat",
            json={"message": chat_msg},
            headers=headers
        )
        assert chat_response.status_code == 200, f"Chat endpoint failed: {chat_response.text}"
        chat_data = chat_response.json()
        assert chat_data["success"] is True
        assert chat_data["status"] == "agent_running"
        
        # Poll chat agent status
        import time
        print("Polling chat agent status...")
        agent_completed = False
        printed_logs = set()
        for _ in range(60): # timeout after 60 seconds
            status_response = client.get(f"/roadmaps/{roadmap_id}/chat-status", headers=headers)
            assert status_response.status_code == 200
            status_data = status_response.json()
            run = status_data.get("run")
            if run:
                for log in run.get("logs", []):
                    log_key = (log.get("timestamp"), log.get("message"))
                    if log_key not in printed_logs:
                        print(f"[{log.get('type')}] {log.get('message')}")
                        printed_logs.add(log_key)
                
                if run.get("status") in ["completed", "failed"]:
                    agent_completed = True
                    print(f"Agent finished with status: {run.get('status')}")
                    if run.get("status") == "completed":
                        print("AI Summary:", run.get("summary"))
                    break
            time.sleep(1)
            
        assert agent_completed, "Agent did not finish in time"
        
        # Verify chat history updated in DB
        list_response = client.get("/roadmaps", headers=headers)
        roadmap = list_response.json()[0]
        assert len(roadmap["chatHistory"]) == 4
        assert roadmap["chatHistory"][-2]["content"] == chat_msg
        assert roadmap["chatHistory"][-1]["role"] == "model"
        print("Chat query verified successfully")

        # 6. Send message asking to edit the roadmap
        edit_msg = "Please add a weekend milestone to practice Docker Compose after milestone 1, and verify it with a simple print('Compose OK') python execution in the sandbox."
        edit_response = client.post(
            f"/roadmaps/{roadmap_id}/chat",
            json={"message": edit_msg},
            headers=headers
        )
        assert edit_response.status_code == 200, f"Edit roadmap chat failed: {edit_response.text}"
        edit_data = edit_response.json()
        assert edit_data["success"] is True
        
        print("Polling agent edit status...")
        agent_completed = False
        printed_logs = set()
        for _ in range(90): # timeout after 90 seconds
            status_response = client.get(f"/roadmaps/{roadmap_id}/chat-status", headers=headers)
            assert status_response.status_code == 200
            status_data = status_response.json()
            run = status_data.get("run")
            if run:
                for log in run.get("logs", []):
                    log_key = (log.get("timestamp"), log.get("message"))
                    if log_key not in printed_logs:
                        print(f"[{log.get('type')}] {log.get('message')}")
                        printed_logs.add(log_key)
                
                if run.get("status") in ["completed", "failed"]:
                    agent_completed = True
                    print(f"Agent finished with status: {run.get('status')}")
                    if run.get("status") == "completed":
                        print("AI Summary:", run.get("summary"))
                    break
            time.sleep(1)
            
        assert agent_completed, "Agent did not finish in time for editing"
        
        # Verify tasks count increased
        list_response = client.get("/roadmaps", headers=headers)
        roadmap = list_response.json()[0]
        assert len(roadmap["roadmap"]) > len(roadmap_tasks)
        print("Edit request response received")
        print("Updated Tasks count:", len(roadmap["roadmap"]))

        # 7. Update status and notes of a task using its ID
        first_task = roadmap["roadmap"][0]
        task_id = first_task["_id"]
        
        patch_response = client.patch(
            f"/roadmaps/{roadmap_id}/tasks/{task_id}",
            json={"status": "completed", "notes": "Completed learning first milestone!"},
            headers=headers
        )
        assert patch_response.status_code == 200, f"PATCH task details failed: {patch_response.text}"
        patch_data = patch_response.json()
        assert patch_data["status"] == "completed"
        assert patch_data["notes"] == "Completed learning first milestone!"
        assert patch_data["progress"]["completed"] == 1
        print("PATCH task details (status and notes) verified successfully")
        
    finally:
        # Cleanup DB after test
        users_collection.delete_many({"username": test_username})
        roadmaps_collection.delete_many({"userId": user_id})
        print("Database cleaned up successfully.")

if __name__ == "__main__":
    test_chat_under_roadmap_flow()
