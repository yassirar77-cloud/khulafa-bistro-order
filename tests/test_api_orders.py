# tests/test_api_orders.py
"""
P0 PRIORITY — Core revenue path. Every order creation/cancellation/payment.
Tests the FastAPI endpoints with mocked Telegram and database isolation.
"""
import pytest
import time
import sys
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# Counter to ensure unique order numbers across tests
_order_counter = 0


def _make_unique_order_number():
    """Generate a unique order number to avoid UNIQUE constraint failures."""
    global _order_counter
    _order_counter += 1
    from datetime import datetime
    return f"KB{datetime.now().strftime('%Y%m%d%H%M%S')}{_order_counter:04d}"


@pytest.fixture(scope="module")
def client():
    """TestClient with mocked startup (no Telegram bot thread)."""
    # Init DB first, before importing main
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

    # Patch Thread so the Telegram bot never starts
    with patch("main.Thread") as mock_thread, \
         patch("main.requests") as mock_req:
        mock_thread.return_value.start.return_value = None
        mock_req.post.return_value = MagicMock(text='{"ok": true}', json=lambda: {"ok": True})

        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def _create_order(client, menu_item_id=1, quantity=1):
    """Helper: create an order and return response JSON."""
    payload = {
        "customer_telegram_id": "test_user_123",
        "customer_name": "Test User",
        "customer_phone": "0123456789",
        "order_type": "dine_in",
        "items": [{"menu_item_id": menu_item_id, "quantity": quantity}]
    }
    with patch("main.requests") as mock_req:
        mock_req.post.return_value = MagicMock(text='{"ok": true}')
        response = client.post("/api/orders", json=payload)
    return response


# ============================================================
# GET /api/ — Health check
# ============================================================


class TestHealthCheck:

    def test_api_root(self, client):
        response = client.get("/api/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data


# ============================================================
# GET /api/menu
# ============================================================


class TestMenuEndpoint:

    def test_get_menu_returns_200(self, client):
        response = client.get("/api/menu")
        assert response.status_code == 200

    def test_menu_has_categories(self, client):
        response = client.get("/api/menu")
        data = response.json()
        assert "menu" in data
        menu = data["menu"]
        assert len(menu) > 0

    def test_menu_items_have_required_fields(self, client):
        response = client.get("/api/menu")
        data = response.json()
        for category, items in data["menu"].items():
            for item in items:
                assert "id" in item
                assert "name" in item
                assert "price" in item

    def test_menu_prices_positive(self, client):
        response = client.get("/api/menu")
        for category, items in response.json()["menu"].items():
            for item in items:
                assert item["price"] > 0


# ============================================================
# POST /api/orders — Create order
# ============================================================


class TestCreateOrder:

    def test_create_order_success(self, client):
        resp = _create_order(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "order_id" in data
        assert "order_number" in data
        assert data["total_price"] > 0

    def test_create_order_invalid_menu_item(self, client):
        resp = _create_order(client, menu_item_id=99999)
        assert resp.status_code == 404

    def test_create_order_missing_fields(self, client):
        payload = {"items": [{"menu_item_id": 1, "quantity": 1}]}
        response = client.post("/api/orders", json=payload)
        assert response.status_code == 422

    def test_create_order_multiple_items(self, client):
        time.sleep(1)  # Ensure unique order number (second-level granularity)
        payload = {
            "customer_telegram_id": "12345",
            "customer_name": "Test User",
            "customer_phone": "0123456789",
            "order_type": "pickup",
            "items": [
                {"menu_item_id": 1, "quantity": 2},
                {"menu_item_id": 2, "quantity": 1},
            ]
        }
        with patch("main.requests") as mock_req:
            mock_req.post.return_value = MagicMock(text='{"ok": true}')
            response = client.post("/api/orders", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["total_price"] > 0


# ============================================================
# GET /api/orders/{order_id}
# ============================================================


class TestGetOrder:

    def test_get_existing_order(self, client):
        time.sleep(1)
        resp = _create_order(client)
        assert resp.status_code == 200, f"Failed to create order: {resp.text}"
        order_id = resp.json()["order_id"]

        response = client.get(f"/api/orders/{order_id}")
        assert response.status_code == 200
        data = response.json()
        assert "order" in data
        assert "items" in data
        assert data["order"]["status"] == "pending"

    def test_get_nonexistent_order(self, client):
        response = client.get("/api/orders/999999")
        assert response.status_code == 404


# ============================================================
# POST /api/orders/{order_id}/cancel
# ============================================================


class TestCancelOrder:

    def test_cancel_order_success(self, client):
        time.sleep(1)
        resp = _create_order(client)
        assert resp.status_code == 200
        order_id = resp.json()["order_id"]

        with patch("main.send_message") as mock_send:
            response = client.post(f"/api/orders/{order_id}/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_cancel_nonexistent_order(self, client):
        response = client.post("/api/orders/999999/cancel")
        assert response.status_code == 404

    def test_cancel_voice_qr_order_skips_customer_notification(self, client):
        """Bug 2 (Apr 2026): voice/QR walk-in orders carry the sentinel
        customer_telegram_id='voice_qr'. Cancelling one must not crash on
        the [400] 'chat not found' path, and must NOT send a customer
        message (the sentinel is not a Telegram chat)."""
        time.sleep(1)
        payload = {
            "customer_telegram_id": "voice_qr",   # anonymous walk-in
            "customer_name": "Table T01",
            "customer_phone": "",
            "order_type": "dine_in",
            "items": [{"menu_item_id": 1, "quantity": 1}],
        }
        with patch("main.requests") as mock_req:
            mock_req.post.return_value = MagicMock(text='{"ok": true}')
            resp = client.post("/api/orders", json=payload)
        assert resp.status_code == 200
        order_id = resp.json()["order_id"]

        with patch("main.send_message") as mock_send:
            response = client.post(f"/api/orders/{order_id}/cancel")

        # Endpoint succeeds — no crash
        assert response.status_code == 200
        assert response.json()["success"] is True
        # Anonymous customer is skipped — send_message must NOT be called
        mock_send.assert_not_called()

    def test_cancel_normal_order_still_notifies_customer(self, client):
        """Guard against over-broad skip: real telegram customers
        still receive their cancel notification."""
        time.sleep(1)
        resp = _create_order(client)
        assert resp.status_code == 200
        order_id = resp.json()["order_id"]

        with patch("main.send_message") as mock_send:
            response = client.post(f"/api/orders/{order_id}/cancel")

        assert response.status_code == 200
        # Real customer id → send_message IS called
        mock_send.assert_called_once()


# ============================================================
# POST /api/orders/{order_id}/confirm_payment
# ============================================================


class TestConfirmPayment:

    def test_confirm_payment_success(self, client):
        time.sleep(1)
        resp = _create_order(client)
        assert resp.status_code == 200
        order_id = resp.json()["order_id"]

        response = client.post(f"/api/orders/{order_id}/confirm_payment")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


# ============================================================
# POST /api/orders/{order_id}/status
# ============================================================


class TestUpdateOrderStatus:

    def test_update_status(self, client):
        time.sleep(1)
        resp = _create_order(client)
        assert resp.status_code == 200
        order_id = resp.json()["order_id"]

        with patch("main.send_customer_notification"):
            response = client.post(
                f"/api/orders/{order_id}/status",
                json={"status": "preparing"}
            )
        assert response.status_code == 200
        assert response.json()["success"] is True


# ============================================================
# GET /api/settings/{key}
# ============================================================


class TestSettings:

    def test_get_existing_setting(self, client):
        response = client.get("/api/settings/restaurant_name")
        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "restaurant_name"

    def test_get_nonexistent_setting(self, client):
        response = client.get("/api/settings/nonexistent_key_xyz")
        assert response.status_code == 404
