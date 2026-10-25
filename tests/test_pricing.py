import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.pricing import compute_total

client = TestClient(app)


def test_no_discount():
    assert compute_total(10.0, 3) == 30.0


def test_discount_applied():
    assert compute_total(10.0, 3, 0.15) == 25.5


def test_discount_is_capped():
    assert compute_total(100.0, 1, 0.9) == 50.0


def test_rounding_to_cents():
    assert compute_total(0.333, 3, 0.0) == 1.0


def test_rejects_bad_qty():
    with pytest.raises(ValueError):
        compute_total(10.0, 0)


def test_rejects_bad_discount():
    with pytest.raises(ValueError):
        compute_total(10.0, 1, 1.5)


def test_health_endpoint():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_price_endpoint():
    r = client.post("/price", json={"unit_price": 10, "qty": 3, "discount": 0.15})
    assert r.status_code == 200
    assert r.json() == {"total": 25.5}


def test_price_endpoint_validation_error():
    r = client.post("/price", json={"unit_price": 10, "qty": 0})
    assert r.status_code == 422
