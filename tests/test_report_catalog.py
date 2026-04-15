"""Tests for report_catalog.py — verify every catalog entry has a valid generator."""

import pytest

from report_catalog import REPORT_CATALOG, generate_report


class TestReportCatalog:
    def test_all_entries_have_required_keys(self):
        for key, entry in REPORT_CATALOG.items():
            assert "name" in entry, f"Missing 'name' for {key}"
            assert "generator" in entry, f"Missing 'generator' for {key}"
            assert callable(entry["generator"]), f"Generator not callable for {key}"

    def test_catalog_has_expected_report_types(self):
        expected = {
            # Daily Metrics
            "daily_metrics", "daily_metrics_new_customers", "daily_metrics_new_sales",
            "daily_metrics_refunds", "daily_metrics_renewals", "daily_metrics_entry_ltv",
            # Subscription Cohorts
            "cohort_activity", "cohort_renewal_rates", "cohort_stick_rates", "cohort_heatmap",
            # Refund Analysis
            "refund_analysis", "refund_time_to_refund", "refund_monthly_trend",
            # Product LTV
            "product_ltv",
            # Subscription Health
            "subscription_health", "subscription_health_churn_trend",
            "subscription_health_trial", "subscription_health_aging",
            # Customer Segments
            "customer_segments", "customer_segments_multi_product", "customer_segments_concentration",
            # Product Deep Dive
            "product_deep_dive", "product_deep_dive_attach", "product_deep_dive_revenue_mix",
            # Revenue Forecasting
            "mrr_waterfall", "revenue_forecast",
            # Other
            "upcoming_renewals", "vip_customers",
        }
        assert expected == set(REPORT_CATALOG.keys())

    def test_catalog_count(self):
        assert len(REPORT_CATALOG) == 28

    def test_generate_report_unknown_type_raises(self):
        with pytest.raises(KeyError):
            generate_report("nonexistent", None)
