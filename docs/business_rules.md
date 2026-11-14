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


## Vocabulary (how plain-English questions map to definitions)

- "revenue", "sales", "income", "money we made" (no qualifier) = **net revenue**.
- "orders" (no qualifier) = **completed orders from non-test customers**.
- "Q1"–"Q4" = **fiscal** quarters unless the question says "calendar".
  Q1 = Feb–Apr, Q2 = May–Jul, Q3 = Aug–Oct, Q4 = Nov–Jan.
- "Q3 2025" or "fiscal 2025" = fiscal year **FY2025** (Feb 1, 2024 – Jan 31, 2025).
- A named month ("January 2025") or "calendar year/quarter" = calendar dates.
- "Customer accounts" or "records" = raw rows (includes test and deleted), used only when a question says so explicitly.
- Product/category revenue is gross line revenue; refunds are NOT allocated to products.
- Product names are not unique; always group products by product_id.