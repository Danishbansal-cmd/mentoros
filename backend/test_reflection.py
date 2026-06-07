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

def test_reflection_and_memory():
    # 1. Register a test user
    test_username = "reflection_tester_888"
    test_password = "test_password_123"
    
    # Cleanup previous run if any
    users_collection.delete_many({"username": test_username})
    
    reg_response = client.post("/auth/register", json={"username": test_username, "password": test_password})
    assert reg_response.status_code == 201, f"Failed to register: {reg_response.text}"
    user_id = reg_response.json()["id"]
    print(f"Registered test user: {test_username}")
    
    # 2. Login
    login_response = client.post("/auth/login", json={"username": test_username, "password": test_password})
    assert login_response.status_code == 200, f"Failed to login: {login_response.text}"
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        # 3. Generate a roadmap
        goal = "Learn Docker containerization and orchestration"
        print(f"Generating roadmap for: {goal}")
        gen_response = client.post("/generate-roadmap", json={"goal": goal}, headers=headers)
        assert gen_response.status_code == 200, f"Failed to generate roadmap: {gen_response.text}"
        print("Roadmap generated successfully.")

        # Get roadmap ID
        list_response = client.get("/roadmaps", headers=headers)
        assert list_response.status_code == 200
        roadmaps = list_response.json()
        assert len(roadmaps) == 1
        roadmap_id = roadmaps[0]["id"]

        # Verify initial weakAreas & reflection are empty or initialized
        assert "weakAreas" in roadmaps[0]
        assert "reflection" in roadmaps[0]
        print("Initial verification passed: weakAreas and reflection lists exist.")

        # 4. Send a message indicating struggles with Docker Volumes
        chat_msg = "I am having a lot of trouble understanding Docker Volumes. How do they map folders from host to container? I've tried multiple times and keep getting confused."
        print(f"\nUser: {chat_msg}")
        chat_response = client.post(
            f"/roadmaps/{roadmap_id}/chat",
            json={"message": chat_msg},
            headers=headers
        )
        assert chat_response.status_code == 200, f"Chat failed: {chat_response.text}"
        chat_data = chat_response.json()
        
        print("\nAI Response (first snippet):", chat_data["response"][:200] + "...")
        print("\nChecking updated cognitive profile...")
        print("Weak Areas:", chat_data.get("weakAreas"))
        print("Reflections:", chat_data.get("reflection"))

        assert len(chat_data.get("weakAreas", [])) > 0, "AI reflection failed to identify any weak areas!"
        assert len(chat_data.get("reflection", [])) > 0, "AI reflection failed to write reflection logs!"

        print("\nFirst reflection round verified successfully.")

        # 5. Send second message indicating struggle with Docker Network to test incremental counts/additions
        chat_msg_2 = "Can we talk about Docker Network? I don't understand how container networking works, I find it extremely hard."
        print(f"\nUser: {chat_msg_2}")
        chat_response_2 = client.post(
            f"/roadmaps/{roadmap_id}/chat",
            json={"message": chat_msg_2},
            headers=headers
        )
        assert chat_response_2.status_code == 200
        chat_data_2 = chat_response_2.json()

        print("\nWeak Areas Round 2:", chat_data_2.get("weakAreas"))
        print("Reflections Round 2:", chat_data_2.get("reflection"))

        assert len(chat_data_2.get("weakAreas", [])) >= 1
        assert len(chat_data_2.get("reflection", [])) == 2, "Reflection count did not increment to 2!"

        print("\nSecond reflection round verified successfully.")

    finally:
        # Cleanup DB after test
        users_collection.delete_many({"username": test_username})
        roadmaps_collection.delete_many({"userId": user_id})
        print("Database cleaned up successfully.")

if __name__ == "__main__":
    test_reflection_and_memory()
