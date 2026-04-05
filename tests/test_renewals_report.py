"""Tests for upcoming_renewals_and_cancellations in analytics.py."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from analytics import upcoming_renewals_and_cancellations


def _make_subs(rows):
    """Helper to build a subscriptions DataFrame."""
    return pd.DataFrame(rows)


class TestUpcomingRenewals:
    def test_renewal_within_window(self):
        now = datetime.now(timezone.utc)
        subs = _make_subs([{
            "id": "1", "customer_email": "a@test.com",
            "product_name": "Course A", "status": "active",
            "next_bill_date": (now + timedelta(days=5)).isoformat(),
            "interval": "monthly", "price": 49.99,
        }])
        result = upcoming_renewals_and_cancellations(subs, lookahead_weeks=1)
        assert len(result["renewals"]) == 1
        assert result["renewals"].iloc[0]["customer_email"] == "a@test.com"

    def test_renewal_outside_window(self):
        now = datetime.now(timezone.utc)
        subs = _make_subs([{
            "id": "1", "customer_email": "a@test.com",
            "product_name": "Course A", "status": "active",
            "next_bill_date": (now + timedelta(days=30)).isoformat(),
            "interval": "monthly", "price": 49.99,
        }])
        result = upcoming_renewals_and_cancellations(subs, lookahead_weeks=1)
        assert len(result["renewals"]) == 0

    def test_cancellation_within_window(self):
        now = datetime.now(timezone.utc)
        subs = _make_subs([{
            "id": "2", "customer_email": "b@test.com",
            "product_name": "Course B", "status": "canceled",
            "canceled_at": (now + timedelta(days=5)).isoformat(),
            "next_bill_date": None, "interval": "monthly", "price": 29.99,
        }])
        result = upcoming_renewals_and_cancellations(subs, lookahead_weeks=1)
        assert len(result["cancellations"]) == 1

    def test_multiple_lookahead_windows(self):
        now = datetime.now(timezone.utc)
        subs = _make_subs([
            {"id": "1", "customer_email": "a@test.com", "product_name": "P1",
             "status": "active", "next_bill_date": (now + timedelta(days=5)).isoformat(),
             "interval": "monthly", "price": 49.99},
            {"id": "2", "customer_email": "b@test.com", "product_name": "P2",
             "status": "active", "next_bill_date": (now + timedelta(days=20)).isoformat(),
             "interval": "monthly", "price": 29.99},
        ])
        r1 = upcoming_renewals_and_cancellations(subs, lookahead_weeks=1)
        r4 = upcoming_renewals_and_cancellations(subs, lookahead_weeks=4)
        assert len(r1["renewals"]) == 1
        assert len(r4["renewals"]) == 2

    def test_empty_input(self):
        result = upcoming_renewals_and_cancellations(pd.DataFrame())
        assert result["renewals"].empty
        assert result["cancellations"].empty

    def test_product_filter(self):
        now = datetime.now(timezone.utc)
        subs = _make_subs([
            {"id": "1", "customer_email": "a@test.com", "product_name": "P1",
             "status": "active", "next_bill_date": (now + timedelta(days=3)).isoformat(),
             "interval": "monthly", "price": 49.99},
            {"id": "2", "customer_email": "b@test.com", "product_name": "P2",
             "status": "active", "next_bill_date": (now + timedelta(days=3)).isoformat(),
             "interval": "monthly", "price": 29.99},
        ])
        result = upcoming_renewals_and_cancellations(subs, product_filter=["P1"])
        assert len(result["renewals"]) == 1
        assert result["renewals"].iloc[0]["product_name"] == "P1"
