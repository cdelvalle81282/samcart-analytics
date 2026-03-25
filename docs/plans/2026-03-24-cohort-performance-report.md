# Cohort Performance Report — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the subscription-status-based cohort page with a charge-based cohort performance report that tracks actual billing cycles, revenue, refunds, renewal rates, and stick rates — matching the manually-built spreadsheet methodology.

**Architecture:** New `build_cohort_performance()` function in `analytics.py` ranks charges per subscription by date, groups into billing-cycle periods, and computes 3 output tables (activity summary, renewal rates, stick/refund rates). The page (`pages/2_Subscription_Cohorts.py`) is replaced with new UI rendering these tables plus a retention heatmap. Supports weekly/monthly/yearly subscriptions with period labels matching their billing interval.

**Tech Stack:** Python, pandas, Streamlit, Plotly

---

### Task 1: Add `build_cohort_performance()` to analytics.py — tests first

**Files:**
- Create: `tests/test_cohort_performance.py`
- Modify: `analytics.py` (after line 230, after `build_cohort_retention`)

**Step 1: Write the failing tests**

Create `tests/test_cohort_performance.py`:

```python
"""Tests for charge-based cohort performance report."""

import pandas as pd
import pytest

from analytics import build_cohort_performance


# ------------------------------------------------------------------
# Shared test helpers
# ------------------------------------------------------------------

def _make_charges(**overrides):
    """5 charges across 2 subs: sub s1 has 3 charges (initial + 2 renewals),
    sub s2 has 2 charges (initial + 1 renewal). One refund on s2's renewal."""
    defaults = {
        "id": ["c1", "c2", "c3", "c4", "c5"],
        "order_id": ["o1", "o2", "o3", "o4", "o5"],
        "subscription_id": ["s1", "s1", "s1", "s2", "s2"],
        "customer_email": ["a@t.co", "a@t.co", "a@t.co", "b@t.co", "b@t.co"],
        "amount": [99.0, 99.0, 99.0, 99.0, 99.0],
        "status": ["", "", "", "", "refunded"],
        "created_at": [
            "2024-01-01T10:00:00Z",  # s1 initial
            "2024-01-08T10:00:00Z",  # s1 renewal 1
            "2024-01-15T10:00:00Z",  # s1 renewal 2
            "2024-01-01T10:00:00Z",  # s2 initial
            "2024-01-08T10:00:00Z",  # s2 renewal (refunded)
        ],
        "refund_amount": [0.0, 0.0, 0.0, 0.0, 99.0],
        "refund_date": [None, None, None, None, "2024-01-10T10:00:00Z"],
    }
    defaults.update(overrides)
    return pd.DataFrame(defaults)


def _make_orders(**overrides):
    defaults = {
        "id": ["o1", "o2", "o3", "o4", "o5"],
        "customer_email": ["a@t.co", "a@t.co", "a@t.co", "b@t.co", "b@t.co"],
        "customer_id": ["1", "1", "1", "2", "2"],
        "product_id": ["p1", "p1", "p1", "p1", "p1"],
        "product_name": ["Widget", "Widget", "Widget", "Widget", "Widget"],
        "total": [99.0, 99.0, 99.0, 99.0, 99.0],
        "created_at": [
            "2024-01-01T10:00:00Z",
            "2024-01-08T10:00:00Z",
            "2024-01-15T10:00:00Z",
            "2024-01-01T10:00:00Z",
            "2024-01-08T10:00:00Z",
        ],
        "subscription_id": ["s1", "s1", "s1", "s2", "s2"],
    }
    defaults.update(overrides)
    return pd.DataFrame(defaults)


def _make_subscriptions(**overrides):
    defaults = {
        "id": ["s1", "s2"],
        "customer_email": ["a@t.co", "b@t.co"],
        "product_id": ["p1", "p1"],
        "product_name": ["Widget", "Widget"],
        "status": ["active", "canceled"],
        "interval": ["weekly", "weekly"],
        "price": [99.0, 99.0],
        "created_at": ["2024-01-01T10:00:00Z", "2024-01-01T10:00:00Z"],
        "canceled_at": [None, "2024-01-10T10:00:00Z"],
        "trial_days": [0, 0],
        "next_bill_date": [None, None],
        "billing_cycle_count": [3, 1],
    }
    defaults.update(overrides)
    return pd.DataFrame(defaults)


class TestBuildCohortPerformance:
    """Test the main build_cohort_performance function."""

    def test_returns_three_dataframes(self):
        charges = _make_charges()
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, renewal_rates, stick_rates = build_cohort_performance(
            charges, orders, subs
        )
        assert isinstance(activity, pd.DataFrame)
        assert isinstance(renewal_rates, pd.DataFrame)
        assert isinstance(stick_rates, pd.DataFrame)

    def test_activity_summary_columns(self):
        activity, _, _ = build_cohort_performance(
            _make_charges(), _make_orders(), _make_subscriptions()
        )
        expected_cols = {
            "period", "active_subscribers", "renewals", "initial_charges",
            "total_charged", "cumulative_refunds", "refunds_this_period",
            "period_revenue", "cumulative_revenue",
        }
        assert expected_cols.issubset(set(activity.columns))

    def test_activity_summary_period_0(self):
        """Period 0 should have 2 active subs (both s1 and s2 initial charges)."""
        activity, _, _ = build_cohort_performance(
            _make_charges(), _make_orders(), _make_subscriptions()
        )
        p0 = activity[activity["period"] == 0].iloc[0]
        assert p0["active_subscribers"] == 2
        assert p0["initial_charges"] == 2
        assert p0["renewals"] == 0
        assert p0["period_revenue"] == 198.0  # 99 * 2

    def test_activity_summary_period_1(self):
        """Period 1: s1 renews (successful), s2 charge is refunded.
        Only s1 counted as active. Refund tracked."""
        activity, _, _ = build_cohort_performance(
            _make_charges(), _make_orders(), _make_subscriptions()
        )
        p1 = activity[activity["period"] == 1].iloc[0]
        assert p1["active_subscribers"] == 1  # only s1
        assert p1["renewals"] == 1
        assert p1["refunds_this_period"] == 1

    def test_activity_summary_period_2(self):
        """Period 2: only s1 renews."""
        activity, _, _ = build_cohort_performance(
            _make_charges(), _make_orders(), _make_subscriptions()
        )
        p2 = activity[activity["period"] == 2].iloc[0]
        assert p2["active_subscribers"] == 1
        assert p2["renewals"] == 1
        assert p2["period_revenue"] == 99.0

    def test_renewal_rate_columns(self):
        _, renewal_rates, _ = build_cohort_performance(
            _make_charges(), _make_orders(), _make_subscriptions()
        )
        expected_cols = {
            "period", "subscribers_start", "subscribers_end",
            "dropped_off", "renewal_rate", "stick_rate",
        }
        assert expected_cols.issubset(set(renewal_rates.columns))

    def test_renewal_rate_period_1(self):
        """Week 1 -> Week 2: start=2, end=1, renewal_rate=50%."""
        _, renewal_rates, _ = build_cohort_performance(
            _make_charges(), _make_orders(), _make_subscriptions()
        )
        r1 = renewal_rates[renewal_rates["period"] == 1].iloc[0]
        assert r1["subscribers_start"] == 2
        assert r1["subscribers_end"] == 1
        assert r1["dropped_off"] == 1
        assert abs(r1["renewal_rate"] - 50.0) < 0.1

    def test_stick_rate_columns(self):
        _, _, stick_rates = build_cohort_performance(
            _make_charges(), _make_orders(), _make_subscriptions()
        )
        expected_cols = {
            "period", "original_cohort", "still_active", "dropped_cumulative",
            "stick_rate", "cumulative_refunds", "refund_rate",
            "churn_refund_rate",
        }
        assert expected_cols.issubset(set(stick_rates.columns))

    def test_stick_rate_values(self):
        _, _, stick_rates = build_cohort_performance(
            _make_charges(), _make_orders(), _make_subscriptions()
        )
        # Period 0: all active
        s0 = stick_rates[stick_rates["period"] == 0].iloc[0]
        assert s0["original_cohort"] == 2
        assert s0["still_active"] == 2
        assert abs(s0["stick_rate"] - 100.0) < 0.1

        # Period 2: only s1
        s2 = stick_rates[stick_rates["period"] == 2].iloc[0]
        assert s2["still_active"] == 1
        assert abs(s2["stick_rate"] - 50.0) < 0.1

    def test_empty_charges(self):
        empty = pd.DataFrame(columns=[
            "id", "order_id", "subscription_id", "customer_email",
            "amount", "status", "created_at", "refund_amount", "refund_date",
        ])
        orders = _make_orders()
        subs = _make_subscriptions()
        activity, renewal_rates, stick_rates = build_cohort_performance(
            empty, orders, subs
        )
        assert activity.empty
        assert renewal_rates.empty
        assert stick_rates.empty

    def test_no_subscription_charges_excluded(self):
        """Charges without subscription_id should be excluded."""
        charges = _make_charges(subscription_id=["", "", "", "", ""])
        activity, _, _ = build_cohort_performance(
            charges, _make_orders(), _make_subscriptions()
        )
        assert activity.empty

    def test_monthly_interval_label(self):
        """Interval label should come through for display purposes."""
        subs = _make_subscriptions(interval=["monthly", "monthly"])
        activity, _, _ = build_cohort_performance(
            _make_charges(), _make_orders(), subs
        )
        # Function should still work — interval is metadata, periods are billing cycles
        assert not activity.empty

    def test_cumulative_revenue(self):
        activity, _, _ = build_cohort_performance(
            _make_charges(), _make_orders(), _make_subscriptions()
        )
        # Cumulative revenue should increase monotonically
        cum_rev = activity["cumulative_revenue"].tolist()
        for i in range(1, len(cum_rev)):
            assert cum_rev[i] >= cum_rev[i - 1]
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cohort_performance.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_cohort_performance' from 'analytics'`

**Step 3: Implement `build_cohort_performance()` in `analytics.py`**

Add after `build_cohort_retention()` (after line 230). The function:

```python
def build_cohort_performance(
    charges_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
    product_filter: str | None = None,
    interval_filter: str | None = None,
    combined_cohort: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Charge-based cohort performance report.

    Tracks actual billing cycles: ranks charges per subscription by date,
    assigns period 0 (initial) through period N (renewals), then computes
    activity summary, renewal rates, and stick/refund rates.

    Parameters
    ----------
    charges_df : charges table
    orders_df : orders table (for product enrichment)
    subscriptions_df : subscriptions table (for interval, product info)
    product_filter : optional product_name to filter to
    interval_filter : optional interval to filter to
    combined_cohort : if True, all subs in one cohort; if False, group by
                      the period of initial charge

    Returns
    -------
    (activity_summary, renewal_rates, stick_rates) — three DataFrames.
    All empty if no qualifying data.
    """
    empty_activity = pd.DataFrame(columns=[
        "period", "active_subscribers", "renewals", "initial_charges",
        "total_charged", "cumulative_refunds", "refunds_this_period",
        "period_revenue", "cumulative_revenue",
    ])
    empty_renewal = pd.DataFrame(columns=[
        "period", "subscribers_start", "subscribers_end",
        "dropped_off", "renewal_rate", "stick_rate",
    ])
    empty_stick = pd.DataFrame(columns=[
        "period", "original_cohort", "still_active", "dropped_cumulative",
        "stick_rate", "cumulative_refunds", "refund_rate",
        "churn_refund_rate",
    ])
    empty = (empty_activity, empty_renewal, empty_stick)

    if charges_df.empty:
        return empty

    # --- Step 1: Filter to subscription-linked charges ---
    df = charges_df.copy()
    has_sub = (
        df["subscription_id"].notna()
        & (df["subscription_id"] != "")
        & (df["subscription_id"] != "nan")
    )
    df = df[has_sub]
    if df.empty:
        return empty

    # --- Step 2: Enrich with product info ---
    df = enrich_charges_with_product(df, orders_df, subscriptions_df)

    # --- Step 3: Join interval from subscriptions ---
    if not subscriptions_df.empty and "id" in subscriptions_df.columns:
        sub_info = (
            subscriptions_df[["id", "interval"]]
            .drop_duplicates("id", keep="last")
            .rename(columns={"id": "subscription_id"})
        )
        sub_info["subscription_id"] = sub_info["subscription_id"].astype(str)
        df["subscription_id"] = df["subscription_id"].astype(str)
        df = df.merge(sub_info, on="subscription_id", how="left", suffixes=("", "_sub"))
        # If interval came from merge, keep it
        if "interval_sub" in df.columns:
            df["interval"] = df.get("interval", df["interval_sub"]).fillna(df["interval_sub"])
            df = df.drop(columns=["interval_sub"])

    # --- Step 4: Apply filters ---
    if product_filter and "product_name" in df.columns:
        df = df[df["product_name"] == product_filter]
    if interval_filter and "interval" in df.columns:
        df = df[df["interval"] == interval_filter]
    if df.empty:
        return empty

    # --- Step 5: Classify charges ---
    df["is_successful"] = _is_successful_charge(df["status"])
    df["is_refund"] = _is_refund_charge(df["status"])

    # --- Step 6: Rank charges per subscription (billing cycle period) ---
    df["_charge_dt"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
    df = df.dropna(subset=["_charge_dt"])
    df["period"] = (
        df.groupby("subscription_id")["_charge_dt"]
        .rank(method="first")
        .astype(int) - 1  # 0-indexed: period 0 = initial
    )

    # --- Step 7: Revenue ---
    df["net_amount"] = _net_charge_amount(df)

    # --- Step 8: Compute per-period aggregates ---
    max_period = int(df["period"].max())

    # Active = had a successful charge in this period
    # Refund = had a refund charge in this period
    periods = list(range(max_period + 1))

    activity_rows = []
    cumulative_refunds = 0
    cumulative_revenue = 0.0

    # Count unique subscriptions per period
    for p in periods:
        p_df = df[df["period"] == p]

        successful_subs = p_df[p_df["is_successful"]]["subscription_id"].nunique()
        refund_count = p_df[p_df["is_refund"]]["subscription_id"].nunique()
        cumulative_refunds += refund_count

        period_revenue = p_df[p_df["is_successful"]]["net_amount"].sum()
        cumulative_revenue += period_revenue

        initial = successful_subs if p == 0 else 0
        renewals = successful_subs if p > 0 else 0

        activity_rows.append({
            "period": p,
            "active_subscribers": successful_subs,
            "renewals": renewals,
            "initial_charges": initial,
            "total_charged": successful_subs + refund_count,
            "cumulative_refunds": cumulative_refunds,
            "refunds_this_period": refund_count,
            "period_revenue": round(period_revenue, 2),
            "cumulative_revenue": round(cumulative_revenue, 2),
        })

    activity = pd.DataFrame(activity_rows)

    # --- Step 9: Renewal rates ---
    cohort_size = activity.iloc[0]["active_subscribers"] if not activity.empty else 0
    renewal_rows = []
    for i, p in enumerate(periods):
        if i == 0:
            continue  # No renewal rate for period 0
        prev_active = activity.iloc[i - 1]["active_subscribers"]
        curr_active = activity.iloc[i]["active_subscribers"]
        dropped = prev_active - curr_active
        rate = (curr_active / prev_active * 100) if prev_active > 0 else 0.0
        stick = (curr_active / cohort_size * 100) if cohort_size > 0 else 0.0

        renewal_rows.append({
            "period": p,
            "subscribers_start": int(prev_active),
            "subscribers_end": int(curr_active),
            "dropped_off": int(dropped),
            "renewal_rate": round(rate, 1),
            "stick_rate": round(stick, 1),
        })

    renewal_rates = pd.DataFrame(renewal_rows)

    # Add "notes" column — flag largest drop
    if not renewal_rates.empty:
        max_drop_idx = renewal_rates["dropped_off"].idxmax()
        renewal_rates["notes"] = ""
        renewal_rates.loc[max_drop_idx, "notes"] = "Largest period-over-period drop"

    # --- Step 10: Stick / refund rates ---
    stick_rows = []
    cum_refunds_running = 0
    for i, p in enumerate(periods):
        curr_active = int(activity.iloc[i]["active_subscribers"])
        refunds_this = int(activity.iloc[i]["refunds_this_period"])
        cum_refunds_running += refunds_this
        dropped_cum = int(cohort_size - curr_active)
        stick = (curr_active / cohort_size * 100) if cohort_size > 0 else 0.0
        refund_rate = (cum_refunds_running / cohort_size * 100) if cohort_size > 0 else 0.0
        churn_refund = (dropped_cum + cum_refunds_running) / cohort_size * 100 if cohort_size > 0 else 0.0

        stick_rows.append({
            "period": p,
            "original_cohort": int(cohort_size),
            "still_active": curr_active,
            "dropped_cumulative": dropped_cum,
            "stick_rate": round(stick, 1),
            "cumulative_refunds": cum_refunds_running,
            "refund_rate": round(refund_rate, 1),
            "churn_refund_rate": round(churn_refund, 1),
        })

    stick_rates = pd.DataFrame(stick_rows)

    return activity, renewal_rates, stick_rates
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cohort_performance.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 6: Lint**

Run: `ruff check analytics.py tests/test_cohort_performance.py --fix`
Expected: Clean

**Step 7: Commit**

```bash
git add analytics.py tests/test_cohort_performance.py
git commit -m "feat: add charge-based build_cohort_performance() with tests"
```

---

### Task 2: Add `build_cohort_heatmap()` helper for multi-cohort view

**Files:**
- Modify: `analytics.py` (after `build_cohort_performance`)
- Modify: `tests/test_cohort_performance.py`

**Step 1: Write the failing test**

Add to `tests/test_cohort_performance.py`:

```python
from analytics import build_cohort_heatmap


class TestBuildCohortHeatmap:
    def test_returns_dataframe(self):
        result = build_cohort_heatmap(
            _make_charges(), _make_orders(), _make_subscriptions()
        )
        assert isinstance(result, pd.DataFrame)

    def test_index_is_cohort_label(self):
        result = build_cohort_heatmap(
            _make_charges(), _make_orders(), _make_subscriptions()
        )
        assert result.index.name == "cohort"

    def test_columns_are_periods(self):
        result = build_cohort_heatmap(
            _make_charges(), _make_orders(), _make_subscriptions()
        )
        # Should have numeric period columns + cohort_size
        assert "cohort_size" in result.columns
        period_cols = [c for c in result.columns if c != "cohort_size"]
        assert all(isinstance(c, int) for c in period_cols)

    def test_empty_charges(self):
        empty = pd.DataFrame(columns=[
            "id", "order_id", "subscription_id", "customer_email",
            "amount", "status", "created_at", "refund_amount", "refund_date",
        ])
        result = build_cohort_heatmap(empty, _make_orders(), _make_subscriptions())
        assert result.empty
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cohort_performance.py::TestBuildCohortHeatmap -v`
Expected: FAIL — ImportError

**Step 3: Implement `build_cohort_heatmap()`**

Add after `build_cohort_performance()` in `analytics.py`:

```python
def build_cohort_heatmap(
    charges_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    subscriptions_df: pd.DataFrame,
    product_filter: str | None = None,
    interval_filter: str | None = None,
) -> pd.DataFrame:
    """
    Charge-based retention heatmap for per-period cohorts.

    Groups subscriptions by the month of their initial charge, then for each
    cohort tracks the % that had a successful charge at each billing-cycle period.

    Returns pivot table: rows=cohort month, cols=period number, values=retention %.
    Also includes a 'cohort_size' column.
    """
    if charges_df.empty:
        return pd.DataFrame()

    df = charges_df.copy()
    has_sub = (
        df["subscription_id"].notna()
        & (df["subscription_id"] != "")
        & (df["subscription_id"] != "nan")
    )
    df = df[has_sub]
    if df.empty:
        return pd.DataFrame()

    df = enrich_charges_with_product(df, orders_df, subscriptions_df)

    # Join interval
    if not subscriptions_df.empty and "id" in subscriptions_df.columns:
        sub_info = (
            subscriptions_df[["id", "interval"]]
            .drop_duplicates("id", keep="last")
            .rename(columns={"id": "subscription_id"})
        )
        sub_info["subscription_id"] = sub_info["subscription_id"].astype(str)
        df["subscription_id"] = df["subscription_id"].astype(str)
        df = df.merge(sub_info, on="subscription_id", how="left", suffixes=("", "_sub"))
        if "interval_sub" in df.columns:
            df["interval"] = df.get("interval", df["interval_sub"]).fillna(df["interval_sub"])
            df = df.drop(columns=["interval_sub"])

    if product_filter and "product_name" in df.columns:
        df = df[df["product_name"] == product_filter]
    if interval_filter and "interval" in df.columns:
        df = df[df["interval"] == interval_filter]
    if df.empty:
        return pd.DataFrame()

    df["is_successful"] = _is_successful_charge(df["status"])
    df["_charge_dt"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
    df = df.dropna(subset=["_charge_dt"])

    df["period"] = (
        df.groupby("subscription_id")["_charge_dt"]
        .rank(method="first")
        .astype(int) - 1
    )

    # Determine cohort for each subscription: month of their period-0 charge
    initial = df[df["period"] == 0][["subscription_id", "_charge_dt"]].copy()
    initial["_charge_dt_et"] = initial["_charge_dt"].dt.tz_convert(ET)
    initial["cohort"] = initial["_charge_dt_et"].dt.to_period("M").astype(str)
    cohort_map = initial.set_index("subscription_id")["cohort"].to_dict()
    df["cohort"] = df["subscription_id"].map(cohort_map)
    df = df.dropna(subset=["cohort"])

    # Only successful charges for retention
    successful = df[df["is_successful"]]

    # Build per-cohort retention
    max_period = int(df["period"].max()) if not df["period"].isna().all() else 0
    max_period = min(max_period, 52)

    cohort_groups = df.groupby("cohort")["subscription_id"].nunique()
    rows = []
    for cohort_label, size in cohort_groups.items():
        row = {"cohort": cohort_label, "cohort_size": size}
        cohort_successful = successful[successful["cohort"] == cohort_label]
        for p in range(max_period + 1):
            active = cohort_successful[cohort_successful["period"] == p]["subscription_id"].nunique()
            row[p] = round(active / size * 100, 1) if size > 0 else 0.0
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows).set_index("cohort")
    result.index.name = "cohort"
    return result
```

**Step 4: Run tests**

Run: `pytest tests/test_cohort_performance.py -v`
Expected: All PASS

**Step 5: Lint**

Run: `ruff check analytics.py tests/test_cohort_performance.py --fix`

**Step 6: Commit**

```bash
git add analytics.py tests/test_cohort_performance.py
git commit -m "feat: add build_cohort_heatmap() for per-period cohort retention"
```

---

### Task 3: Update methodology.py with new cohort docs

**Files:**
- Modify: `methodology.py` (lines 65-85, replace `COHORT_RETENTION_METHODOLOGY`)

**Step 1: Replace the methodology constant**

Replace the existing `COHORT_RETENTION_METHODOLOGY` (lines 65-85 of `methodology.py`) with:

```python
COHORT_RETENTION_METHODOLOGY = """
### How Cohort Performance Is Calculated

**Data Source**
- Source of truth: `charges` table (actual billing events, not subscription status)
- Charges are linked to subscriptions via `subscription_id`
- Only subscription-linked charges are included (one-time purchases excluded)

**Billing Cycle Periods**
- For each subscription, charges are ranked by date: rank 1 = Period 0 (initial purchase), rank 2 = Period 1 (first renewal), etc.
- Each period represents one billing cycle — the label adapts to the subscription interval:
  - Weekly subs: Week 0, Week 1, Week 2, ...
  - Monthly subs: Month 0, Month 1, Month 2, ...
  - Yearly subs: Year 0, Year 1, Year 2, ...

**Charge Classification**
- Successful: status is NULL/empty (SamCart default), or in {charged, succeeded, paid, complete}
- Refund: status in {refunded, partially_refunded, refund}
- Revenue uses net realized amount: `amount - refund_amount` for partial refunds

**Activity Summary**
- Active Subscribers: count of unique subscriptions with a successful charge in this period
- Renewals: active subscribers in periods > 0
- Initial Charges: active subscribers in period 0
- Period Revenue: sum of net charge amounts for successful charges
- Refunds This Period: unique subscriptions with a refund charge in this period

**Renewal Rate**
- Formula: `Active(Period N) / Active(Period N-1) * 100`
- Measures period-over-period retention

**Stick Rate**
- Formula: `Active(Period N) / Cohort Size * 100`
- Measures cumulative retention from original cohort

**Refund Rate**
- Formula: `Cumulative Refunds / Cohort Size * 100`

**Churn + Refund Rate**
- Formula: `(Dropped + Cumulative Refunds) / Cohort Size * 100`
- Gives full picture of lost subscribers

**Cohort Modes**
- Per-period: groups subscriptions by the month of their initial charge
- Combined: all subscriptions in one cohort regardless of when they joined

**Filters**
- Product: filters charges by product_name (enriched via orders/subscriptions)
- Interval: filters by subscription billing interval (weekly, monthly, yearly, etc.)
"""
```

**Step 2: Lint**

Run: `ruff check methodology.py --fix`

**Step 3: Commit**

```bash
git add methodology.py
git commit -m "docs: update cohort methodology to reflect charge-based approach"
```

---

### Task 4: Replace pages/2_Subscription_Cohorts.py with new UI

**Files:**
- Modify: `pages/2_Subscription_Cohorts.py` (full rewrite)

**Step 1: Rewrite the page**

Replace the entire contents of `pages/2_Subscription_Cohorts.py` with the new UI that:

1. Loads charges, subscriptions, orders, products
2. Provides filters: product, interval, cohort mode toggle
3. Shows summary metrics
4. Renders 3 tables (activity, renewal rates, stick rates) with dollar formatting
5. Shows retention heatmap in per-period mode
6. Provides export buttons for each table

Key UI elements:
- `st.selectbox` for product and interval filters
- `st.radio` for cohort mode (Combined / Per-Period)
- `st.dataframe` with `st.column_config.NumberColumn` for dollar formatting
- `px.imshow` heatmap (same pattern as existing code)
- `render_export_buttons` for each table
- Period labels adapt: use interval from subscriptions to label "Week N" / "Month N" / "Year N"

The page should call `build_cohort_performance()` for the 3 tables and `build_cohort_heatmap()` for the heatmap.

**Step 2: Lint**

Run: `ruff check pages/2_Subscription_Cohorts.py --fix`

**Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add pages/2_Subscription_Cohorts.py
git commit -m "feat: replace subscription cohort page with charge-based cohort performance report"
```

---

### Task 5: Fix daily metrics export — add totals row and dollar formatting

**Files:**
- Modify: `pages/4_Daily_Metrics.py` (around line 129-140, the export in tab1)
- Modify: `export.py` (line 48, add revenue columns to currency format list)

**Step 1: Update `export.py` currency column list**

In `export.py` line 48, add the daily metrics revenue columns to the currency format set:

```python
# Before:
if col_name in ("total", "amount", "total_spend", "total_revenue", "avg_order_value", "price", "estimated_ltv"):

# After:
if col_name in (
    "total", "amount", "total_spend", "total_revenue",
    "avg_order_value", "price", "estimated_ltv",
    "sale_revenue", "refund_amount", "renewal_revenue",
    "period_revenue", "cumulative_revenue",
):
```

**Step 2: Update daily metrics page to add totals row before export**

In `pages/4_Daily_Metrics.py`, modify the tab1 section (around lines 128-140). After building `display_df` and before `render_export_buttons`, add a totals row and format dollar columns:

```python
with tab1:
    display_df = filtered.copy()
    display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")

    # Build totals row for export
    totals = {col: "" for col in display_df.columns}
    totals["date"] = "TOTAL"
    totals["product_name"] = ""
    for col in ["new_customer_count", "sale_count", "sale_revenue",
                "refund_count", "refund_amount", "renewal_count", "renewal_revenue"]:
        if col in display_df.columns:
            totals[col] = display_df[col].sum()

    st.dataframe(
        display_df,
        column_config={
            "sale_revenue": st.column_config.NumberColumn("Sale Revenue", format="$%.2f"),
            "refund_amount": st.column_config.NumberColumn("Refund Amount", format="$%.2f"),
            "renewal_revenue": st.column_config.NumberColumn("Renewal Revenue", format="$%.2f"),
        },
        use_container_width=True,
    )

    # Export version includes totals row
    export_df = pd.concat([display_df, pd.DataFrame([totals])], ignore_index=True)
    render_export_buttons(export_df, "daily_summary", key_prefix="daily_summary")
```

**Step 3: Lint**

Run: `ruff check pages/4_Daily_Metrics.py export.py --fix`

**Step 4: Run tests**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add pages/4_Daily_Metrics.py export.py
git commit -m "feat: add totals row and dollar formatting to daily metrics export"
```

---

### Task 6: Final verification

**Step 1: Run full lint**

Run: `ruff check . --fix`

**Step 2: Run full test suite**

Run: `pytest tests/ -v`

**Step 3: Verify no regressions**

Check:
- Revenue calculations still use charges as source of truth
- NULL/empty charge status treated as successful
- SQL queries use parameterized values
- No PII in export filenames

**Step 4: Final commit if any fixups needed**
