"""Tests for build_cohort_performance() — charge-based cohort analysis."""

import pandas as pd
import pytest

from analytics import build_cohort_performance


# ------------------------------------------------------------------
# Shared test fixtures
# ------------------------------------------------------------------

def _make_charges():
    """
    5 charges across 2 subscriptions, both weekly, product "Widget" at $99.

    s1: 3 charges (initial + 2 renewals), all successful
    s2: 2 charges (initial successful + 1 refunded renewal)
    """
    return pd.DataFrame({
        "id": ["c1", "c2", "c3", "c4", "c5"],
        "order_id": ["o1", "o1", "o1", "o2", "o2"],
        "subscription_id": ["s1", "s1", "s1", "s2", "s2"],
        "customer_email": ["a@t.co", "a@t.co", "a@t.co", "b@t.co", "b@t.co"],
        "amount": [99.0, 99.0, 99.0, 99.0, 99.0],
        "refund_amount": [0.0, 0.0, 0.0, 0.0, 99.0],
        "status": ["", "", "", "", "refunded"],
        "created_at": [
            "2024-01-01T10:00:00Z",   # s1 period 0
            "2024-01-08T10:00:00Z",   # s1 period 1
            "2024-01-15T10:00:00Z",   # s1 period 2
            "2024-01-01T12:00:00Z",   # s2 period 0
            "2024-01-08T12:00:00Z",   # s2 period 1 (refunded)
        ],
    })


def _make_orders():
    """Orders linked to the two subscriptions."""
    return pd.DataFrame({
        "id": ["o1", "o2"],
        "customer_email": ["a@t.co", "b@t.co"],
        "customer_id": ["1", "2"],
        "product_id": ["p1", "p1"],
        "product_name": ["Widget", "Widget"],
        "total": [99.0, 99.0],
        "created_at": ["2024-01-01T10:00:00Z", "2024-01-01T12:00:00Z"],
        "subscription_id": ["s1", "s2"],
    })


def _make_subscriptions():
    """Two weekly subscriptions for Widget."""
    return pd.DataFrame({
        "id": ["s1", "s2"],
        "customer_email": ["a@t.co", "b@t.co"],
        "product_id": ["p1", "p1"],
        "product_name": ["Widget", "Widget"],
        "status": ["active", "canceled"],
        "interval": ["weekly", "weekly"],
        "price": [99.0, 99.0],
        "created_at": ["2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"],
        "canceled_at": [None, "2024-01-10T00:00:00Z"],
    })


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestReturnShape:
    """build_cohort_performance returns a tuple of 3 DataFrames."""

    def test_returns_three_dataframes(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        result = build_cohort_performance(charges, orders, subs)
        assert isinstance(result, tuple)
        assert len(result) == 3
        activity, renewal, stick = result
        assert isinstance(activity, pd.DataFrame)
        assert isinstance(renewal, pd.DataFrame)
        assert isinstance(stick, pd.DataFrame)


class TestActivitySummaryColumns:
    """Activity summary has the expected columns."""

    def test_columns_present(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(charges, orders, subs)
        expected_cols = {
            "period", "active_subscribers", "renewals", "initial_charges",
            "total_charged", "cumulative_refunds", "refunds_this_period",
            "period_revenue", "cumulative_revenue",
        }
        assert expected_cols.issubset(set(activity.columns))


class TestPeriodZero:
    """Period 0 counts initial charges and revenue correctly."""

    def test_initial_charges_count(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(charges, orders, subs)
        p0 = activity[activity["period"] == 0].iloc[0]
        # Period 0: 2 subscriptions (s1 and s2) both have initial charge
        assert p0["active_subscribers"] == 2
        assert p0["initial_charges"] == 2
        assert p0["renewals"] == 0

    def test_period_zero_revenue(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(charges, orders, subs)
        p0 = activity[activity["period"] == 0].iloc[0]
        # Both initial charges are successful at $99
        assert p0["period_revenue"] == 198.0

    def test_period_zero_no_refunds(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(charges, orders, subs)
        p0 = activity[activity["period"] == 0].iloc[0]
        assert p0["refunds_this_period"] == 0


class TestRenewalsAndRefunds:
    """Period 1+ counts renewals and tracks refunds."""

    def test_period_one_renewals(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(charges, orders, subs)
        p1 = activity[activity["period"] == 1].iloc[0]
        # Period 1: s1 has a successful renewal, s2 has a refunded renewal
        # active_subscribers = unique subs with a successful charge in this period
        assert p1["active_subscribers"] == 1  # only s1 is successful
        assert p1["renewals"] == 1
        assert p1["initial_charges"] == 0

    def test_period_one_refund_tracked(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(charges, orders, subs)
        p1 = activity[activity["period"] == 1].iloc[0]
        assert p1["refunds_this_period"] == 1

    def test_period_one_total_charged(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(charges, orders, subs)
        p1 = activity[activity["period"] == 1].iloc[0]
        # total_charged = successful + refunded subscription count = 2
        assert p1["total_charged"] == 2

    def test_period_two_only_s1(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(charges, orders, subs)
        p2 = activity[activity["period"] == 2].iloc[0]
        # Period 2: only s1 has a charge
        assert p2["active_subscribers"] == 1
        assert p2["renewals"] == 1


class TestRenewalRateCalculation:
    """Renewal rate DataFrame is correct."""

    def test_renewal_rate_columns(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        _, renewal, _ = build_cohort_performance(charges, orders, subs)
        expected_cols = {
            "period", "subscribers_start", "subscribers_end",
            "dropped_off", "renewal_rate", "stick_rate", "notes",
        }
        assert expected_cols.issubset(set(renewal.columns))

    def test_no_period_zero_in_renewal(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        _, renewal, _ = build_cohort_performance(charges, orders, subs)
        assert 0 not in renewal["period"].values

    def test_period_one_renewal_rate(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        _, renewal, _ = build_cohort_performance(charges, orders, subs)
        r1 = renewal[renewal["period"] == 1].iloc[0]
        # subscribers_start = active_subscribers at period 0 = 2
        # subscribers_end = active_subscribers at period 1 = 1
        assert r1["subscribers_start"] == 2
        assert r1["subscribers_end"] == 1
        assert r1["dropped_off"] == 1
        assert r1["renewal_rate"] == pytest.approx(50.0)

    def test_largest_drop_note(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        _, renewal, _ = build_cohort_performance(charges, orders, subs)
        # The row with max dropped_off should have the note
        noted = renewal[renewal["notes"] == "Largest period-over-period drop"]
        assert len(noted) >= 1


class TestStickRateCalculation:
    """Stick rate DataFrame is correct."""

    def test_stick_rate_columns(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        _, _, stick = build_cohort_performance(charges, orders, subs)
        expected_cols = {
            "period", "original_cohort", "still_active",
            "dropped_cumulative", "stick_rate", "cumulative_refunds",
            "refund_rate", "churn_refund_rate",
        }
        assert expected_cols.issubset(set(stick.columns))

    def test_period_zero_stick_rate_100(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        _, _, stick = build_cohort_performance(charges, orders, subs)
        s0 = stick[stick["period"] == 0].iloc[0]
        assert s0["stick_rate"] == pytest.approx(100.0)
        assert s0["original_cohort"] == 2
        assert s0["still_active"] == 2

    def test_period_one_stick_rate(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        _, _, stick = build_cohort_performance(charges, orders, subs)
        s1 = stick[stick["period"] == 1].iloc[0]
        # 1 of 2 still active = 50%
        assert s1["stick_rate"] == pytest.approx(50.0)
        assert s1["dropped_cumulative"] == 1

    def test_cumulative_refunds_in_stick(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        _, _, stick = build_cohort_performance(charges, orders, subs)
        s1 = stick[stick["period"] == 1].iloc[0]
        assert s1["cumulative_refunds"] == 1
        assert s1["refund_rate"] == pytest.approx(50.0)


class TestCumulativeRevenue:
    """Cumulative revenue is monotonically non-decreasing."""

    def test_cumulative_non_decreasing(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(charges, orders, subs)
        cum = activity["cumulative_revenue"].tolist()
        for i in range(1, len(cum)):
            assert cum[i] >= cum[i - 1]

    def test_cumulative_revenue_values(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(charges, orders, subs)
        # Period 0: 2 x $99 = $198, Period 1: 1 x $99 = $99 (refund nets to 0)
        # Period 2: 1 x $99 = $99
        # Cumulative: 198, 297, 396
        assert activity[activity["period"] == 0].iloc[0]["cumulative_revenue"] == 198.0
        assert activity[activity["period"] == 1].iloc[0]["cumulative_revenue"] == 297.0
        assert activity[activity["period"] == 2].iloc[0]["cumulative_revenue"] == 396.0


class TestEmptyInput:
    """Empty charges returns empty DataFrames with correct columns."""

    def test_empty_charges(self):
        empty_charges = pd.DataFrame(columns=[
            "id", "order_id", "subscription_id", "customer_email",
            "amount", "refund_amount", "status", "created_at",
        ])
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, renewal, stick = build_cohort_performance(
            empty_charges, orders, subs,
        )
        assert activity.empty
        assert renewal.empty
        assert stick.empty
        # Check columns are still correct
        assert "period" in activity.columns
        assert "period" in renewal.columns
        assert "period" in stick.columns

    def test_no_subscription_charges(self):
        """Charges without subscription_id should be excluded."""
        charges = pd.DataFrame({
            "id": ["c1", "c2"],
            "order_id": ["o1", "o2"],
            "subscription_id": ["", ""],  # no subscription link
            "customer_email": ["a@t.co", "b@t.co"],
            "amount": [99.0, 99.0],
            "refund_amount": [0.0, 0.0],
            "status": ["", ""],
            "created_at": [
                "2024-01-01T10:00:00Z",
                "2024-01-08T10:00:00Z",
            ],
        })
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, renewal, stick = build_cohort_performance(
            charges, orders, subs,
        )
        assert activity.empty
        assert renewal.empty
        assert stick.empty


class TestChargesWithoutSubExcluded:
    """Charges without subscription_id are excluded even when mixed with valid ones."""

    def test_mixed_sub_and_non_sub_charges(self):
        charges = _make_charges()
        # Add a non-subscription charge
        extra = pd.DataFrame({
            "id": ["c_nosub"],
            "order_id": ["o99"],
            "subscription_id": [""],
            "customer_email": ["z@t.co"],
            "amount": [500.0],
            "refund_amount": [0.0],
            "status": [""],
            "created_at": ["2024-01-01T10:00:00Z"],
        })
        mixed = pd.concat([charges, extra], ignore_index=True)
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(mixed, orders, subs)
        # The $500 non-sub charge should not appear
        p0 = activity[activity["period"] == 0].iloc[0]
        assert p0["period_revenue"] == 198.0  # same as without extra charge


class TestMonthlyIntervalFilter:
    """Monthly interval still works (interval is metadata from subscriptions)."""

    def test_monthly_interval_filter(self):
        charges = _make_charges()
        orders = _make_orders()
        # Change subscriptions to monthly
        subs = _make_subscriptions()
        subs["interval"] = "monthly"
        activity, renewal, stick = build_cohort_performance(
            charges, orders, subs, interval_filter="monthly",
        )
        # Should still work — same charges, just filtered by interval
        assert not activity.empty
        p0 = activity[activity["period"] == 0].iloc[0]
        assert p0["active_subscribers"] == 2

    def test_interval_filter_excludes_non_matching(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()  # weekly
        # Filter for monthly should exclude all weekly subs
        activity, _, _ = build_cohort_performance(
            charges, orders, subs, interval_filter="monthly",
        )
        assert activity.empty


class TestProductFilter:
    """Product filter works correctly."""

    def test_filter_matching_product(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(
            charges, orders, subs, product_filter="p1",
        )
        assert not activity.empty

    def test_filter_non_matching_product(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(
            charges, orders, subs, product_filter="p_nonexistent",
        )
        assert activity.empty


class TestCombinedCohort:
    """combined_cohort flag treats all subscriptions as one cohort."""

    def test_combined_cohort_true(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, _, _ = build_cohort_performance(
            charges, orders, subs, combined_cohort=True,
        )
        assert not activity.empty
        # Should still work the same — all subs combined
        p0 = activity[activity["period"] == 0].iloc[0]
        assert p0["active_subscribers"] == 2
