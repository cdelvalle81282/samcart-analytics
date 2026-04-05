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
            "daily_metrics", "refund_analysis", "cohort_performance",
            "product_ltv", "subscription_health", "customer_segments",
            "product_deep_dive", "revenue_forecast", "mrr_waterfall",
            "upcoming_renewals", "vip_customers",
        }
        assert expected == set(REPORT_CATALOG.keys())

    def test_generate_report_unknown_type_raises(self):
        with pytest.raises(KeyError):
            generate_report("nonexistent", None)
