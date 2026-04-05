"""Tests for vip_customers in analytics.py."""

import pandas as pd

from analytics import vip_customers


class TestVIPCustomers:
    def test_high_ltv_above_threshold(self):
        charges = pd.DataFrame([
            {"customer_email": "whale@test.com", "amount": 5000, "status": None,
             "refund_amount": 0},
            {"customer_email": "small@test.com", "amount": 100, "status": None,
             "refund_amount": 0},
        ])
        orders = pd.DataFrame(columns=["customer_email", "total"])
        subs = pd.DataFrame(
            columns=["customer_email", "status", "interval",
                      "billing_cycle_count", "product_name", "price"]
        )
        result = vip_customers(charges, orders, subs, ltv_threshold=4000)
        assert len(result["high_ltv"]) == 1
        assert result["high_ltv"].iloc[0]["customer_email"] == "whale@test.com"

    def test_loyal_subscribers(self):
        charges = pd.DataFrame(
            columns=["customer_email", "amount", "status", "refund_amount"]
        )
        orders = pd.DataFrame(columns=["customer_email", "total"])
        subs = pd.DataFrame([
            {"customer_email": "loyal@test.com", "status": "active",
             "interval": "monthly", "billing_cycle_count": 6,
             "product_name": "Course A", "price": 49.99},
            {"customer_email": "new@test.com", "status": "active",
             "interval": "monthly", "billing_cycle_count": 1,
             "product_name": "Course A", "price": 49.99},
        ])
        result = vip_customers(charges, orders, subs, min_billing_cycles=3)
        assert len(result["loyal_subscribers"]) == 1
        assert result["loyal_subscribers"].iloc[0]["customer_email"] == "loyal@test.com"

    def test_custom_thresholds(self):
        charges = pd.DataFrame([
            {"customer_email": "a@test.com", "amount": 1500, "status": None,
             "refund_amount": 0},
        ])
        orders = pd.DataFrame(columns=["customer_email", "total"])
        subs = pd.DataFrame(
            columns=["customer_email", "status", "interval",
                      "billing_cycle_count", "product_name", "price"]
        )
        r1 = vip_customers(charges, orders, subs, ltv_threshold=4000)
        assert len(r1["high_ltv"]) == 0
        r2 = vip_customers(charges, orders, subs, ltv_threshold=1000)
        assert len(r2["high_ltv"]) == 1

    def test_empty_input(self):
        charges = pd.DataFrame(
            columns=["customer_email", "amount", "status", "refund_amount"]
        )
        orders = pd.DataFrame(columns=["customer_email", "total"])
        subs = pd.DataFrame(
            columns=["customer_email", "status", "interval",
                      "billing_cycle_count", "product_name", "price"]
        )
        result = vip_customers(charges, orders, subs)
        assert result["high_ltv"].empty
        assert result["loyal_subscribers"].empty
