"""Tests for new_customer_ltv_by_entry_product with ltv_window_days."""

import pandas as pd

from analytics import new_customer_ltv_by_entry_product


def _make_orders(rows):
    df = pd.DataFrame(rows)
    return df


def _make_charges(rows):
    df = pd.DataFrame(rows)
    return df


def _days_ago(n):
    return (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=n)).isoformat()


def _empty_subs():
    return pd.DataFrame(columns=["customer_email", "product_id", "product_name", "status"])


class TestWindowedLTV:
    def setup_method(self):
        # Customer A bought Product X 120 days ago
        # Customer B bought Product X 20 days ago (immature for 30d window)
        self.orders = _make_orders([
            {"customer_email": "a@test.com", "product_id": 1, "product_name": "Product X",
             "total": 100.0, "created_at": _days_ago(120), "id": 1},
            {"customer_email": "b@test.com", "product_id": 1, "product_name": "Product X",
             "total": 100.0, "created_at": _days_ago(20), "id": 2},
        ])
        # A has charges at day 5 ($50) and day 60 ($50); B has charge at day 5 ($50)
        self.charges = _make_charges([
            {"customer_email": "a@test.com", "amount": 50.0, "status": "", "refund_amount": 0,
             "created_at": _days_ago(115), "id": 10},
            {"customer_email": "a@test.com", "amount": 50.0, "status": "", "refund_amount": 0,
             "created_at": _days_ago(60), "id": 11},
            {"customer_email": "b@test.com", "amount": 50.0, "status": "", "refund_amount": 0,
             "created_at": _days_ago(15), "id": 12},
        ])

    def test_all_time_includes_both_customers(self):
        result = new_customer_ltv_by_entry_product(
            self.orders, self.charges, _empty_subs(), ltv_window_days=None
        )
        assert not result.empty
        row = result[result["product_name"] == "Product X"].iloc[0]
        assert row["customer_count"] == 2

    def test_30day_window_excludes_immature_cohort(self):
        # B joined only 20 days ago — not mature for 30d window
        result = new_customer_ltv_by_entry_product(
            self.orders, self.charges, _empty_subs(), ltv_window_days=30
        )
        assert not result.empty
        row = result[result["product_name"] == "Product X"].iloc[0]
        assert row["customer_count"] == 1  # only A (120 days old)

    def test_30day_window_only_counts_charges_within_window(self):
        # A's charge at day 5 is within 30d window; charge at day 60 is outside
        result = new_customer_ltv_by_entry_product(
            self.orders, self.charges, _empty_subs(), ltv_window_days=30
        )
        row = result[result["product_name"] == "Product X"].iloc[0]
        assert abs(row["avg_ltv"] - 50.0) < 0.01  # only the $50 charge within 30 days

    def test_90day_window_includes_both_charges_for_mature_customer(self):
        # A's charges at day 5 and day 60 both fall within 90-day window
        result = new_customer_ltv_by_entry_product(
            self.orders, self.charges, _empty_subs(), ltv_window_days=90
        )
        row = result[result["product_name"] == "Product X"].iloc[0]
        assert abs(row["avg_ltv"] - 100.0) < 0.01  # $50 + $50 = $100

    def test_empty_orders_returns_empty(self):
        result = new_customer_ltv_by_entry_product(
            pd.DataFrame(), self.charges, _empty_subs(), ltv_window_days=30
        )
        assert result.empty

    def test_all_immature_returns_empty(self):
        # Both customers joined within 5 days — none mature for 90d window
        orders = _make_orders([
            {"customer_email": "x@test.com", "product_id": 2, "product_name": "New Product",
             "total": 50.0, "created_at": _days_ago(3), "id": 1},
        ])
        result = new_customer_ltv_by_entry_product(
            orders, self.charges, _empty_subs(), ltv_window_days=90
        )
        assert result.empty
