"""
Tests for restocking API endpoints.
"""
import pytest
from datetime import datetime

import mock_data


class TestRestockingRecommendationsEndpoint:
    """Test suite for the restocking recommendations endpoint."""

    def test_zero_budget_returns_no_recommendations(self, client):
        """Test that a zero budget yields no recommendations."""
        response = client.get("/api/restocking/recommendations?budget=0")
        assert response.status_code == 200
        assert response.json() == []

    def test_negative_budget_returns_no_recommendations(self, client):
        """Test that a negative budget yields no recommendations."""
        response = client.get("/api/restocking/recommendations?budget=-500")
        assert response.status_code == 200
        assert response.json() == []

    def test_missing_budget_defaults_to_zero(self, client):
        """Test that omitting budget behaves like budget=0."""
        response = client.get("/api/restocking/recommendations")
        assert response.status_code == 200
        assert response.json() == []

    def test_large_budget_returns_recommendations(self, client):
        """Test that a generous budget returns recommended items."""
        response = client.get("/api/restocking/recommendations?budget=100000")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        first_item = data[0]
        assert "sku" in first_item
        assert "name" in first_item
        assert "category" in first_item
        assert "warehouse" in first_item
        assert "quantity_on_hand" in first_item
        assert "reorder_point" in first_item
        assert "shortage" in first_item
        assert "unit_cost" in first_item
        assert "trend" in first_item
        assert "forecasted_demand" in first_item
        assert "recommended_quantity" in first_item
        assert "line_total" in first_item

    def test_recommendations_only_include_understocked_items(self, client):
        """Test that every recommended item is actually below its reorder point."""
        response = client.get("/api/restocking/recommendations?budget=100000")
        data = response.json()

        for item in data:
            assert item["quantity_on_hand"] < item["reorder_point"]
            assert item["shortage"] == item["reorder_point"] - item["quantity_on_hand"]

    def test_recommended_quantity_never_exceeds_shortage(self, client):
        """Test that recommendations never suggest ordering more than the actual shortage."""
        response = client.get("/api/restocking/recommendations?budget=100000")
        data = response.json()

        for item in data:
            assert item["recommended_quantity"] <= item["shortage"]
            assert item["recommended_quantity"] > 0

    def test_line_totals_match_quantity_times_unit_cost(self, client):
        """Test that each line total is quantity * unit_cost."""
        response = client.get("/api/restocking/recommendations?budget=100000")
        data = response.json()

        for item in data:
            expected = round(item["recommended_quantity"] * item["unit_cost"], 2)
            assert abs(item["line_total"] - expected) < 0.01

    def test_recommendations_respect_budget_ceiling(self, client):
        """Test that the sum of recommended line totals never exceeds the given budget."""
        budget = 5000
        response = client.get(f"/api/restocking/recommendations?budget={budget}")
        data = response.json()

        total = sum(item["line_total"] for item in data)
        assert total <= budget

    def test_small_budget_recommends_fewer_items_than_large_budget(self, client):
        """Test that increasing the budget can only add items, never remove coverage."""
        small_response = client.get("/api/restocking/recommendations?budget=100")
        large_response = client.get("/api/restocking/recommendations?budget=100000")

        small_data = small_response.json()
        large_data = large_response.json()

        assert len(small_data) <= len(large_data)

    def test_trend_values_are_valid(self, client):
        """Test that trend is always one of the known demand-forecast trend values."""
        response = client.get("/api/restocking/recommendations?budget=100000")
        data = response.json()

        valid_trends = ["increasing", "stable", "decreasing"]
        for item in data:
            assert item["trend"] in valid_trends


class TestRestockingOrdersEndpoint:
    """Test suite for creating and listing restocking orders."""

    def test_create_restocking_order_success(self, client):
        """Test submitting a restocking order with a workable budget."""
        response = client.post("/api/restocking/orders", json={"budget": 100000})
        assert response.status_code == 201

        order = response.json()
        assert order["id"].startswith("RO-")
        assert order["status"] == "Submitted"
        assert order["budget"] == 100000
        assert order["lead_time_days"] == 7
        assert isinstance(order["items"], list)
        assert len(order["items"]) > 0

    def test_create_restocking_order_total_cost_matches_items(self, client):
        """Test that total_cost equals the sum of item line totals."""
        response = client.post("/api/restocking/orders", json={"budget": 100000})
        order = response.json()

        calculated_total = sum(item["line_total"] for item in order["items"])
        assert abs(order["total_cost"] - calculated_total) < 0.01

    def test_create_restocking_order_expected_delivery_matches_lead_time(self, client):
        """Test that expected_delivery is order_date plus the lead time in days."""
        response = client.post("/api/restocking/orders", json={"budget": 100000})
        order = response.json()

        order_date = datetime.strptime(order["order_date"], "%Y-%m-%d")
        expected_delivery = datetime.strptime(order["expected_delivery"], "%Y-%m-%d")

        assert (expected_delivery - order_date).days == order["lead_time_days"]

    def test_create_restocking_order_zero_budget_fails(self, client):
        """Test that a budget too small to afford anything is rejected."""
        response = client.post("/api/restocking/orders", json={"budget": 0})
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data

    def test_create_restocking_order_missing_budget_is_rejected(self, client):
        """Test that a request body without a budget fails validation."""
        response = client.post("/api/restocking/orders", json={})
        assert response.status_code == 422

    def test_submitted_order_appears_in_orders_list(self, client):
        """Test that a newly created restocking order shows up in the GET list."""
        create_response = client.post("/api/restocking/orders", json={"budget": 100000})
        created_order = create_response.json()

        list_response = client.get("/api/restocking/orders")
        assert list_response.status_code == 200

        all_orders = list_response.json()
        matching = [o for o in all_orders if o["id"] == created_order["id"]]
        assert len(matching) == 1
        assert matching[0]["total_cost"] == created_order["total_cost"]

    def test_get_restocking_orders_returns_list(self, client):
        """Test that the restocking orders list endpoint returns an array."""
        response = client.get("/api/restocking/orders")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestRestockingEdgeCases:
    """Test suite for malformed-data edge cases that previously crashed the recommendation engine."""

    def test_zero_unit_cost_item_is_skipped_not_crashed(self, client):
        """A shortage item with unit_cost 0 must not raise ZeroDivisionError, just be skipped."""
        bad_item = {
            'id': 'test-zero-cost',
            'sku': 'TEST-ZERO-COST',
            'name': 'Zero Cost Test Item',
            'category': 'Test',
            'warehouse': 'San Francisco',
            'quantity_on_hand': 0,
            'reorder_point': 100,
            'unit_cost': 0,
            'location': 'Test',
            'last_updated': '2025-01-01T00:00:00'
        }
        mock_data.inventory_items.append(bad_item)
        try:
            response = client.get("/api/restocking/recommendations?budget=100000")
            assert response.status_code == 200
            skus = [item['sku'] for item in response.json()]
            assert 'TEST-ZERO-COST' not in skus
        finally:
            mock_data.inventory_items.remove(bad_item)

    def test_missing_trend_in_demand_forecast_does_not_crash(self, client):
        """A demand forecast entry with a null trend must not raise AttributeError and should fall back to 'stable'."""
        bad_item = {
            'id': 'test-bad-trend',
            'sku': 'TEST-BAD-TREND',
            'name': 'Bad Trend Test Item',
            'category': 'Test',
            'warehouse': 'San Francisco',
            'quantity_on_hand': 0,
            'reorder_point': 100,
            'unit_cost': 10.0,
            'location': 'Test',
            'last_updated': '2025-01-01T00:00:00'
        }
        bad_forecast = {
            'id': 'test-forecast-bad-trend',
            'item_sku': 'TEST-BAD-TREND',
            'item_name': 'Bad Trend Test Item',
            'current_demand': 10,
            'forecasted_demand': 20,
            'trend': None,
            'period': 'Next 30 days'
        }
        mock_data.inventory_items.append(bad_item)
        mock_data.demand_forecasts.append(bad_forecast)
        try:
            response = client.get("/api/restocking/recommendations?budget=100000")
            assert response.status_code == 200
            matching = [item for item in response.json() if item['sku'] == 'TEST-BAD-TREND']
            assert len(matching) == 1
            assert matching[0]['trend'] == 'stable'
        finally:
            mock_data.inventory_items.remove(bad_item)
            mock_data.demand_forecasts.remove(bad_forecast)
