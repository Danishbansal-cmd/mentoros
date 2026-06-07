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
        chat_msg = "What is a container image?"
        chat_response = client.post(
            f"/roadmaps/{roadmap_id}/chat",
            json={"message": chat_msg},
            headers=headers
        )
        assert chat_response.status_code == 200, f"Chat endpoint failed: {chat_response.text}"
        chat_data = chat_response.json()
        
        assert "response" in chat_data
        assert "roadmap" in chat_data
        assert "chatHistory" in chat_data
        
        # Verify message count increased in history (user message + AI response = 4 total)
        assert len(chat_data["chatHistory"]) == 4
        assert chat_data["chatHistory"][-2]["content"] == chat_msg
        assert chat_data["chatHistory"][-1]["role"] == "model"
        print("Chat response verified successfully")
        print("AI Response:", chat_data["response"])

        # 6. Send message asking to edit the roadmap
        edit_msg = "Please add a weekend milestone to practice Docker Compose."
        edit_response = client.post(
            f"/roadmaps/{roadmap_id}/chat",
            json={"message": edit_msg},
            headers=headers
        )
        assert edit_response.status_code == 200, f"Edit roadmap chat failed: {edit_response.text}"
        edit_data = edit_response.json()
        
        assert len(edit_data["chatHistory"]) == 6
        print("Edit request response received")
        print("Updated Tasks count:", len(edit_data["roadmap"]))

        # 7. Update status and notes of a task using its ID
        first_task = edit_data["roadmap"][0]
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
