-- Silver layer: typed, deduplicated, validated.
-- Expectations (CONSTRAINT ... EXPECT) come in three strengths:
--   no ON VIOLATION      -> keep the row, but count it as a failure (warn)
--   ON VIOLATION DROP ROW -> remove the row
--   ON VIOLATION FAIL UPDATE -> stop the pipeline (for data that must never be wrong)

CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.silver.customers (
  CONSTRAINT valid_customer_id     EXPECT (customer_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT valid_signup_date     EXPECT (signup_date IS NOT NULL),
  CONSTRAINT deleted_has_timestamp EXPECT (NOT is_deleted OR deleted_at IS NOT NULL)
)
COMMENT 'One row per customer (latest profile version). Soft-deleted customers and test accounts are KEPT and flagged.'
AS SELECT
  TRY_CAST(customer_id AS BIGINT)        AS customer_id,
  first_name,
  last_name,
  lower(trim(email))                     AS email,
  upper(trim(country))                   AS country,
  region,
  TRY_CAST(signup_date AS DATE)          AS signup_date,
  TRY_CAST(is_test_account AS BOOLEAN)   AS is_test_account,
  TRY_CAST(is_deleted AS BOOLEAN)        AS is_deleted,
  TRY_CAST(deleted_at AS TIMESTAMP)      AS deleted_at,
  TRY_CAST(updated_at AS TIMESTAMP)      AS updated_at
FROM (
  SELECT * FROM ${catalog}.bronze.customers_raw
  QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY TRY_CAST(updated_at AS TIMESTAMP) DESC) = 1
);


CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.silver.products (
  CONSTRAINT valid_product_id EXPECT (product_id IS NOT NULL)  ON VIOLATION DROP ROW,
  CONSTRAINT positive_price   EXPECT (list_price_usd > 0)
)
COMMENT 'One row per product.'
AS SELECT
  TRY_CAST(product_id AS BIGINT)               AS product_id,
  product_name,
  category,
  TRY_CAST(list_price_usd AS DECIMAL(18,2))    AS list_price_usd,
  TRY_CAST(is_active AS BOOLEAN)               AS is_active
FROM (
  SELECT * FROM ${catalog}.bronze.products_raw
  QUALIFY ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY _ingested_at DESC) = 1
);


CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.silver.orders (
  CONSTRAINT valid_order_id     EXPECT (order_id IS NOT NULL)    ON VIOLATION DROP ROW,
  CONSTRAINT has_customer       EXPECT (customer_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT valid_order_ts     EXPECT (order_ts IS NOT NULL)    ON VIOLATION DROP ROW,
  CONSTRAINT non_negative_total EXPECT (order_total >= 0)        ON VIOLATION DROP ROW,
  CONSTRAINT known_status       EXPECT (status IN ('completed', 'cancelled', 'pending')),
  CONSTRAINT known_currency     EXPECT (currency IN ('USD', 'EUR', 'GBP', 'CAD', 'INR'))
)
COMMENT 'One row per order, deduplicated. order_total is in LOCAL currency. Includes cancelled/pending orders and test-account orders.'
AS SELECT
  TRY_CAST(order_id AS BIGINT)            AS order_id,
  TRY_CAST(customer_id AS BIGINT)         AS customer_id,
  TRY_CAST(order_ts AS TIMESTAMP)         AS order_ts,
  lower(trim(status))                     AS status,
  lower(trim(channel))                    AS channel,
  upper(trim(currency))                   AS currency,
  TRY_CAST(order_total AS DECIMAL(18,2))  AS order_total
FROM (
  SELECT * FROM ${catalog}.bronze.orders_raw
  QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY _ingested_at DESC, _source_file) = 1
);


CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.silver.order_items (
  CONSTRAINT valid_keys         EXPECT (order_id IS NOT NULL AND product_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT positive_quantity  EXPECT (quantity > 0)    ON VIOLATION DROP ROW,
  CONSTRAINT non_negative_price EXPECT (unit_price >= 0) ON VIOLATION DROP ROW
)
COMMENT 'One row per order line. unit_price is in the order''s LOCAL currency.'
AS SELECT
  TRY_CAST(order_id AS BIGINT)            AS order_id,
  TRY_CAST(line_number AS INT)            AS line_number,
  TRY_CAST(product_id AS BIGINT)          AS product_id,
  TRY_CAST(quantity AS INT)               AS quantity,
  TRY_CAST(unit_price AS DECIMAL(18,2))   AS unit_price
FROM (
  SELECT * FROM ${catalog}.bronze.order_items_raw
  QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id, line_number ORDER BY _ingested_at DESC) = 1
);


CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.silver.refunds (
  CONSTRAINT valid_refund     EXPECT (refund_id IS NOT NULL AND order_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT positive_amount  EXPECT (refund_amount > 0) ON VIOLATION DROP ROW,
  CONSTRAINT valid_refund_ts  EXPECT (refund_ts IS NOT NULL)
)
COMMENT 'One row per refund. refund_amount is in the order''s LOCAL currency.'
AS SELECT
  TRY_CAST(refund_id AS BIGINT)             AS refund_id,
  TRY_CAST(order_id AS BIGINT)              AS order_id,
  TRY_CAST(refund_ts AS TIMESTAMP)          AS refund_ts,
  TRY_CAST(refund_amount AS DECIMAL(18,2))  AS refund_amount,
  reason
FROM (
  SELECT * FROM ${catalog}.bronze.refunds_raw
  QUALIFY ROW_NUMBER() OVER (PARTITION BY refund_id ORDER BY _ingested_at DESC) = 1
);


CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.silver.fx_rates (
  CONSTRAINT positive_rate EXPECT (usd_per_unit > 0 AND rate_month IS NOT NULL) ON VIOLATION FAIL UPDATE
)
COMMENT 'Monthly FX rates: USD value of 1 unit of currency, for the month starting rate_month.'
AS SELECT
  upper(trim(currency))                      AS currency,
  TRY_CAST(rate_month AS DATE)               AS rate_month,
  TRY_CAST(usd_per_unit AS DECIMAL(18,8))    AS usd_per_unit
FROM (
  SELECT * FROM ${catalog}.bronze.fx_rates_raw
  QUALIFY ROW_NUMBER() OVER (PARTITION BY currency, rate_month ORDER BY _ingested_at DESC) = 1
);


CREATE OR REFRESH MATERIALIZED VIEW ${catalog}.silver.fiscal_calendar (
  CONSTRAINT valid_fiscal_quarter EXPECT (fiscal_quarter BETWEEN 1 AND 4 AND date IS NOT NULL) ON VIOLATION FAIL UPDATE
)
COMMENT 'One row per day. Fiscal year starts Feb 1 and is named by the year it ends (FY2026 = 2025-02-01 to 2026-01-31).'
AS SELECT
  TRY_CAST(date AS DATE)               AS date,
  TRY_CAST(calendar_year AS INT)       AS calendar_year,
  TRY_CAST(calendar_quarter AS INT)    AS calendar_quarter,
  TRY_CAST(calendar_month AS INT)      AS calendar_month,
  month_name,
  day_of_week,
  TRY_CAST(is_weekend AS BOOLEAN)      AS is_weekend,
  TRY_CAST(fiscal_year AS INT)         AS fiscal_year,
  TRY_CAST(fiscal_quarter AS INT)      AS fiscal_quarter,
  TRY_CAST(fiscal_month AS INT)        AS fiscal_month
FROM (
  SELECT * FROM ${catalog}.bronze.fiscal_calendar_raw
  QUALIFY ROW_NUMBER() OVER (PARTITION BY date ORDER BY _ingested_at DESC) = 1
);