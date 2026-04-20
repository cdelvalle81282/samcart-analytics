"""
Regression tests for the four audit findings fixed in this session.

Finding 1: cohort partially_refunded inclusion
Finding 2: trial-aware first-charge classification
Finding 3: tied-timestamp rank stability
Finding 4: VIP product filter scopes high_ltv
"""

import pandas as pd

from analytics import (
    _identify_renewals,
    build_cohort_performance,
    vip_customers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sub(sub_id, email, product="Prod A", interval="monthly",
         created_at="2025-01-01T00:00:00Z", trial_days=0, status="active",
         billing_cycle_count=1):
    return {
        "id": sub_id,
        "customer_email": email,
        "product_id": "p1",
        "product_name": product,
        "status": status,
        "interval": interval,
        "price": 99.0,
        "created_at": created_at,
        "canceled_at": None,
        "trial_days": trial_days,
        "next_bill_date": None,
        "billing_cycle_count": billing_cycle_count,
    }


def _charge(charge_id, sub_id, email, amount, status, created_at,
            refund_amount=0.0, order_id=""):
    return {
        "id": str(charge_id),
        "subscription_id": sub_id,
        "customer_email": email,
        "amount": amount,
        "status": status,
        "created_at": created_at,
        "refund_amount": refund_amount,
        "order_id": order_id,
    }


# ---------------------------------------------------------------------------
# Finding 3: tied timestamps must produce exactly one rank-1 charge
# ---------------------------------------------------------------------------

class TestTiedTimestampRanking:
    def test_two_same_second_charges_only_one_is_initial(self):
        charges = pd.DataFrame([
            _charge(1, "sub1", "a@t.com", 99, None, "2025-02-01T10:00:00Z"),
            _charge(2, "sub1", "a@t.com", 99, None, "2025-02-01T10:00:00Z"),
        ])
        # Sub created same day as charges so the old-sub heuristic doesn't fire
        subs = pd.DataFrame([_sub("sub1", "a@t.com", created_at="2025-02-01T09:55:00Z")])
        result = _identify_renewals(charges, subs)
        # Exactly one charge is rank-1 (not a renewal); the other is rank-2 (renewal)
        assert result.sum() == 1, f"Expected 1 renewal, got {result.sum()}"
        assert not result.all(), "Both charges were marked renewal — should be one each"

    def test_three_same_second_charges_two_are_renewals(self):
        charges = pd.DataFrame([
            _charge(1, "sub1", "a@t.com", 99, None, "2025-02-01T10:00:00Z"),
            _charge(2, "sub1", "a@t.com", 99, None, "2025-02-01T10:00:00Z"),
            _charge(3, "sub1", "a@t.com", 99, None, "2025-02-01T10:00:00Z"),
        ])
        subs = pd.DataFrame([_sub("sub1", "a@t.com", created_at="2025-02-01T09:55:00Z")])
        result = _identify_renewals(charges, subs)
        assert result.sum() == 2


# ---------------------------------------------------------------------------
# Finding 1: partially_refunded charges count as active cohort activity
# ---------------------------------------------------------------------------

class TestCohortPartialRefund:
    def _make_cohort_data(self):
        subs = pd.DataFrame([
            _sub("sub1", "full@t.com", created_at="2025-01-15T00:00:00Z"),
            _sub("sub2", "partial@t.com", created_at="2025-01-15T00:00:00Z"),
        ])
        charges = pd.DataFrame([
            # sub1: normal successful period-0 charge
            _charge(1, "sub1", "full@t.com", 99, None,
                    "2025-01-15T00:00:00Z"),
            # sub2: partial refund period-0 charge — net revenue = 99 - 20 = 79
            _charge(2, "sub2", "partial@t.com", 99, "partially_refunded",
                    "2025-01-15T00:00:00Z", refund_amount=20.0),
        ])
        orders = pd.DataFrame(columns=["id", "customer_email", "product_id",
                                        "product_name", "total", "created_at",
                                        "subscription_id"])
        return subs, charges, orders

    def test_partially_refunded_counts_as_active(self):
        subs, charges, orders = self._make_cohort_data()
        activity, _, _ = build_cohort_performance(charges, orders, subs)
        p0 = activity[activity["period"] == 0].iloc[0]
        assert p0["active_subscribers"] == 2, (
            f"partially_refunded sub should count as active, got {p0['active_subscribers']}"
        )

    def test_partially_refunded_revenue_is_net(self):
        subs, charges, orders = self._make_cohort_data()
        activity, _, _ = build_cohort_performance(charges, orders, subs)
        p0 = activity[activity["period"] == 0].iloc[0]
        assert abs(p0["period_revenue"] - 178.0) < 0.01, (
            f"Expected 99 + 79 = 178, got {p0['period_revenue']}"
        )

    def test_partially_refunded_appears_in_refunds_this_period(self):
        # partially_refunded is in REFUND_CHARGE_STATUSES so it counts as a refund event —
        # this documents intended behavior (partial refunds are tracked as refund activity).
        subs, charges, orders = self._make_cohort_data()
        activity, _, _ = build_cohort_performance(charges, orders, subs)
        p0 = activity[activity["period"] == 0].iloc[0]
        assert p0["refunds_this_period"] == 1, (
            f"partial refund should appear in refunds_this_period, got {p0['refunds_this_period']}"
        )


# ---------------------------------------------------------------------------
# Finding 2: trial-aware first-charge classification
# ---------------------------------------------------------------------------

class TestTrialAwareRenewalClassification:
    def test_trial_first_charge_is_not_renewal(self):
        """14-day trial: subscription Jan 1, first paid charge Jan 15 — not a renewal."""
        charges = pd.DataFrame([
            _charge(1, "sub1", "trial@t.com", 99, None, "2025-01-15T00:00:00Z"),
        ])
        subs = pd.DataFrame([
            _sub("sub1", "trial@t.com", created_at="2025-01-01T00:00:00Z", trial_days=14)
        ])
        result = _identify_renewals(charges, subs)
        assert not result.iloc[0], "Trial first-paid charge should NOT be a renewal"

    def test_incomplete_history_old_sub_is_renewal(self):
        """No trial, subscription Jan 1, charge May 1 (120d gap) — missing history, is renewal."""
        charges = pd.DataFrame([
            _charge(1, "sub1", "old@t.com", 99, None, "2025-05-01T00:00:00Z"),
        ])
        subs = pd.DataFrame([
            _sub("sub1", "old@t.com", created_at="2025-01-01T00:00:00Z", trial_days=0)
        ])
        result = _identify_renewals(charges, subs)
        assert result.iloc[0], "Old sub with no trial and 120d gap should be a renewal"

    def test_same_day_charge_is_not_renewal(self):
        """No trial, subscription and charge same day — genuine first purchase."""
        charges = pd.DataFrame([
            _charge(1, "sub1", "new@t.com", 99, None, "2025-03-01T10:05:00Z"),
        ])
        subs = pd.DataFrame([
            _sub("sub1", "new@t.com", created_at="2025-03-01T10:00:00Z", trial_days=0)
        ])
        result = _identify_renewals(charges, subs)
        assert not result.iloc[0], "Same-day charge should not be a renewal"

    def test_long_trial_first_charge_within_window(self):
        """30-day trial + 7-day grace = 37-day threshold. Charge at day 30 is not renewal."""
        charges = pd.DataFrame([
            _charge(1, "sub1", "longtrial@t.com", 99, None, "2025-02-01T00:00:00Z"),
        ])
        subs = pd.DataFrame([
            _sub("sub1", "longtrial@t.com", created_at="2025-01-01T00:00:00Z", trial_days=30)
        ])
        result = _identify_renewals(charges, subs)
        assert not result.iloc[0], "Charge within trial+grace window should not be a renewal"

    def test_subscriptions_without_trial_days_column(self):
        """Subscriptions frame missing trial_days must not raise KeyError."""
        charges = pd.DataFrame([
            _charge(1, "sub1", "a@t.com", 99, None, "2025-03-01T10:05:00Z"),
        ])
        # Deliberately omit trial_days from the subscriptions frame
        subs = pd.DataFrame([{
            "id": "sub1",
            "customer_email": "a@t.com",
            "product_id": "p1",
            "product_name": "Prod A",
            "status": "active",
            "interval": "monthly",
            "price": 99.0,
            "created_at": "2025-03-01T10:00:00Z",
            "canceled_at": None,
            "next_bill_date": None,
            "billing_cycle_count": 1,
            # trial_days intentionally absent
        }])
        result = _identify_renewals(charges, subs)
        assert not result.iloc[0], "Same-day charge without trial_days column should not be a renewal"


# ---------------------------------------------------------------------------
# Finding 4: VIP product filter scopes high_ltv
# ---------------------------------------------------------------------------

class TestVIPProductFilter:
    def _make_vip_data(self):
        charges = pd.DataFrame([
            {"id": "c1", "customer_email": "alice@t.com", "amount": 5000,
             "status": None, "refund_amount": 0, "order_id": "o1",
             "subscription_id": ""},
            {"id": "c2", "customer_email": "bob@t.com", "amount": 5000,
             "status": None, "refund_amount": 0, "order_id": "o2",
             "subscription_id": ""},
        ])
        orders = pd.DataFrame([
            {"id": "o1", "customer_email": "alice@t.com", "product_id": "pA",
             "product_name": "Product A", "total": 5000,
             "created_at": "2025-01-01T00:00:00Z", "subscription_id": ""},
            {"id": "o2", "customer_email": "bob@t.com", "product_id": "pB",
             "product_name": "Product B", "total": 5000,
             "created_at": "2025-01-01T00:00:00Z", "subscription_id": ""},
        ])
        subs = pd.DataFrame(
            columns=["customer_email", "status", "interval",
                     "billing_cycle_count", "product_name", "price", "id",
                     "product_id", "created_at", "canceled_at", "trial_days",
                     "next_bill_date"]
        )
        return charges, orders, subs

    def test_product_filter_excludes_other_product_whales(self):
        charges, orders, subs = self._make_vip_data()
        result = vip_customers(charges, orders, subs, ltv_threshold=4000,
                               product_filter=["Product A"])
        emails = result["high_ltv"]["customer_email"].tolist()
        assert "alice@t.com" in emails, "Alice (Product A buyer) should be in high_ltv"
        assert "bob@t.com" not in emails, "Bob (Product B buyer) should be excluded by product filter"

    def test_no_filter_includes_all(self):
        charges, orders, subs = self._make_vip_data()
        result = vip_customers(charges, orders, subs, ltv_threshold=4000)
        emails = result["high_ltv"]["customer_email"].tolist()
        assert "alice@t.com" in emails
        assert "bob@t.com" in emails

    def test_product_filter_excludes_other_product_whales_empty_charges(self):
        """Product filter must scope high_ltv even when charges_df is empty (orders fallback)."""
        _, orders, subs = self._make_vip_data()
        empty_charges = pd.DataFrame(
            columns=["id", "customer_email", "amount", "status",
                     "refund_amount", "order_id", "subscription_id"]
        )
        result = vip_customers(empty_charges, orders, subs, ltv_threshold=4000,
                               product_filter=["Product A"])
        emails = result["high_ltv"]["customer_email"].tolist()
        assert "alice@t.com" in emails, "Alice should be in high_ltv via orders fallback"
        assert "bob@t.com" not in emails, "Bob (Product B) should be excluded even with empty charges"
