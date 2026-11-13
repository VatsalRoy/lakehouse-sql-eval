# Business rules (the single source of truth)

- **Fiscal year:** starts Feb 1, named by the year it ends. FY2026 = 2025-02-01 to 2026-01-31.
  "Q3" means fiscal Q3 unless a question says "calendar".
- **Currency:** all money is reported in USD, converted at the FX rate of the order's month.
- **Gross revenue:** sum of order_total_usd for completed orders from non-test customers.
- **Net revenue:** gross revenue minus refunds on those orders. Refunds count against the
  ORIGINAL order's date (not the refund date).
- **Excluded everywhere:** test accounts (is_test_account = true); cancelled and pending orders.
- **Soft-deleted customers:** their past orders still count toward revenue,
  but they are not counted as active customers.
- **Active customer:** a non-test, non-deleted customer with at least one completed order in the period.
- **Average order value (AOV):** net revenue / number of completed orders (non-test).
- **Refund rate:** refunded USD / gross revenue (by value, not by count).
- **Line-item revenue (by category/product):** sum of line_amount_usd; never sum order totals after joining to lines.