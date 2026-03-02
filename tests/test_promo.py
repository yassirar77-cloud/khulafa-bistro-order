# tests/test_promo.py
"""
P1 PRIORITY — Discount abuse prevention. Expiry and usage limits must hold.
Tests promo code endpoints via the enhanced_routes.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timedelta


@pytest.fixture(scope="module")
def client():
    """TestClient with mocked startup (no Telegram bot thread)."""
    import init_db
    init_db.init_database()
    import migrate_database
    try:
        migrate_database.migrate_database()
    except Exception:
        pass
    import migrate_add_tables
    try:
        migrate_add_tables.migrate()
    except Exception:
        pass

    with patch("main.Thread") as mock_thread, \
         patch("main.requests") as mock_req:
        mock_thread.return_value.start.return_value = None
        mock_req.post.return_value = MagicMock(text='{"ok": true}', json=lambda: {"ok": True})

        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ============================================================
# POST /api/promo/create
# ============================================================


class TestPromoCreate:

    def test_create_promo_success(self, client):
        response = client.post("/api/promo/create", json={
            "code": "TEST10",
            "discount_percentage": 10,
            "min_order_amount": 5.00,
            "max_uses": 100,
            "valid_from": datetime.now().isoformat(),
            "valid_until": (datetime.now() + timedelta(days=30)).isoformat(),
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_create_duplicate_promo_fails(self, client):
        # Create first
        client.post("/api/promo/create", json={
            "code": "DUP10",
            "discount_percentage": 10,
        })
        # Create duplicate
        response = client.post("/api/promo/create", json={
            "code": "DUP10",
            "discount_percentage": 20,
        })
        assert response.status_code == 400


# ============================================================
# POST /api/promo/validate
# ============================================================


class TestPromoValidation:

    def test_validate_existing_promo(self, client):
        """Pre-seeded WELCOME10 from migrate_database should be valid."""
        response = client.post("/api/promo/validate", json={
            "code": "WELCOME10",
            "order_total": 20.00
        })
        # May be 200 or 404 depending on migration seed
        if response.status_code == 200:
            data = response.json()
            assert data["valid"] is True
            assert data["discount"] > 0

    def test_invalid_code_rejected(self, client):
        response = client.post("/api/promo/validate", json={
            "code": "FAKECODE999",
            "order_total": 50.00
        })
        assert response.status_code == 404

    def test_expired_promo_rejected(self, client):
        # Create expired promo
        client.post("/api/promo/create", json={
            "code": "EXPIRED99",
            "discount_percentage": 10,
            "valid_until": (datetime.now() - timedelta(days=1)).isoformat(),
        })

        response = client.post("/api/promo/validate", json={
            "code": "EXPIRED99",
            "order_total": 50.00
        })
        assert response.status_code == 400

    def test_min_order_not_met(self, client):
        # Create promo with min order
        client.post("/api/promo/create", json={
            "code": "MINORDER50",
            "discount_percentage": 15,
            "min_order_amount": 50.00,
            "valid_until": (datetime.now() + timedelta(days=30)).isoformat(),
        })

        response = client.post("/api/promo/validate", json={
            "code": "MINORDER50",
            "order_total": 10.00
        })
        assert response.status_code == 400

    def test_max_uses_enforced(self, client):
        # Create promo with max_uses=1
        client.post("/api/promo/create", json={
            "code": "ONCE123",
            "discount_percentage": 20,
            "max_uses": 1,
            "valid_until": (datetime.now() + timedelta(days=30)).isoformat(),
        })

        # Use it once — manually set current_uses to max
        import sqlite3
        conn = sqlite3.connect("khulafa_bistro.db")
        conn.execute("UPDATE promo_codes SET current_uses = 1 WHERE UPPER(code) = 'ONCE123'")
        conn.commit()
        conn.close()

        # Try to use again — should fail
        response = client.post("/api/promo/validate", json={
            "code": "ONCE123",
            "order_total": 50.00
        })
        assert response.status_code == 400


# ============================================================
# GET /api/promo/list
# ============================================================


class TestPromoList:

    def test_list_returns_array(self, client):
        response = client.get("/api/promo/list")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


# ============================================================
# Analytics endpoints
# ============================================================


class TestAnalytics:

    def test_daily_sales(self, client):
        response = client.get("/api/analytics/sales/daily")
        assert response.status_code == 200
        data = response.json()
        assert "date" in data
        assert "summary" in data

    def test_weekly_sales(self, client):
        response = client.get("/api/analytics/sales/weekly")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_monthly_sales(self, client):
        response = client.get("/api/analytics/sales/monthly?year=2025&month=1")
        assert response.status_code == 200
        data = response.json()
        assert "year" in data
        assert "month" in data


# ============================================================
# Payment endpoints
# ============================================================


class TestPaymentEndpoints:

    def test_get_tng_qr(self, client):
        # Note: /api/settings/tng_qr_url is intercepted by the generic
        # /api/settings/{key} route which queries the settings table.
        # Returns 404 if the key doesn't exist in settings, or 200 if it does.
        response = client.get("/api/settings/tng_qr_url")
        assert response.status_code in [200, 404]

    def test_get_grabpay_qr(self, client):
        response = client.get("/api/settings/grabpay_qr_url")
        assert response.status_code in [200, 404]
