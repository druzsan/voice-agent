from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_status_describes_the_setup(client: TestClient) -> None:
    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json() == {
        "database": "ok",
        "llm": {"provider": "echo", "model": None, "configured": True},
        "stt": {"model": "small.en", "max_recording_s": 5},
        "tts": {"model": "en_US-lessac-medium"},
    }
