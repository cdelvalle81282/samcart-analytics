# Cohort Performance Report — Design

## Problem
The existing Subscription Cohorts page uses subscription status (created_at → canceled_at) to determine retention. This doesn't match actual billing activity. A charge-based approach using real charge events is more accurate and matches the manually-built spreadsheet methodology.

## Approach: Charge-Based Cohort Performance Report

### Data Flow
1. **Enrich charges** with product info via `enrich_charges_with_product()` (order_id → orders, fallback subscription_id → subscriptions)
2. **Link charges to subscriptions** via `charges.subscription_id → subscriptions.id` to get `interval`
3. **Rank charges** per subscription by `created_at` ascending. Rank 1 = Period 0 (initial), Rank 2+ = renewals
4. **Classify charges**: successful (NULL/empty/whitelist) vs refund
5. **Build cohorts**: group by initial-charge period (matching interval granularity), with toggle for single combined cohort
6. **Aggregate** per cohort per billing period: active subs, renewals, revenue, refunds
7. **Derive metrics**: renewal rate, stick rate, refund rate, churn+refund rate

### Period Labels
- Weekly subs: Week 1, Week 2, ...
- Monthly subs: Month 1, Month 2, ...
- Yearly subs: Year 1, Year 2, ...
- Each period = one billing cycle

### Cohort Modes
- **Per-period cohorts** (default): group by when subscribers first purchased (week/month/year matching interval)
- **Single combined cohort**: all subscribers lumped together regardless of join date

### Output Tables

**Table A — Activity Summary** (per billing period):
Period, Active Subscribers, Renewals, Initial Charges, Total Charged, Cumulative Refunds, Refunds This Period, Period Revenue ($), Cumulative Revenue ($)

**Table B — Period-over-Period Renewal Rate**:
Period, Subscribers (Start), Subscribers (End), Dropped Off, Renewal Rate, Stick Rate, Notes (auto-flags largest drop)

**Table C — Cumulative Stick Rate & Refund Rate**:
Through Period, Original Cohort, Still Active, Dropped (Cumul.), Stick Rate, Cumul. Refunds, Refund Rate, Churn + Refund Rate

### UI Layout (replaces page 2)
- **Filters**: Product, Interval, Cohort view toggle (per-period / combined)
- **Summary metrics**: Total Subscriptions, Currently Active, Overall Churn Rate
- **Tables A, B, C** shown for selected cohort (or combined)
- **Retention heatmap** (per-period cohort mode only) — charge-based
- **Export buttons** for all tables

### File Changes
| File | Change |
|------|--------|
| `analytics.py` | Add `build_cohort_performance()` returning 3 DataFrames |
| `pages/2_Subscription_Cohorts.py` | Replace with new UI |
| `methodology.py` | Update methodology docs |

### Existing `build_cohort_retention()` preserved (not deleted) for backward compat.
