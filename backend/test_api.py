# pyrefly: ignore [missing-import]
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_generate_roadmap():
    response = client.post("/generate-roadmap", json={"goal": "Backend interviews in 60 days"})
    assert response.status_code == 200
    print("Response JSON:", response.json())
    assert "roadmap" in response.json()

if __name__ == "__main__":
    test_generate_roadmap()
    print("Test passed successfully!")
