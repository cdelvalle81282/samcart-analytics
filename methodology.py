"""Methodology descriptions and API data dictionary for documentation tabs."""

# ------------------------------------------------------------------
# Per-page methodology text (Markdown)
# ------------------------------------------------------------------

DASHBOARD_METHODOLOGY = """
### How Metrics Are Calculated

**Total Revenue**
- Source: `charges` table filtered to successful charges
- A charge is successful if its status is NULL/empty (SamCart default) or in (`charged`, `succeeded`, `paid`, `complete`)
- Sums the `amount` field from successful charges only
- Excludes refunded and partially_refunded charges
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
- Source: `charges` table filtered to successful statuses (`charged`, `succeeded`, `paid`, `complete`)
- `total_spend`: sum of all successful charge amounts for that customer
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
### How Metrics Are Calculated

**Cohort Assignment**
- Source: `subscriptions` table
- Each subscription is assigned to a cohort based on its `created_at` month

**Retention Calculation**
- For each cohort, tracks how many subscriptions are still active at month 0, 1, 2, ... N
- Active subscriptions (no `canceled_at`) are right-censored: counted as retained through the current month
- Canceled subscriptions use their `canceled_at` date to determine when they churned
- Retention % = `(subscriptions active at month N) / (cohort size) * 100`

**Churn Rate**
- `canceled subscriptions / total subscriptions * 100`
- Canceled includes both "canceled" and "cancelled" spellings

**Filters**
- Product filter: filters subscriptions by `product_name`
- Interval filter: filters by billing interval (monthly, yearly, etc.)
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
- Source: `charges` table filtered to successful charges (status is NULL/empty or in `charged`, `succeeded`, `paid`, `complete`)
- Enriched with product info by joining to `orders` (via `order_id`) and `subscriptions` (via `subscription_id`)
- Excludes renewals: for each `subscription_id`, charges are ranked by date — only rank 1 (initial purchase) is kept
- One-time charges (no `subscription_id`) are always counted as new sales
- `sale_count`: number of qualifying charges
- `sale_revenue`: sum of charge amounts

**Refunds**
- Source: `charges` table filtered to refund statuses (`refunded`, `partially_refunded`, `refund`)
- Enriched with product info the same way as new sales
- `refund_count`: number of refund charges
- `refund_amount`: sum of refund charge amounts

**Renewals**
- Source: `charges` table filtered to successful charges (status NULL/empty or whitelisted) with a non-empty `subscription_id`
- For each subscription, charges are ranked by date — only rank > 1 (subsequent charges) are renewals
- `renewal_count`: number of renewal charges
- `renewal_revenue`: sum of renewal charge amounts

**Entry Product LTV**
- Finds each customer's first order to determine their "entry product"
- Calculates total lifetime spend from successful charges
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
| `trial_days` | No | — | Trial period length |
| `next_bill_date` | No | — | Next scheduled charge date |
| `billing_cycle_count` | No | — | Number of completed billing cycles |

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
| `refund_amount` | No | — | Amount refunded (if partial) |
| `refund_date` | No | — | Date of refund |

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
"""
