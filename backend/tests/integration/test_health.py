"""Integration tests: application health check.

This was the scaffold's only fully implemented integration test,
checking that the FastAPI application starts correctly.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, base_url="http://localhost")


def test_health_check():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
