-- Gold layer: a small star schema that business users (and the LLM) query.
-- Dimensions describe things (customers, products, dates); facts record events (orders, lines, refunds).
-- Gold deliberately does NOT bake in business rules (no "net revenue" column, test accounts still present).
-- Those rules live in the metric view (Phase 3). That is the whole experiment.

CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.gold.dim_customer
COMMENT 'Customer dimension. Includes soft-deleted customers (is_deleted) and internal test accounts (is_test_account).'
AS SELECT
  customer_id, first_name, last_name, email, country, region,
  signup_date, is_test_account, is_deleted, deleted_at
FROM ${catalog}.silver.customers;


CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.gold.dim_product
COMMENT 'Product dimension. list_price_usd is the catalog price before discounts.'
AS SELECT product_id, product_name, category, list_price_usd, is_active
FROM ${catalog}.silver.products;


CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.gold.dim_date
COMMENT 'Date dimension with calendar and fiscal attributes. Fiscal year starts Feb 1; FY2026 = 2025-02-01 to 2026-01-31.'
AS SELECT
  date, calendar_year, calendar_quarter, calendar_month, month_name, day_of_week, is_weekend,
  fiscal_year, fiscal_quarter, fiscal_month,
  concat('FY', fiscal_year, '-Q', fiscal_quarter) AS fiscal_quarter_label
FROM ${catalog}.silver.fiscal_calendar;


CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.gold.fact_orders
COMMENT 'One row per order. order_total_local is in the order currency; order_total_usd uses the FX rate of the order month. Includes ALL statuses and test accounts.'
AS SELECT
  o.order_id,
  o.customer_id,
  CAST(o.order_ts AS DATE)                              AS order_date,
  o.order_ts,
  o.status,
  o.channel,
  o.currency,
  o.order_total                                         AS order_total_local,
  fx.usd_per_unit                                       AS fx_usd_per_unit,
  CAST(ROUND(o.order_total * fx.usd_per_unit, 2) AS DECIMAL(18,2)) AS order_total_usd
FROM ${catalog}.silver.orders o
LEFT JOIN ${catalog}.silver.fx_rates fx
  ON fx.currency = o.currency
 AND fx.rate_month = trunc(CAST(o.order_ts AS DATE), 'MM');


CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.gold.fact_order_items
COMMENT 'One row per order line. Amounts in local and USD (order-month FX). Summing order-level columns after joining to this table double-counts.'
AS SELECT
  i.order_id,
  i.line_number,
  i.product_id,
  i.quantity,
  i.unit_price                                                   AS unit_price_local,
  CAST(i.quantity * i.unit_price AS DECIMAL(18,2))               AS line_amount_local,
  CAST(ROUND(i.quantity * i.unit_price * fx.usd_per_unit, 2) AS DECIMAL(18,2)) AS line_amount_usd
FROM ${catalog}.silver.order_items i
INNER JOIN ${catalog}.silver.orders o ON o.order_id = i.order_id
LEFT JOIN ${catalog}.silver.fx_rates fx
  ON fx.currency = o.currency
 AND fx.rate_month = trunc(CAST(o.order_ts AS DATE), 'MM');


CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.gold.fact_refunds
COMMENT 'One row per refund. Converted to USD at the ORIGINAL order month FX rate, so a full refund exactly cancels its order. refund_date may fall in a later quarter than the order.'
AS SELECT
  r.refund_id,
  r.order_id,
  r.refund_ts,
  CAST(r.refund_ts AS DATE)                                       AS refund_date,
  r.reason,
  o.currency,
  r.refund_amount                                                 AS refund_amount_local,
  CAST(ROUND(r.refund_amount * fx.usd_per_unit, 2) AS DECIMAL(18,2)) AS refund_amount_usd
FROM ${catalog}.silver.refunds r
INNER JOIN ${catalog}.silver.orders o ON o.order_id = r.order_id
LEFT JOIN ${catalog}.silver.fx_rates fx
  ON fx.currency = o.currency
 AND fx.rate_month = trunc(CAST(o.order_ts AS DATE), 'MM');