"""Tests for the 12 new analytics functions and updated helpers."""

import pandas as pd
import pytest

from analytics import (
    _is_collected_charge,
    _is_gross_charge,
    _net_charge_amount,
    _normalize_to_monthly,
    arpu_by_product,
    churn_analysis,
    customer_concentration,
    daily_refunds,
    failed_payment_analysis,
    mrr_waterfall,
    multi_product_buyers,
    net_revenue_retention,
    new_vs_renewal_revenue_mix,
    product_attach_rate,
    product_mrr_trend,
    refund_analysis,
    revenue_forecast,
    rfm_segmentation,
    subscription_aging,
    trial_conversion,
    trial_days_to_convert,
)


# ------------------------------------------------------------------
# Shared test helpers
# ------------------------------------------------------------------

def _make_charges(**overrides):
    """Build a minimal charges DataFrame."""
    defaults = {
        "id": ["c1", "c2", "c3"],
        "order_id": ["o1", "o2", "o3"],
        "subscription_id": ["s1", "s2", ""],
        "customer_email": ["a@t.co", "b@t.co", "c@t.co"],
        "amount": [100.0, 200.0, 50.0],
        "status": ["", "", "refunded"],
        "created_at": [
            "2024-01-15T10:00:00Z",
            "2024-02-15T10:00:00Z",
            "2024-03-15T10:00:00Z",
        ],
        "refund_amount": [0.0, 0.0, 50.0],
        "refund_date": [None, None, "2024-03-20T10:00:00Z"],
    }
    defaults.update(overrides)
    return pd.DataFrame(defaults)


def _make_orders(**overrides):
    """Build a minimal orders DataFrame."""
    defaults = {
        "id": ["o1", "o2", "o3"],
        "customer_email": ["a@t.co", "b@t.co", "c@t.co"],
        "customer_id": ["1", "2", "3"],
        "product_id": ["p1", "p2", "p1"],
        "product_name": ["Product A", "Product B", "Product A"],
        "total": [100.0, 200.0, 50.0],
        "created_at": [
            "2024-01-15T10:00:00Z",
            "2024-02-15T10:00:00Z",
            "2024-03-15T10:00:00Z",
        ],
        "subscription_id": ["s1", "s2", ""],
    }
    defaults.update(overrides)
    return pd.DataFrame(defaults)


def _make_subscriptions(**overrides):
    """Build a minimal subscriptions DataFrame."""
    defaults = {
        "id": ["s1", "s2"],
        "customer_email": ["a@t.co", "b@t.co"],
        "product_id": ["p1", "p2"],
        "product_name": ["Product A", "Product B"],
        "status": ["active", "canceled"],
        "interval": ["monthly", "monthly"],
        "price": [29.99, 49.99],
        "created_at": ["2024-01-01T00:00:00Z", "2024-01-15T00:00:00Z"],
        "canceled_at": [None, "2024-06-15T00:00:00Z"],
        "trial_days": [0, 14],
        "next_bill_date": ["2024-07-01T00:00:00Z", None],
        "billing_cycle_count": [6, 0],
    }
    defaults.update(overrides)
    return pd.DataFrame(defaults)


# ------------------------------------------------------------------
# Helper tests
# ------------------------------------------------------------------


class TestCollectedCharge:
    def test_successful_is_collected(self):
        s = pd.Series(["", "charged", "succeeded", "paid", "complete"])
        result = _is_collected_charge(s)
        assert result.all()

    def test_partially_refunded_is_collected(self):
        s = pd.Series(["partially_refunded"])
        assert _is_collected_charge(s).all()

    def test_fully_refunded_not_collected(self):
        s = pd.Series(["refunded", "refund"])
        assert not _is_collected_charge(s).any()

    def test_failed_not_collected(self):
        s = pd.Series(["failed", "pending"])
        assert not _is_collected_charge(s).any()


class TestGrossCharge:
    def test_includes_successful_and_refunded(self):
        s = pd.Series(["", "charged", "refunded", "partially_refunded"])
        result = _is_gross_charge(s)
        assert result.all()

    def test_excludes_failed(self):
        s = pd.Series(["failed", "pending"])
        assert not _is_gross_charge(s).any()


class TestNetChargeAmount:
    def test_successful_uses_full_amount(self):
        df = pd.DataFrame({"amount": [100.0], "status": [""], "refund_amount": [0.0]})
        result = _net_charge_amount(df)
        assert result.iloc[0] == 100.0

    def test_partial_refund_subtracts(self):
        df = pd.DataFrame({"amount": [100.0], "status": ["partially_refunded"], "refund_amount": [25.0]})
        result = _net_charge_amount(df)
        assert result.iloc[0] == 75.0

    def test_fully_refunded_is_zero(self):
        df = pd.DataFrame({"amount": [100.0], "status": ["refunded"], "refund_amount": [100.0]})
        result = _net_charge_amount(df)
        assert result.iloc[0] == 0.0

    def test_clamps_to_zero(self):
        df = pd.DataFrame({"amount": [50.0], "status": ["partially_refunded"], "refund_amount": [75.0]})
        result = _net_charge_amount(df)
        assert result.iloc[0] == 0.0

    def test_missing_refund_amount_column(self):
        df = pd.DataFrame({"amount": [100.0], "status": [""]})
        result = _net_charge_amount(df)
        assert result.iloc[0] == 100.0


class TestNormalizeToMonthly:
    def test_monthly_unchanged(self):
        assert _normalize_to_monthly(100, "monthly") == 100.0

    def test_yearly_divides_by_12(self):
        assert abs(_normalize_to_monthly(120, "yearly") - 10.0) < 0.01

    def test_quarterly(self):
        assert abs(_normalize_to_monthly(90, "quarterly") - 30.0) < 0.01

    def test_unknown_defaults_to_1(self):
        assert _normalize_to_monthly(100, "unknown") == 100.0


# ------------------------------------------------------------------
# Report function tests
# ------------------------------------------------------------------


class TestMrrWaterfall:
    def test_empty_input(self):
        result = mrr_waterfall(pd.DataFrame())
        assert result.empty

    def test_basic_waterfall(self):
        subs = _make_subscriptions()
        result = mrr_waterfall(subs)
        assert not result.empty
        assert "new_mrr" in result.columns
        assert "churned_mrr" in result.columns
        assert "net_mrr" in result.columns


class TestRevenueForecast:
    def test_empty_input(self):
        result = revenue_forecast(pd.DataFrame())
        assert result.empty

    def test_no_next_bill_date(self):
        subs = _make_subscriptions(next_bill_date=[None, None])
        result = revenue_forecast(subs)
        assert result.empty

    def test_basic_forecast(self):
        subs = _make_subscriptions(
            status=["active", "active"],
            next_bill_date=["2099-01-15T00:00:00Z", "2099-01-20T00:00:00Z"],
            canceled_at=[None, None],
        )
        result = revenue_forecast(subs)
        assert not result.empty
        assert "forecast_30d" in result.columns


class TestRefundAnalysis:
    def test_empty_input(self):
        bp, ttf, mt = refund_analysis(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        assert bp.empty
        assert ttf.empty
        assert mt.empty

    def test_basic_analysis(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        bp, ttf, mt = refund_analysis(charges, orders, subs)
        assert not bp.empty
        assert "refund_rate_count_pct" in bp.columns


class TestChurnAnalysis:
    def test_empty_input(self):
        bp, mt = churn_analysis(pd.DataFrame())
        assert bp.empty
        assert mt.empty

    def test_basic_churn(self):
        subs = _make_subscriptions()
        bp, mt = churn_analysis(subs)
        assert not bp.empty
        assert "churn_rate" in bp.columns
        assert not mt.empty


class TestTrialConversion:
    def test_empty_input(self):
        result = trial_conversion(pd.DataFrame())
        assert result.empty

    def test_no_trial_days_column(self):
        subs = _make_subscriptions()
        subs = subs.drop(columns=["trial_days"])
        result = trial_conversion(subs)
        assert result.empty

    def test_basic_conversion(self):
        subs = _make_subscriptions(
            id=["s1", "s2", "s3"],
            customer_email=["a@t.co", "b@t.co", "c@t.co"],
            product_id=["p1", "p1", "p1"],
            product_name=["Product A", "Product A", "Product A"],
            status=["active", "canceled", "canceled"],
            interval=["monthly", "monthly", "monthly"],
            price=[29.99, 29.99, 29.99],
            created_at=["2024-01-01T00:00:00Z", "2024-01-15T00:00:00Z", "2024-02-01T00:00:00Z"],
            canceled_at=[None, "2024-02-15T00:00:00Z", "2024-02-20T00:00:00Z"],
            trial_days=[14, 14, 14],
            next_bill_date=["2024-07-01T00:00:00Z", None, None],
            billing_cycle_count=[3, 0, 1],
        )
        result = trial_conversion(subs)
        assert not result.empty
        # s1 converted (cycle_count=3), s2 dropped (canceled, cycle=0), s3 converted (cycle=1)
        assert result.iloc[0]["converted"] == 2
        assert result.iloc[0]["dropped"] == 1


class TestSubscriptionAging:
    def test_empty_input(self):
        result = subscription_aging(pd.DataFrame())
        assert result.empty

    def test_basic_aging(self):
        subs = _make_subscriptions()
        result = subscription_aging(subs)
        # Only active subs included — s1 is active, s2 is canceled
        assert not result.empty
        assert "age_bucket" in result.columns


class TestRfmSegmentation:
    def test_empty_input(self):
        result = rfm_segmentation(pd.DataFrame(), pd.DataFrame())
        assert result.empty

    def test_too_few_customers(self):
        orders = _make_orders()
        charges = _make_charges()
        # Only 3 customers — below threshold of 10
        result = rfm_segmentation(orders, charges)
        assert result.empty

    def test_enough_customers(self):
        # Create 12 customers
        emails = [f"user{i}@t.co" for i in range(12)]
        orders = pd.DataFrame({
            "id": [f"o{i}" for i in range(12)],
            "customer_email": emails,
            "customer_id": [str(i) for i in range(12)],
            "product_id": ["p1"] * 12,
            "product_name": ["Product A"] * 12,
            "total": [100.0 + i * 10 for i in range(12)],
            "created_at": ["2024-01-15T10:00:00Z"] * 12,
            "subscription_id": [""] * 12,
        })
        charges = pd.DataFrame({
            "id": [f"c{i}" for i in range(12)],
            "order_id": [f"o{i}" for i in range(12)],
            "subscription_id": [""] * 12,
            "customer_email": emails,
            "amount": [100.0 + i * 10 for i in range(12)],
            "status": [""] * 12,
            "created_at": ["2024-01-15T10:00:00Z"] * 12,
            "refund_amount": [0.0] * 12,
            "refund_date": [None] * 12,
        })
        result = rfm_segmentation(orders, charges)
        assert not result.empty
        assert "segment" in result.columns


class TestMultiProductBuyers:
    def test_empty_input(self):
        bs, pc = multi_product_buyers(pd.DataFrame())
        assert bs.empty
        assert pc.empty

    def test_single_product_customers(self):
        orders = _make_orders(
            customer_email=["a@t.co", "b@t.co", "c@t.co"],
            product_id=["p1", "p1", "p1"],
        )
        bs, pc = multi_product_buyers(orders)
        assert bs.empty  # No multi-product buyers

    def test_multi_product(self):
        orders = _make_orders(
            id=["o1", "o2", "o3"],
            customer_email=["a@t.co", "a@t.co", "b@t.co"],
            product_id=["p1", "p2", "p1"],
            product_name=["Product A", "Product B", "Product A"],
        )
        bs, pc = multi_product_buyers(orders)
        assert len(bs) == 1  # Only a@t.co has multiple products
        assert not pc.empty


class TestCustomerConcentration:
    def test_empty_input(self):
        result = customer_concentration(pd.DataFrame())
        assert result.empty

    def test_basic_concentration(self):
        charges = _make_charges(status=["", "", ""])
        result = customer_concentration(charges)
        assert not result.empty
        assert result.iloc[-1]["cumulative_pct"] == 100.0


class TestProductMrrTrend:
    def test_empty_input(self):
        result = product_mrr_trend(pd.DataFrame())
        assert result.empty

    def test_basic_trend(self):
        subs = _make_subscriptions()
        result = product_mrr_trend(subs)
        assert not result.empty
        assert "mrr" in result.columns


class TestProductAttachRate:
    def test_empty_input(self):
        result = product_attach_rate(pd.DataFrame())
        assert result.empty

    def test_insufficient_buyers(self):
        # Only 3 customers, need 5 per product
        orders = _make_orders()
        result = product_attach_rate(orders)
        assert result.empty

    def test_sufficient_buyers(self):
        # 6 customers for each of 2 products, 3 overlap
        emails = [f"u{i}@t.co" for i in range(9)]
        orders = pd.DataFrame({
            "id": [f"o{i}" for i in range(9)],
            "customer_email": emails,
            "customer_id": [str(i) for i in range(9)],
            "product_id": ["p1"] * 6 + ["p2"] * 3,
            "product_name": ["A"] * 6 + ["B"] * 3,
            "total": [100.0] * 9,
            "created_at": ["2024-01-15T10:00:00Z"] * 9,
            "subscription_id": [""] * 9,
        })
        # Add p2 orders for first 3 users (overlap)
        overlap = pd.DataFrame({
            "id": ["o10", "o11", "o12"],
            "customer_email": emails[:3],
            "customer_id": ["0", "1", "2"],
            "product_id": ["p2", "p2", "p2"],
            "product_name": ["B", "B", "B"],
            "total": [100.0] * 3,
            "created_at": ["2024-02-15T10:00:00Z"] * 3,
            "subscription_id": [""] * 3,
        })
        all_orders = pd.concat([orders, overlap], ignore_index=True)
        result = product_attach_rate(all_orders)
        assert not result.empty
        assert "attach_rate_pct" in result.columns


class TestNewVsRenewalRevenueMix:
    def test_empty_input(self):
        result = new_vs_renewal_revenue_mix(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        assert result.empty

    def test_basic_mix(self):
        charges = _make_charges(status=["", "", ""])
        orders = _make_orders()
        subs = _make_subscriptions()
        result = new_vs_renewal_revenue_mix(charges, orders, subs)
        assert not result.empty
        assert "new_revenue" in result.columns
        assert "renewal_revenue" in result.columns


# ------------------------------------------------------------------
# Regression tests for bug fixes
# ------------------------------------------------------------------


class TestRefundAnalysisFallback:
    """Fix 2: Full refunds with no explicit refund_amount should use charge amount."""

    def test_full_refund_no_refund_amount_uses_charge_amount(self):
        charges = pd.DataFrame({
            "id": ["c1", "c2"],
            "order_id": ["o1", "o2"],
            "subscription_id": ["", ""],
            "customer_email": ["a@t.co", "b@t.co"],
            "amount": [100.0, 200.0],
            "status": ["", "refunded"],
            "created_at": ["2024-01-15T10:00:00Z", "2024-02-15T10:00:00Z"],
            "refund_amount": [0.0, 0.0],  # API didn't provide refund_amount
            "refund_date": [None, "2024-02-20T10:00:00Z"],
        })
        orders = pd.DataFrame({
            "id": ["o1", "o2"],
            "customer_email": ["a@t.co", "b@t.co"],
            "customer_id": ["1", "2"],
            "product_id": ["p1", "p1"],
            "product_name": ["A", "A"],
            "total": [100.0, 200.0],
            "created_at": ["2024-01-15T10:00:00Z", "2024-02-15T10:00:00Z"],
            "subscription_id": ["", ""],
        })
        subs = pd.DataFrame(columns=["id", "product_id", "product_name"])
        bp, _, _ = refund_analysis(charges, orders, subs)
        # The refund_amount should fall back to charge amount ($200), not $0
        assert bp["refund_amount"].sum() == 200.0

    def test_partial_refund_without_explicit_amount_does_not_use_full_charge(self):
        charges = pd.DataFrame({
            "id": ["c1"],
            "order_id": ["o1"],
            "subscription_id": [""],
            "customer_email": ["a@t.co"],
            "amount": [100.0],
            "status": ["partially_refunded"],
            "created_at": ["2024-01-15T10:00:00Z"],
            "refund_amount": [0.0],
            "refund_date": ["2024-01-20T10:00:00Z"],
        })
        orders = _make_orders(
            id=["o1"], customer_email=["a@t.co"], customer_id=["1"],
            product_id=["p1"], product_name=["A"], total=[100.0],
            created_at=["2024-01-15T10:00:00Z"], subscription_id=[""],
        )
        subs = pd.DataFrame(columns=["id", "product_id", "product_name"])
        bp, _, _ = refund_analysis(charges, orders, subs)
        assert bp.iloc[0]["refund_amount"] == 0.0


class TestDailyRefundsDate:
    """Fix 3: daily_refunds should use refund_date and effective refund amount."""

    def test_uses_refund_date_not_created_at(self):
        charges = pd.DataFrame({
            "id": ["c1"],
            "order_id": ["o1"],
            "subscription_id": [""],
            "customer_email": ["a@t.co"],
            "amount": [100.0],
            "status": ["partially_refunded"],
            "created_at": ["2024-01-01T10:00:00Z"],  # charge in Jan
            "refund_amount": [25.0],
            "refund_date": ["2024-02-01T10:00:00Z"],  # refund in Feb
        })
        orders = _make_orders(id=["o1"], customer_email=["a@t.co"],
                              product_id=["p1"], product_name=["A"],
                              total=[100.0], created_at=["2024-01-01T10:00:00Z"],
                              subscription_id=[""], customer_id=["1"])
        subs = pd.DataFrame(columns=["id", "product_id", "product_name"])
        result = daily_refunds(charges, orders, subs)
        assert not result.empty
        # Should appear in Feb (refund_date), not Jan (created_at)
        assert str(result.iloc[0]["date"]).startswith("2024-02")
        # Amount should be the refund amount, not the full charge
        assert result.iloc[0]["refund_amount"] == 25.0


class TestRevenueForecastEdge:
    """Fix 4: forecast windows should use exact timedeltas, not floored days."""

    def test_billing_past_30_days_excluded_from_30d(self):
        # Create a sub that bills 30 days + 1 hour from now (past the 30d window)
        now = pd.Timestamp.now(tz="UTC")
        bill_past_30d = (now + pd.Timedelta(days=30, hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        subs = _make_subscriptions(
            id=["s1"],
            customer_email=["a@t.co"],
            product_id=["p1"],
            product_name=["A"],
            status=["active"],
            interval=["monthly"],
            price=[100.0],
            created_at=["2024-01-01T00:00:00Z"],
            canceled_at=[None],
            trial_days=[0],
            next_bill_date=[bill_past_30d],
            billing_cycle_count=[6],
        )
        result = revenue_forecast(subs)
        # 30d + 1h out should NOT be in 30-day window (strict <)
        if not result.empty:
            assert result.iloc[0]["forecast_30d"] == 0
            # But should be in 60-day window
            assert result.iloc[0]["forecast_60d"] == 100.0

    def test_billing_exactly_30_days_is_included_in_30d(self):
        now = pd.Timestamp.now(tz="UTC")
        bill_at_30d = (now + pd.Timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

        subs = _make_subscriptions(
            id=["s1"],
            customer_email=["a@t.co"],
            product_id=["p1"],
            product_name=["A"],
            status=["active"],
            interval=["monthly"],
            price=[100.0],
            created_at=["2024-01-01T00:00:00Z"],
            canceled_at=[None],
            trial_days=[0],
            next_bill_date=[bill_at_30d],
            billing_cycle_count=[6],
        )
        result = revenue_forecast(subs)
        assert not result.empty
        assert result.iloc[0]["forecast_30d"] == 100.0


class TestSubscriptionAgingZeroDay:
    """Fix 5: Same-day subscriptions should be in the 0-30d bucket."""

    def test_zero_age_falls_in_first_bucket(self):
        now = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
        subs = _make_subscriptions(
            id=["s1"],
            customer_email=["a@t.co"],
            product_id=["p1"],
            product_name=["A"],
            status=["active"],
            interval=["monthly"],
            price=[29.99],
            created_at=[now],
            canceled_at=[None],
            trial_days=[0],
            next_bill_date=[None],
            billing_cycle_count=[0],
        )
        result = subscription_aging(subs)
        assert not result.empty
        bucket_0_30 = result[result["age_bucket"] == "0-30d"]
        assert not bucket_0_30.empty
        assert bucket_0_30.iloc[0]["count"] == 1


# ------------------------------------------------------------------
# New analytics function tests
# ------------------------------------------------------------------


def _charges_df(rows):
    """Build a charges DataFrame from a list of dict rows with sane defaults."""
    defaults = {
        "id": "c?",
        "order_id": "o?",
        "subscription_id": "s1",
        "customer_email": "x@t.com",
        "amount": 0.0,
        "status": "",
        "created_at": "2026-01-15T10:00:00Z",
        "refund_amount": 0.0,
        "refund_date": None,
    }
    out = []
    for i, r in enumerate(rows):
        merged = {**defaults, **r}
        if merged["id"] == "c?":
            merged["id"] = f"c{i}"
        if merged["order_id"] == "o?":
            merged["order_id"] = f"o{i}"
        out.append(merged)
    return pd.DataFrame(out)


class TestNRR:
    def test_empty_charges(self):
        result = net_revenue_retention(pd.DataFrame(), pd.DataFrame())
        assert result.empty
        assert list(result.columns) == ["month", "nrr_pct", "starting_mrr", "ending_mrr"]

    def test_single_month_returns_empty(self):
        # Only one month of data — no prior period, so NRR cannot be computed
        charges = _charges_df([
            {"subscription_id": "sub1", "status": "charged", "amount": 100.0,
             "created_at": "2026-01-15T10:00:00Z", "customer_email": "a@test.com"},
            {"subscription_id": "sub1", "status": "charged", "amount": 50.0,
             "created_at": "2026-01-20T10:00:00Z", "customer_email": "b@test.com"},
        ])
        result = net_revenue_retention(charges, pd.DataFrame())
        assert result.empty

    def test_basic_retention(self):
        # Customer A: $100 in Jan + $80 in Feb; Customer B: $50 in Jan only (churned)
        # starting = 150, ending = 80 (only A in both months), nrr = 80/150*100 = 53.33%
        charges = _make_charges(
            subscription_id=["s1", "s2", "s1"],
            status=["charged", "charged", "charged"],
            amount=[100.0, 50.0, 80.0],
            refund_amount=[0.0, 0.0, 0.0],
            created_at=[
                "2026-01-15T10:00:00Z",
                "2026-01-20T10:00:00Z",
                "2026-02-15T10:00:00Z",
            ],
            customer_email=["a@test.com", "b@test.com", "a@test.com"],
        )
        result = net_revenue_retention(charges, pd.DataFrame())
        assert not result.empty
        assert len(result) == 1
        row = result.iloc[0]
        assert row["month"] == "2026-02"
        assert abs(row["starting_mrr"] - 150.0) < 0.01
        assert abs(row["ending_mrr"] - 80.0) < 0.01
        assert abs(row["nrr_pct"] - 53.33) < 0.1

    def test_excludes_new_customers_from_ending(self):
        # Customer C only appears in Feb — should NOT inflate ending_mrr
        charges = _make_charges(
            subscription_id=["s1", "s1", "s3"],
            status=["charged", "charged", "charged"],
            amount=[100.0, 100.0, 200.0],
            refund_amount=[0.0, 0.0, 0.0],
            created_at=[
                "2026-01-15T10:00:00Z",
                "2026-02-15T10:00:00Z",
                "2026-02-20T10:00:00Z",
            ],
            customer_email=["a@test.com", "a@test.com", "c@test.com"],
        )
        result = net_revenue_retention(charges, pd.DataFrame())
        assert not result.empty
        row = result.iloc[0]
        # ending should only count customer A ($100), not C ($200)
        assert abs(row["ending_mrr"] - 100.0) < 0.01
        assert abs(row["nrr_pct"] - 100.0) < 0.1

    def test_zero_prior_cohort_returns_nan(self):
        # Prior month has only refunded charges (filtered out by _is_collected_charge)
        # → only one month of collected charges remains → returns empty
        charges = _charges_df([
            {"subscription_id": "s1", "status": "refunded", "amount": 100.0,
             "refund_amount": 100.0, "created_at": "2026-01-15T10:00:00Z",
             "customer_email": "a@test.com"},
            {"subscription_id": "s1", "status": "charged", "amount": 80.0,
             "refund_amount": 0.0, "created_at": "2026-02-15T10:00:00Z",
             "customer_email": "a@test.com"},
        ])
        result = net_revenue_retention(charges, pd.DataFrame())
        if not result.empty:
            assert pd.isna(result.iloc[0]["nrr_pct"])


class TestMRRWaterfallExpansion:
    def test_columns_present(self):
        result = mrr_waterfall(_make_subscriptions())
        expected_cols = {
            "month", "new_mrr", "expansion_mrr", "contraction_mrr",
            "churned_mrr", "reactivation_mrr", "net_mrr", "quick_ratio",
        }
        assert expected_cols.issubset(set(result.columns))

    def test_contraction_always_zero(self):
        result = mrr_waterfall(_make_subscriptions())
        assert (result["contraction_mrr"] == 0.0).all()

    def test_net_mrr_invariant(self):
        result = mrr_waterfall(_make_subscriptions())
        computed = (
            result["new_mrr"] + result["expansion_mrr"] + result["reactivation_mrr"]
            - result["churned_mrr"] - result["contraction_mrr"]
        ).round(2)
        assert (computed == result["net_mrr"].round(2)).all()

    def test_quick_ratio_nan_when_no_churn(self):
        # A subscription with no cancellations → churned_mrr = 0 → quick_ratio NaN
        subs = pd.DataFrame([{
            "id": "s1", "customer_email": "a@test.com", "product_id": "p1",
            "product_name": "Prod A", "status": "active", "interval": "monthly",
            "price": 50.0, "created_at": pd.Timestamp("2026-01-15", tz="UTC"),
            "canceled_at": pd.NaT, "trial_days": 0, "next_bill_date": pd.NaT,
            "billing_cycle_count": 2,
        }])
        result = mrr_waterfall(subs)
        assert not result.empty
        # All months should have NaN quick_ratio (no churn ever)
        assert result["quick_ratio"].isna().all()

    def test_expansion_classification(self):
        # Customer has Product A sub active; then creates Product B sub same month
        # Product B should go to expansion_mrr, not new_mrr
        subs = pd.DataFrame([
            {
                "id": "s1", "customer_email": "a@test.com", "product_id": "pA",
                "product_name": "Prod A", "status": "active", "interval": "monthly",
                "price": 40.0, "created_at": pd.Timestamp("2026-01-10", tz="UTC"),
                "canceled_at": pd.NaT, "trial_days": 0, "next_bill_date": pd.NaT,
                "billing_cycle_count": 3,
            },
            {
                "id": "s2", "customer_email": "a@test.com", "product_id": "pB",
                "product_name": "Prod B", "status": "active", "interval": "monthly",
                "price": 30.0, "created_at": pd.Timestamp("2026-02-05", tz="UTC"),
                "canceled_at": pd.NaT, "trial_days": 0, "next_bill_date": pd.NaT,
                "billing_cycle_count": 1,
            },
        ])
        result = mrr_waterfall(subs)
        # Feb row: expansion_mrr should be 30, new_mrr for pB contribution = 0
        feb = result[result["month"] == "2026-02"]
        assert not feb.empty
        assert feb.iloc[0]["expansion_mrr"] == pytest.approx(30.0, abs=0.01)
        # new_mrr in Feb should be 0 (pB is expansion, no truly new customers)
        assert feb.iloc[0]["new_mrr"] == pytest.approx(0.0, abs=0.01)


class TestArpuByProduct:
    def test_empty(self):
        result = arpu_by_product(pd.DataFrame())
        assert result.empty
        assert "monthly_arpu" in result.columns

    def test_no_active_subs(self):
        subs = _make_subscriptions()
        subs["status"] = "canceled"
        result = arpu_by_product(subs)
        assert result.empty

    def test_basic_monthly(self):
        # 3 active subs at $30/mo, 2 unique customers (a@t.com appears twice)
        # revenues = 90, unique customers = 2, monthly_arpu = 90/2 = 45
        subs = pd.DataFrame([
            {"id": "s1", "customer_email": "a@t.com", "product_id": "p1",
             "product_name": "Prod X", "status": "active", "interval": "monthly",
             "price": 30.0, "created_at": pd.Timestamp("2026-01-01", tz="UTC"),
             "canceled_at": pd.NaT, "trial_days": 0, "next_bill_date": pd.NaT,
             "billing_cycle_count": 1},
            {"id": "s2", "customer_email": "b@t.com", "product_id": "p1",
             "product_name": "Prod X", "status": "active", "interval": "monthly",
             "price": 30.0, "created_at": pd.Timestamp("2026-01-01", tz="UTC"),
             "canceled_at": pd.NaT, "trial_days": 0, "next_bill_date": pd.NaT,
             "billing_cycle_count": 1},
            {"id": "s3", "customer_email": "a@t.com", "product_id": "p1",
             "product_name": "Prod X", "status": "active", "interval": "monthly",
             "price": 30.0, "created_at": pd.Timestamp("2026-02-01", tz="UTC"),
             "canceled_at": pd.NaT, "trial_days": 0, "next_bill_date": pd.NaT,
             "billing_cycle_count": 1},
        ])
        result = arpu_by_product(subs)
        assert not result.empty
        row = result[result["product_id"] == "p1"].iloc[0]
        assert row["active_subscribers"] == 2
        assert row["monthly_arpu"] == pytest.approx(45.0, abs=0.01)
        assert row["annual_arpu"] == pytest.approx(540.0, abs=0.01)

    def test_yearly_normalized(self):
        # Yearly $1200 sub → $100/mo contribution
        subs = pd.DataFrame([{
            "id": "s1", "customer_email": "a@t.com", "product_id": "p1",
            "product_name": "Prod Y", "status": "active", "interval": "yearly",
            "price": 1200.0, "created_at": pd.Timestamp("2026-01-01", tz="UTC"),
            "canceled_at": pd.NaT, "trial_days": 0, "next_bill_date": pd.NaT,
            "billing_cycle_count": 1,
        }])
        result = arpu_by_product(subs)
        assert not result.empty
        assert result.iloc[0]["monthly_arpu"] == pytest.approx(100.0, abs=0.01)


class TestFailedPayments:
    def test_empty_charges(self):
        by_month, by_product = failed_payment_analysis(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        assert by_month.empty
        assert by_product.empty
        assert "failed_count" in by_month.columns
        assert "failed_count" in by_product.columns

    def test_no_failed_charges(self):
        charges = _charges_df([
            {"status": "charged", "amount": 100.0, "created_at": "2026-01-15T10:00:00Z"},
            {"status": "charged", "amount": 50.0, "created_at": "2026-01-20T10:00:00Z"},
        ])
        by_month, _ = failed_payment_analysis(charges, pd.DataFrame(), pd.DataFrame())
        assert not by_month.empty
        assert by_month["failed_count"].sum() == 0
        assert by_month["failure_rate_pct"].sum() == 0.0

    def test_failed_classification(self):
        # "declined" = failed; NULL = successful (not failed)
        charges = _make_charges(
            status=["declined", None, "charged"],
            amount=[99.0, 49.0, 79.0],
            created_at=[
                "2026-01-10T10:00:00Z",
                "2026-01-11T10:00:00Z",
                "2026-01-12T10:00:00Z",
            ],
        )
        by_month, _ = failed_payment_analysis(charges, pd.DataFrame(), pd.DataFrame())
        assert not by_month.empty
        assert by_month["failed_count"].sum() == 1
        assert abs(by_month["failed_amount"].sum() - 99.0) < 0.01

    def test_amount_none_no_crash(self):
        # Failed charge with None amount should not crash and contribute 0 to failed_amount
        charges = _charges_df([
            {"status": "failed", "amount": None, "created_at": "2026-01-10T10:00:00Z"},
        ])
        by_month, _ = failed_payment_analysis(charges, pd.DataFrame(), pd.DataFrame())
        assert not by_month.empty
        assert by_month["failed_count"].sum() == 1
        assert by_month["failed_amount"].sum() == 0.0


class TestTrialDaysToConvert:
    def test_empty(self):
        result = trial_days_to_convert(pd.DataFrame())
        assert result.empty
        assert "outcome" in result.columns

    def test_no_trial_column(self):
        subs = _make_subscriptions()
        if "trial_days" in subs.columns:
            subs = subs.drop(columns=["trial_days"])
        result = trial_days_to_convert(subs)
        assert result.empty

    def test_zero_trial_days_excluded(self):
        subs = _make_subscriptions()
        subs["trial_days"] = 0
        result = trial_days_to_convert(subs)
        assert result.empty

    def test_basic_distribution(self):
        subs = pd.DataFrame([
            # 3 converted at 14 days
            {"id": "s1", "customer_email": "a@t.com", "product_id": "p1",
             "product_name": "Prod A", "status": "active", "interval": "monthly",
             "price": 30.0, "trial_days": 14, "billing_cycle_count": 2,
             "created_at": pd.Timestamp("2026-01-01", tz="UTC"),
             "canceled_at": pd.NaT, "next_bill_date": pd.NaT},
            {"id": "s2", "customer_email": "b@t.com", "product_id": "p1",
             "product_name": "Prod A", "status": "active", "interval": "monthly",
             "price": 30.0, "trial_days": 14, "billing_cycle_count": 1,
             "created_at": pd.Timestamp("2026-01-01", tz="UTC"),
             "canceled_at": pd.NaT, "next_bill_date": pd.NaT},
            {"id": "s3", "customer_email": "c@t.com", "product_id": "p1",
             "product_name": "Prod A", "status": "active", "interval": "monthly",
             "price": 30.0, "trial_days": 14, "billing_cycle_count": 3,
             "created_at": pd.Timestamp("2026-01-01", tz="UTC"),
             "canceled_at": pd.NaT, "next_bill_date": pd.NaT},
            # 2 dropped at 7 days
            {"id": "s4", "customer_email": "d@t.com", "product_id": "p1",
             "product_name": "Prod A", "status": "canceled", "interval": "monthly",
             "price": 30.0, "trial_days": 7, "billing_cycle_count": 0,
             "created_at": pd.Timestamp("2026-01-01", tz="UTC"),
             "canceled_at": pd.Timestamp("2026-01-08", tz="UTC"),
             "next_bill_date": pd.NaT},
            {"id": "s5", "customer_email": "e@t.com", "product_id": "p1",
             "product_name": "Prod A", "status": "cancelled", "interval": "monthly",
             "price": 30.0, "trial_days": 7, "billing_cycle_count": 0,
             "created_at": pd.Timestamp("2026-01-01", tz="UTC"),
             "canceled_at": pd.Timestamp("2026-01-08", tz="UTC"),
             "next_bill_date": pd.NaT},
        ])
        result = trial_days_to_convert(subs)
        assert not result.empty
        assert set(result["outcome"].unique()) == {"converted", "dropped"}
        converted_row = result[result["outcome"] == "converted"]
        assert not converted_row.empty
        assert converted_row.iloc[0]["customer_count"] == 3
        dropped_row = result[result["outcome"] == "dropped"]
        assert not dropped_row.empty
        assert dropped_row.iloc[0]["customer_count"] == 2
