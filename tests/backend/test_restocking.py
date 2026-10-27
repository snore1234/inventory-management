"""
Tests for restocking API endpoints.
"""
import pytest


def _forecasts_by_sku(client):
    return {f["item_sku"]: f for f in client.get("/api/demand").json()}


class TestRestockingEndpoints:
    """Test suite for restock order endpoints."""

    def test_demand_forecasts_include_cost_and_lead_time(self, client):
        """Test that demand forecasts carry the fields restocking needs."""
        response = client.get("/api/demand")
        assert response.status_code == 200

        data = response.json()
        assert len(data) > 0

        for forecast in data:
            assert isinstance(forecast["unit_cost"], (int, float))
            assert forecast["unit_cost"] > 0
            assert isinstance(forecast["lead_time_days"], int)
            assert forecast["lead_time_days"] > 0

    def test_get_restock_orders(self, client):
        """Test getting submitted restock orders."""
        response = client.get("/api/restock-orders")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_restock_order(self, client):
        """Test submitting a restock order and reading it back."""
        forecasts = _forecasts_by_sku(client)
        sku = next(iter(forecasts))

        response = client.post("/api/restock-orders", json={"items": [{"sku": sku, "quantity": 10}]})
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert len(order["items"]) == 1
        assert order["items"][0]["sku"] == sku
        assert order["items"][0]["quantity"] == 10

        # Order should be retrievable, matched by id since the list is shared across tests
        listed = client.get("/api/restock-orders").json()
        assert any(o["id"] == order["id"] for o in listed)

    def test_restock_order_total_uses_server_prices(self, client):
        """Test that total value is computed from demand data, not client input."""
        forecasts = _forecasts_by_sku(client)
        skus = list(forecasts)[:2]
        items = [{"sku": skus[0], "quantity": 5}, {"sku": skus[1], "quantity": 3}]

        order = client.post("/api/restock-orders", json={"items": items}).json()

        expected = sum(forecasts[i["sku"]]["unit_cost"] * i["quantity"] for i in items)
        assert abs(order["total_value"] - expected) < 0.01

    def test_restock_order_lead_time_is_longest_item(self, client):
        """Test that the order lead time is the max across its items."""
        forecasts = _forecasts_by_sku(client)
        ordered = sorted(forecasts.values(), key=lambda f: f["lead_time_days"])
        fastest, slowest = ordered[0], ordered[-1]
        assert fastest["lead_time_days"] < slowest["lead_time_days"]

        items = [{"sku": fastest["item_sku"], "quantity": 1}, {"sku": slowest["item_sku"], "quantity": 1}]
        order = client.post("/api/restock-orders", json={"items": items}).json()

        assert order["lead_time_days"] == slowest["lead_time_days"]

    def test_restock_orders_newest_first(self, client):
        """Test that the most recently submitted order is listed first."""
        sku = next(iter(_forecasts_by_sku(client)))
        order = client.post("/api/restock-orders", json={"items": [{"sku": sku, "quantity": 1}]}).json()

        listed = client.get("/api/restock-orders").json()
        assert listed[0]["id"] == order["id"]

    def test_create_restock_order_empty_items(self, client):
        """Test that an empty order is rejected."""
        response = client.post("/api/restock-orders", json={"items": []})
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_create_restock_order_unknown_sku(self, client):
        """Test that an unknown SKU is rejected."""
        response = client.post("/api/restock-orders", json={"items": [{"sku": "NOPE-999", "quantity": 1}]})
        assert response.status_code == 400
        assert "unknown sku" in response.json()["detail"].lower()

    @pytest.mark.parametrize("quantity", [0, -5])
    def test_create_restock_order_invalid_quantity(self, client, quantity):
        """Test that zero or negative quantities are rejected."""
        sku = next(iter(_forecasts_by_sku(client)))
        response = client.post("/api/restock-orders", json={"items": [{"sku": sku, "quantity": quantity}]})
        assert response.status_code == 400
        assert "detail" in response.json()
