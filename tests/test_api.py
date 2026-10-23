from fastapi.testclient import TestClient

from raceproof.api import app


def test_api_lists_generic_target_metadata() -> None:
    response = TestClient(app).get("/api/targets")
    assert response.status_code == 200
    targets = response.json()
    assert {target["id"] for target in targets} == {
        "inventory_oversell",
        "booking_double_reservation",
    }
    assert all(target["actors"] == ["A", "B"] for target in targets)


def test_api_rejects_unknown_target_without_starting_run() -> None:
    response = TestClient(app).post("/api/runs", json={"target_id": "not_registered"})
    assert response.status_code == 422
    assert "unknown target" in response.json()["detail"]
