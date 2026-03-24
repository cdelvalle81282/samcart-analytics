"""Methodology descriptions and API data dictionary for documentation tabs."""

# ------------------------------------------------------------------
# Per-page methodology text (Markdown)
# ------------------------------------------------------------------

DASHBOARD_METHODOLOGY = """
### How Metrics Are Calculated

**Total Revenue**
- Source: `charges` table filtered to *collected* charges (successful + partially refunded)
- A charge is collected if its status is NULL/empty (SamCart default), in (`charged`, `succeeded`, `paid`, `complete`), or `partially_refunded`
- Uses **net realized revenue**: `amount - refund_amount` for partially refunded charges, full `amount` for successful charges
- Fully refunded charges are excluded entirely
- Falls back to `orders.total` if no charges data is available

**Total Customers**
- Source: `customers` table
- Count of distinct customer IDs

**Active Subscriptions**
- Source: `subscriptions` table
- Count of distinct subscriptions where `status` = `active` (case-insensitive)

**Avg Order Value**
- Source: `orders` table
- Mean of the `total` field across all orders

**Overall Churn Rate**
- Formula: `canceled subscriptions / total subscriptions * 100`
- Canceled includes both "canceled" and "cancelled" spellings

**Monthly Revenue Chart**
- Revenue column: from successful charges grouped by month
- Order count column: from orders table grouped by month
- Months with charges but no orders (or vice versa) are filled with 0
"""

CUSTOMER_LOOKUP_METHODOLOGY = """
### How Metrics Are Calculated

**Customer LTV (Lifetime Value)**
- Source: `charges` table filtered to collected charges (successful + partially refunded)
- `total_spend`: sum of net realized charge amounts (`amount - refund_amount`) for that customer
- Partially refunded charges count as 1 event with reduced revenue; fully refunded charges are excluded
- Falls back to `orders.total` if no charges data exists

**First Purchase**
- Source: `orders` table
- Earliest `created_at` date for that customer

**Order Count**
- Source: `orders` table
- Number of orders placed by that customer

**Active Subs**
- Source: `subscriptions` table
- Count of subscriptions with `status` = `active` for that customer

**Top Customers Table**
- Ranked by `total_spend` descending
- Shows top 50 by default
"""

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
- Formula: `Active(Period N) / Active(Period N-1) × 100`
- Measures period-over-period retention

**Stick Rate**
- Formula: `Active(Period N) / Cohort Size × 100`
- Measures cumulative retention from original cohort

**Refund Rate**
- Formula: `Cumulative Refunds / Cohort Size × 100`

**Churn + Refund Rate**
- Formula: `(Dropped + Cumulative Refunds) / Cohort Size × 100`
- Gives full picture of lost subscribers

**Cohort Modes**
- Per-period: groups subscriptions by the month of their initial charge
- Combined: all subscriptions in one cohort regardless of when they joined

**Filters**
- Product: filters charges by product
- Interval: filters by subscription billing interval (weekly, monthly, yearly, etc.)
"""

PRODUCT_LTV_METHODOLOGY = """
### How Metrics Are Calculated

**Total Revenue**
- Source: `orders` table
- Sum of `total` field grouped by `product_id`

**Order Count**
- Source: `orders` table
- Number of orders per product

**Avg Order Value**
- Formula: `total_revenue / order_count` per product

**Subscriber Count**
- Source: `subscriptions` table
- Number of subscriptions (any status) per product

**Avg Lifetime (months)**
- Source: `subscriptions` table
- For each subscription: `(end_date - created_at) / 30.44 days`
- Active subscriptions use current date as end_date
- Averaged per product
"""

DAILY_METRICS_METHODOLOGY = """
### How Metrics Are Calculated

**New-to-File Customers**
- Source: `orders` table
- Finds each customer's very first purchase date across ALL products
- On that first purchase date, counts the customer as "new-to-file" for each product they bought
- A customer is only new-to-file once, on the day of their first-ever order

**New Sales**
- Source: `charges` table filtered to collected charges (successful + partially refunded)
- Uses **net realized revenue** (`amount - refund_amount` for partial refunds)
- Enriched with product info by joining to `orders` (via `order_id`) and `subscriptions` (via `subscription_id`)
- Excludes renewals: for each `subscription_id`, charges are ranked by date — only rank 1 (initial purchase) is kept
- One-time charges (no `subscription_id`) are always counted as new sales
- Partially refunded charges count as 1 sale event with reduced revenue
- `sale_count`: number of qualifying charges
- `sale_revenue`: sum of net charge amounts

**Refunds**
- Source: `charges` table filtered to refund statuses (`refunded`, `partially_refunded`, `refund`)
- Enriched with product info the same way as new sales
- Uses `refund_date` for the daily date axis when available; otherwise falls back to the original charge date
- `refund_count`: number of refund charges
- `refund_amount`: sum of refunded dollars (`refund_amount` when present, otherwise the full `amount` for full refunds)

**Renewals**
- Source: `charges` table filtered to collected charges (successful + partially refunded) with a non-empty `subscription_id`
- For each subscription, charges are ranked by date — only rank > 1 (subsequent charges) are renewals
- Uses **net realized revenue** for each renewal
- `renewal_count`: number of renewal charges
- `renewal_revenue`: sum of net renewal charge amounts

**Entry Product LTV**
- Finds each customer's first order to determine their "entry product"
- Calculates total lifetime spend from collected charges using net realized revenue
- Groups by entry product: shows customer count, average LTV, median LTV, total LTV
"""

# ------------------------------------------------------------------
# API Data Dictionary
# ------------------------------------------------------------------

API_DATA_DICTIONARY = """
### SamCart API Data Points

The dashboard syncs data from the [SamCart v1 REST API](https://api.samcart.com/v1). Below are all fields available from each endpoint and which ones we store locally.

---

#### Orders (`/v1/orders`)

| Field | Stored | Column | Description |
|-------|--------|--------|-------------|
| `id` | Yes | `id` | Unique order ID |
| `customer_id` | Yes | `customer_id` | ID of the customer who placed the order |
| `customer_email` | Yes | `customer_email` | Looked up from customers table via customer_id |
| `order_date` / `created_at` | Yes | `created_at` | When the order was placed (UTC) |
| `total` | Yes | `total` | Order total in dollars |
| `cart_items[].product_id` | Yes | `product_id` | Product ID (from first cart item) |
| `cart_items[].product_name` | Yes | `product_name` | Product name (from first cart item) |
| `cart_items[].subscription_id` | Yes | `subscription_id` | Linked subscription ID if applicable |
| `status` | No | — | Order status |
| `currency` | No | — | Currency code |
| `cart_items[].quantity` | No | — | Item quantity |
| `cart_items[].price` | No | — | Item unit price |
| `shipping` | No | — | Shipping details |
| `tax` | No | — | Tax amount |
| `discount` | No | — | Discount applied |

---

#### Customers (`/v1/customers`)

| Field | Stored | Column | Description |
|-------|--------|--------|-------------|
| `id` | Yes | `id` | Unique customer ID |
| `email` | Yes | `email` | Customer email address |
| `first_name` | Yes | `first_name` | First name |
| `last_name` | Yes | `last_name` | Last name |
| `phone` | Yes | `phone` | Phone number |
| `created_at` | Yes | `created_at` | Account creation date (UTC) |
| `addresses[type=billing].city` | Yes | `billing_city` | Billing city |
| `addresses[type=billing].state` | Yes | `billing_state` | Billing state |
| `addresses[type=billing].country` | Yes | `billing_country` | Billing country |
| `addresses[type=billing].street` | No | — | Billing street (PII excluded) |
| `addresses[type=billing].zip` | No | — | Billing zip code |
| `addresses[type=shipping].*` | No | — | Shipping address fields |

---

#### Subscriptions (`/v1/subscriptions`)

| Field | Stored | Column | Description |
|-------|--------|--------|-------------|
| `id` | Yes | `id` | Unique subscription ID |
| `customer_id` | — | — | Used to look up `customer_email` |
| `customer_email` | Yes | `customer_email` | Resolved from customers table |
| `product_id` | Yes | `product_id` | Associated product |
| `product_name` | Yes | `product_name` | Product display name |
| `status` | Yes | `status` | active, canceled, past_due, etc. |
| `subscription_interval` | Yes | `interval` | Billing interval (monthly, yearly, etc.) |
| `recurring_price.total` | Yes | `price` | Recurring charge amount |
| `created_at` | Yes | `created_at` | Subscription start date (UTC) |
| `end_date` | Yes | `canceled_at` | Set when status = canceled |
| `trial_days` | Yes | `trial_days` | Trial period length (0 = no trial) |
| `next_bill_date` | Yes | `next_bill_date` | Next scheduled charge date (UTC) |
| `billing_cycle_count` | Yes | `billing_cycle_count` | Number of completed billing cycles |

---

#### Charges (`/v1/charges`)

| Field | Stored | Column | Description |
|-------|--------|--------|-------------|
| `id` | Yes | `id` | Unique charge ID |
| `order_id` | Yes | `order_id` | Linked order |
| `subscription_rebill_id` | Yes | `subscription_id` | Linked subscription |
| `customer_id` | — | — | Used to look up `customer_email` |
| `customer_email` | Yes | `customer_email` | Resolved from customers table |
| `total` / `amount` | Yes | `amount` | Charge amount in dollars |
| `charge_refund_status` | Yes | `status` | charged, succeeded, paid, complete, refunded, partially_refunded, refund |
| `created_at` | Yes | `created_at` | Charge date (UTC) |
| `processor` | No | — | Payment processor used |
| `processor_transaction_id` | No | — | Gateway transaction ID |
| `refund_amount` | Yes | `refund_amount` | Amount refunded in dollars (API value / 100) |
| `refund_date` | Yes | `refund_date` | Date of refund (UTC) |

---

#### Products (`/v1/products`)

| Field | Stored | Column | Description |
|-------|--------|--------|-------------|
| `id` | Yes | `id` | Unique product ID |
| `product_name` / `name` | Yes | `name` | Product display name |
| `price` | Yes | `price` | Base price |
| `sku` | Yes | `sku` | Product SKU |
| `type` | No | — | Product type (digital, physical, etc.) |
| `url` | No | — | Product page URL |
| `checkout_url` | No | — | Checkout page URL |
| `description` | No | — | Product description |
| `active` | No | — | Whether product is active |

---

### Charge Status Values

| Status | Category | Description |
|--------|----------|-------------|
| `NULL` / empty | Successful | Default for successful charges (most common) |
| `charged` | Successful | Payment captured |
| `succeeded` | Successful | Payment succeeded |
| `paid` | Successful | Payment completed |
| `complete` | Successful | Transaction complete |
| `refunded` | Refund | Fully refunded |
| `partially_refunded` | Refund | Partially refunded |
| `refund` | Refund | Refund processed |
| `failed` | Failed | Payment failed |
| `pending` | Pending | Awaiting processing |

### Revenue Semantics

The dashboard uses two intentionally different revenue semantics:

| Context | Semantics | Logic |
|---------|-----------|-------|
| Refund Analysis page | **Gross** (original charge amount) | `amount` for charges that transacted (successful + refunded) |
| All other reports (RFM, LTV, Daily, Concentration, Revenue Mix) | **Net realized** (after partial refunds) | `amount - refund_amount` for collected charges |

These totals intentionally differ. Gross semantics show what was originally charged; net semantics show what was actually retained.

| Charge Status | Event Count | Revenue |
|---------------|-------------|---------|
| Successful (NULL/charged/etc.) | 1 sale/renewal | `amount` |
| `partially_refunded` | 1 sale/renewal | `amount - refund_amount` |
| `refunded` (fully) | 0 (excluded) | $0 |
| `failed` / `pending` | 0 | $0 |
"""

# ------------------------------------------------------------------
# New report methodology constants
# ------------------------------------------------------------------

MRR_WATERFALL_METHODOLOGY = """
### How MRR Waterfall Is Calculated

**MRR (Monthly Recurring Revenue)**
- Source: `subscriptions` table
- Each subscription's price is normalized to monthly equivalent using its billing interval
- Weekly × 52/12, yearly ÷ 12, quarterly ÷ 3, etc.

**New MRR**
- Subscriptions created this month where the customer has no prior canceled subscription for the same product
- Concurrent subscriptions for the same product each count as new MRR

**Reactivation MRR**
- Subscriptions created this month where the customer had a prior canceled subscription for the same product
- Only counts as reactivation if no currently-active subscription existed for that (customer, product) at the new sub's start

**Churned MRR**
- Subscriptions whose `canceled_at` falls in this month

**Net MRR**
- Formula: `new_mrr + reactivation_mrr - churned_mrr`

**Limitations**
- Expansion/contraction MRR not tracked (SamCart doesn't surface price changes on existing subs)
"""

REVENUE_FORECAST_METHODOLOGY = """
### How Revenue Forecast Is Calculated

**Projected Revenue**
- Source: `subscriptions` table, active subs with a `next_bill_date`
- For each active subscription, projects future billing dates forward using its interval
- Sums expected charge amounts in 30-day, 60-day, and 90-day windows

**Limitations**
- Assumes no churn — all active subs continue billing
- Does not account for price changes or payment failures
- Only includes subscriptions with a known `next_bill_date`
"""

REFUND_ANALYSIS_METHODOLOGY = """
### How Refund Analysis Is Calculated

**Refund Rate by Product** (uses **gross** semantics)
- Denominator: charges that transacted (successful + refunded statuses), excluding failed/pending
- `refund_rate_count_pct` = refund count / gross charge count × 100
- `refund_rate_revenue_pct` = sum(refunded dollars) / gross revenue × 100
- Refunded dollars use `refund_amount` when present; full refunds fall back to the original `amount`
- Gross revenue uses the original `amount` before any refund

**Time to Refund**
- `days_to_refund` = `refund_date - created_at` (refund event date minus original charge date)
- Only includes charges where `refund_date` is populated

**Monthly Refund Trend**
- Grouped by `refund_date` month (when the refund happened), NOT the original charge month
- Shows absolute refund count and refund amount per month
- No rate in the trend (numerator and denominator use different time bases)

**Note**: Refund analysis uses *gross* semantics intentionally. Totals will differ from net-revenue reports.
"""

CHURN_ANALYSIS_METHODOLOGY = """
### How Churn Analysis Is Calculated

**Churn Rate by Product**
- Formula: `canceled / total × 100` per product
- Includes both "canceled" and "cancelled" spellings
- `avg_lifetime_days`: average days between `created_at` and `canceled_at` for canceled subs

**Monthly Trend**
- Created vs canceled subscriptions per month
- Cumulative active: running total of created minus canceled
"""

TRIAL_CONVERSION_METHODOLOGY = """
### How Trial-to-Paid Conversion Is Calculated

**Trial Identification**
- Source: `subscriptions` table where `trial_days > 0`

**Conversion Status**
- **Converted**: `billing_cycle_count >= 1` (at least one paid billing cycle completed)
- **Dropped**: subscription canceled AND `billing_cycle_count` is 0 or NULL
- **Still in trial**: active subscription with 0 billing cycles — excluded from denominator

**Conversion Rate**
- Formula: `converted / (converted + dropped) × 100`
- Only resolved trials (converted or dropped) are included

**Limitations**
- Requires `trial_days` and `billing_cycle_count` fields from the API (populated after full sync)
"""

SUBSCRIPTION_AGING_METHODOLOGY = """
### How Subscription Aging Is Calculated

**Age Calculation**
- Source: `subscriptions` table, active subs only
- Age = days since `created_at`
- Bucketed: 0-30d, 31-90d, 91-180d, 181-365d, 1-2yr, 2yr+

**Display**
- Grouped by product and age bucket
"""

RFM_METHODOLOGY = """
### How RFM Segmentation Is Calculated

**Recency (R)**
- Days since last *collected* charge (successful or partially refunded)
- Fully refunded charges excluded — a reversed transaction doesn't count as recent activity
- Lower recency = higher R score

**Frequency (F)**
- Distinct order count from the orders table

**Monetary (M)**
- Total net realized charge amount (`amount - refund_amount` for partial refunds)

**Scoring**
- Each dimension scored 1-5 using quintiles (`pd.qcut`, duplicates dropped)
- R is inverted (fewer days since last charge = higher score)

**Segments**
| Segment | Criteria |
|---------|----------|
| Champions | R≥4 and F≥4 |
| Loyal | R≥3 and F≥3 |
| New | R≥4 and F≤2 |
| Potential Loyalists | R≥3 and F≤2 |
| At Risk | R≤2 and F≥3 |
| Lost | R≤2 and F≤2 |
| Hibernating | All others |

**Limitations**
- Requires ≥10 customers for meaningful quintiles
- Uses net realized revenue (partially refunded charges have reduced monetary value)
"""

MULTI_PRODUCT_METHODOLOGY = """
### How Multi-Product Buyers Is Calculated

**Buyer Summary**
- Source: `orders` table
- Counts distinct `product_id` values per customer
- Filters to customers with 2+ distinct products

**Product Combos**
- For each multi-product customer, generates all product pair combinations
- Counts how many customers bought each pair

**Limitations**
- Uses primary order product only — bumps/upsells from the same checkout are not included
"""

CONCENTRATION_METHODOLOGY = """
### How Customer Concentration Is Calculated

**Revenue Ranking**
- Source: `charges` table, collected charges only
- Uses **net realized revenue** (`amount - refund_amount` for partial refunds)
- Customers ranked by total revenue descending

**Cumulative %**
- Running cumulative sum of revenue
- Shows what % of total revenue the top N customers represent

**Key Metrics**
- Top 10 = X%, Top 50 = Y%, Top 100 = Z% of total revenue
"""

PRODUCT_MRR_TREND_METHODOLOGY = """
### How Product MRR Trend Is Calculated

**Monthly MRR**
- Source: `subscriptions` table
- For each subscription: active from `created_at` month through `canceled_at` month (or current month if still active)
- Price normalized to monthly equivalent using billing interval
- Summed per product per month

**Limitations**
- Does not reflect mid-month starts/cancellations (counts the full month)
"""

ATTACH_RATE_METHODOLOGY = """
### How Product Attach Rate Is Calculated

**Attach Rate**
- Source: `orders` table
- For each pair (product_a, product_b): what % of product_a buyers also bought product_b
- Minimum 5 buyers per product to be included
- Directional: attach rate A→B may differ from B→A

**Limitations**
- Uses primary order product only — bumps/upsells from the same checkout are not included
"""

REVENUE_MIX_METHODOLOGY = """
### How Revenue Mix Is Calculated

**New vs Renewal Classification**
- Source: `charges` table, collected charges only (net realized revenue)
- For each `subscription_id`, charges ranked by date: rank 1 = new, rank > 1 = renewal
- Charges without a `subscription_id` are always classified as "new"

**Revenue**
- Uses **net realized revenue** (`amount - refund_amount` for partial refunds)
- Grouped by product and month

**Percentages**
- `new_pct` = new_revenue / total_revenue × 100
- `renewal_pct` = renewal_revenue / total_revenue × 100
"""
