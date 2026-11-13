# Databricks notebook source
# MAGIC %md
# MAGIC # Generate synthetic retail data
# MAGIC Writes raw CSV/JSON files into a Unity Catalog Volume (the "landing zone").
# MAGIC
# MAGIC Deliberate traps that make "revenue" ambiguous:
# MAGIC - ~8% of orders refunded (full or partial), refunds can land in a later quarter
# MAGIC - fiscal year starts Feb 1 (FY named by the year it ends: FY2026 = Feb 2025 - Jan 2026)
# MAGIC - 5 currencies with monthly FX rates
# MAGIC - soft-deleted customers, test accounts, cancelled and pending orders
# MAGIC - an order_total column that double-counts if you join orders to line items
# MAGIC - duplicate rows, bad rows (negative totals, missing customer), late customer updates

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("n_orders", "200000")
dbutils.widgets.text("seed", "42")
dbutils.widgets.dropdown("overwrite", "false", ["false", "true"])

CATALOG = dbutils.widgets.get("catalog")
N_ORDERS = int(dbutils.widgets.get("n_orders"))
SEED = int(dbutils.widgets.get("seed"))
OVERWRITE = dbutils.widgets.get("overwrite") == "true"

spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.bronze.landing COMMENT 'Landing zone for raw generated files'")
LANDING = f"/Volumes/{CATALOG}/bronze/landing"
SOURCES = ["customers", "products", "orders", "order_items", "refunds", "fx_rates", "fiscal_calendar"]

# COMMAND ----------

import os
import shutil
import numpy as np
import pandas as pd

if os.path.isdir(f"{LANDING}/orders") and os.listdir(f"{LANDING}/orders") and not OVERWRITE:
    dbutils.notebook.exit("Landing data already exists. Re-run with overwrite=true, then full-refresh the pipeline.")

for s in SOURCES:
    shutil.rmtree(f"{LANDING}/{s}", ignore_errors=True)
    os.makedirs(f"{LANDING}/{s}", exist_ok=True)

rng = np.random.default_rng(SEED)
EPOCH = pd.Timestamp("1970-01-01")
def to_days(ts):
    return (pd.Timestamp(ts) - EPOCH).days
def days_to_str(d):
    return pd.to_datetime(d, unit="D").strftime("%Y-%m-%d")

START_D = to_days("2023-02-01")  # first day of FY2024
END_D = to_days("2026-01-31")    # last day of FY2026

# COMMAND ----------

# Fiscal calendar: FY starts Feb 1 and is named by the calendar year in which it ends.
dates = pd.date_range("2022-02-01", "2027-01-31", freq="D")
fiscal_month = ((dates.month - 2) % 12) + 1
fiscal_calendar = pd.DataFrame({
    "date": dates.strftime("%Y-%m-%d"),
    "calendar_year": dates.year,
    "calendar_quarter": dates.quarter,
    "calendar_month": dates.month,
    "month_name": dates.strftime("%B"),
    "day_of_week": dates.strftime("%A"),
    "is_weekend": np.where(dates.dayofweek >= 5, "true", "false"),
    "fiscal_year": np.where(dates.month >= 2, dates.year + 1, dates.year),
    "fiscal_quarter": (fiscal_month - 1) // 3 + 1,
    "fiscal_month": fiscal_month,
})

# Monthly FX rates (USD per 1 unit of currency), random walk around realistic levels.
months = pd.date_range("2022-02-01", "2027-01-01", freq="MS")
base_rates = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CAD": 0.74, "INR": 0.012}
fx_rows = []
for cur, b in base_rates.items():
    rates = np.ones(len(months)) if cur == "USD" else b * np.exp(np.cumsum(rng.normal(0, 0.015, len(months))))
    fx_rows += [(cur, m.strftime("%Y-%m-%d"), round(float(r), 8)) for m, r in zip(months, rates)]
fx_rates = pd.DataFrame(fx_rows, columns=["currency", "rate_month", "usd_per_unit"])

# COMMAND ----------

# Customers
N_CUSTOMERS = 25_000
FIRST = ["Aarav", "Olivia", "Liam", "Emma", "Noah", "Ava", "Mia", "Lucas", "Sofia", "Ethan", "Isla", "Leo",
         "Priya", "Arjun", "Chloe", "Hugo", "Lena", "Mateo", "Zara", "Omar", "Grace", "Felix", "Anika", "Jack",
         "Elena", "Ravi", "Maya", "Louis", "Hannah", "Kai"]
LAST = ["Smith", "Patel", "Johnson", "Brown", "Garcia", "Müller", "Martin", "Singh", "Wilson", "Taylor",
        "Dubois", "Schmidt", "Kumar", "Clark", "Lewis", "Walker", "Moreau", "Fischer", "Shah", "Young",
        "King", "Wright", "Lopez", "Hill", "Green", "Baker", "Adams", "Nelson", "Carter", "Mehta"]
COUNTRIES = pd.DataFrame({
    "country": ["US", "CA", "GB", "DE", "FR", "IN"],
    "region": ["North America", "North America", "Europe", "Europe", "Europe", "Asia Pacific"],
    "currency": ["USD", "CAD", "GBP", "EUR", "EUR", "INR"],
    "weight": [0.45, 0.10, 0.12, 0.10, 0.08, 0.15],
})

cidx = rng.choice(len(COUNTRIES), N_CUSTOMERS, p=COUNTRIES["weight"].to_numpy())
customer_id = np.arange(100001, 100001 + N_CUSTOMERS)
first = rng.choice(FIRST, N_CUSTOMERS)
last = rng.choice(LAST, N_CUSTOMERS)
signup_d = rng.integers(to_days("2022-06-01"), to_days("2026-01-15") + 1, N_CUSTOMERS)
is_test = rng.random(N_CUSTOMERS) < 0.015

win_start = np.maximum(signup_d, START_D)          # first day a customer can order
can_delete = win_start + 30 < END_D
is_deleted = (rng.random(N_CUSTOMERS) < 0.04) & can_delete
gap = np.maximum(END_D - win_start - 30, 1)
deleted_d = np.where(is_deleted, win_start + 30 + (rng.random(N_CUSTOMERS) * gap).astype(int), -1)
win_end = np.where(is_deleted, deleted_d, END_D)    # last day a customer can order

domains = rng.choice(["gmail.com", "outlook.com", "yahoo.com", "icloud.com"], N_CUSTOMERS)
email = [f"{f.lower()}.{l.lower()}{i}@{'test.internal' if t else d}"
         for f, l, i, t, d in zip(first, last, customer_id, is_test, domains)]

customers = pd.DataFrame({
    "customer_id": customer_id,
    "first_name": first,
    "last_name": last,
    "email": email,
    "country": COUNTRIES["country"].to_numpy()[cidx],
    "region": COUNTRIES["region"].to_numpy()[cidx],
    "signup_date": days_to_str(signup_d),
    "is_test_account": np.where(is_test, "true", "false"),
    "is_deleted": np.where(is_deleted, "true", "false"),
    "deleted_at": np.where(is_deleted, days_to_str(np.maximum(deleted_d, 0)) + " 12:00:00", ""),
    "updated_at": days_to_str(signup_d) + " 00:00:00",
})

# ~1% of customers get a later profile update (new email). Silver must keep only the latest version.
upd = customers.sample(frac=0.01, random_state=SEED).copy()
upd["email"] = upd["email"].str.replace("@", ".new@", regex=False)
upd["updated_at"] = days_to_str(rng.integers(to_days("2025-06-01"), END_D, len(upd))) + " 09:30:00"

# COMMAND ----------

# Products
CATEGORIES = {  # category: (product nouns, log-price mean, log-price sigma, share of catalog)
    "Electronics": (["Wireless Earbuds", "Smartwatch", "Bluetooth Speaker", "USB-C Hub", "Keyboard", "Webcam", "Power Bank", "Monitor"], 4.6, 0.6, 0.20),
    "Home & Kitchen": (["Blender", "Coffee Maker", "Knife Set", "Air Fryer", "Cookware Set", "Desk Lamp", "Throw Blanket"], 3.8, 0.5, 0.18),
    "Apparel": (["Hoodie", "Running Shoes", "Rain Jacket", "Denim Jeans", "T-Shirt", "Wool Socks"], 3.5, 0.5, 0.18),
    "Sports & Outdoors": (["Yoga Mat", "Water Bottle", "Camping Tent", "Dumbbell Set", "Hiking Backpack"], 3.9, 0.6, 0.14),
    "Beauty": (["Face Serum", "Moisturizer", "Shampoo", "Lip Balm", "Sunscreen"], 3.0, 0.4, 0.12),
    "Books": (["Cookbook", "Novel", "Travel Guide", "Notebook", "Planner"], 2.8, 0.3, 0.10),
    "Toys": (["Building Blocks", "Puzzle", "Board Game", "Plush Toy", "RC Car"], 3.2, 0.5, 0.08),
}
BRANDS = ["Nova", "Acme", "Orbit", "Pine", "Lumen", "Vertex", "Harbor", "Cedar", "Zephyr", "Kite"]
SUFFIX = ["Pro", "Lite", "Max", "Classic", "Eco", "Ultra", "Mini", "Plus"]
N_PRODUCTS = 400

cat_names = list(CATEGORIES)
cat_pick = rng.choice(len(cat_names), N_PRODUCTS, p=[CATEGORIES[c][3] for c in cat_names])
prod_rows = []
for i, ci in enumerate(cat_pick):
    cat = cat_names[ci]
    nouns, mu, sigma, _ = CATEGORIES[cat]
    name = f"{rng.choice(BRANDS)} {rng.choice(nouns)} {rng.choice(SUFFIX)}"
    price = max(2.99, round(float(np.exp(rng.normal(mu, sigma))), 2))
    prod_rows.append((5001 + i, name, cat, price, "true" if rng.random() > 0.05 else "false"))
products = pd.DataFrame(prod_rows, columns=["product_id", "product_name", "category", "list_price_usd", "is_active"])
popularity = 1.0 / np.arange(1, N_PRODUCTS + 1) ** 0.8
popularity = rng.permutation(popularity / popularity.sum())

# COMMAND ----------

# Orders
cust_weight = rng.lognormal(0, 1, N_CUSTOMERS) * np.where(is_test, 8.0, 1.0)  # QA accounts order a lot
ocust = rng.choice(N_CUSTOMERS, N_ORDERS, p=cust_weight / cust_weight.sum())
oday = win_start[ocust] + (rng.random(N_ORDERS) * (win_end[ocust] - win_start[ocust] + 1)).astype(int)
osec = rng.integers(0, 86400, N_ORDERS)
sort_idx = np.argsort(oday.astype(np.int64) * 86400 + osec, kind="stable")
ocust, oday, osec = ocust[sort_idx], oday[sort_idx], osec[sort_idx]

order_ts = pd.to_datetime(oday, unit="D") + pd.to_timedelta(osec, unit="s")
currency = COUNTRIES["currency"].to_numpy()[cidx[ocust]]
status = np.where(rng.random(N_ORDERS) < 0.05, "cancelled", "completed")
recent = oday > END_D - 10
status = np.where(recent & (rng.random(N_ORDERS) < 0.5) & (status == "completed"), "pending", status)
channel = rng.choice(["web", "mobile", "store"], N_ORDERS, p=[0.55, 0.35, 0.10])
order_id = np.arange(1_000_001, 1_000_001 + N_ORDERS)

# FX rate for each order = rate for (currency, order month)
fx_map = {(c, m): r for c, m, r in fx_rows}
order_month = pd.to_datetime(oday, unit="D").strftime("%Y-%m-01")
order_fx = np.array([fx_map[(c, m)] for c, m in zip(currency, order_month)])

# Line items
n_items = rng.choice([1, 2, 3, 4, 5], N_ORDERS, p=[0.45, 0.25, 0.15, 0.10, 0.05])
line_order = np.repeat(np.arange(N_ORDERS), n_items)
n_lines = len(line_order)
line_number = np.arange(n_lines) - np.repeat(np.cumsum(n_items) - n_items, n_items) + 1
pidx = rng.choice(N_PRODUCTS, n_lines, p=popularity)
quantity = rng.choice([1, 2, 3], n_lines, p=[0.75, 0.18, 0.07])
discount = rng.choice([1.0, 0.9, 0.8], n_lines, p=[0.75, 0.17, 0.08])
unit_price_local = np.round(products["list_price_usd"].to_numpy()[pidx] * discount / order_fx[line_order], 2)
line_amount = quantity * unit_price_local
order_total = np.round(np.bincount(line_order, weights=line_amount, minlength=N_ORDERS), 2)

order_items = pd.DataFrame({
    "order_id": order_id[line_order],
    "line_number": line_number,
    "product_id": products["product_id"].to_numpy()[pidx],
    "quantity": quantity,
    "unit_price": unit_price_local,
})

# Bad rows: negative totals (0.1%) and missing customer (0.05%). Silver expectations should drop them.
bad_neg = rng.random(N_ORDERS) < 0.001
bad_nocust = (rng.random(N_ORDERS) < 0.0005) & ~bad_neg
order_total_out = np.where(bad_neg, -order_total, order_total)
cust_out = pd.array(customer_id[ocust], dtype="Int64")
cust_out[bad_nocust] = pd.NA

orders = pd.DataFrame({
    "order_id": order_id,
    "customer_id": cust_out,
    "order_ts": order_ts.strftime("%Y-%m-%d %H:%M:%S"),
    "status": status,
    "channel": channel,
    "currency": currency,
    "order_total": order_total_out,
})
late_batch = orders.sample(frac=0.005, random_state=SEED)  # duplicates that arrive in a second file

# COMMAND ----------

# Refunds: ~8% of all orders (completed, valid ones). 70% full, 30% partial. Refund date 1-45 days later.
eligible = (status == "completed") & ~bad_neg & ~bad_nocust
refunded = eligible & (rng.random(N_ORDERS) < 0.087)
ridx = np.flatnonzero(refunded)
full = rng.random(len(ridx)) < 0.7
pct = np.where(full, 1.0, rng.uniform(0.2, 0.6, len(ridx)))
refund_ts = order_ts[ridx] + pd.to_timedelta(rng.integers(1, 46, len(ridx)), unit="D") \
            + pd.to_timedelta(rng.integers(0, 86400, len(ridx)), unit="s")
refunds = pd.DataFrame({
    "refund_id": np.arange(7_000_001, 7_000_001 + len(ridx)),
    "order_id": order_id[ridx],
    "refund_ts": refund_ts.strftime("%Y-%m-%d %H:%M:%S"),
    "refund_amount": np.round(order_total[ridx] * pct, 2),
    "reason": rng.choice(["damaged", "wrong_item", "not_as_described", "changed_mind", "late_delivery"], len(ridx)),
})

# COMMAND ----------

# Write files to the landing zone
customers.to_csv(f"{LANDING}/customers/customers_initial.csv", index=False)
upd.to_csv(f"{LANDING}/customers/customers_updates.csv", index=False)
products.to_csv(f"{LANDING}/products/products.csv", index=False)
orders.to_csv(f"{LANDING}/orders/orders_main.csv", index=False)
late_batch.to_csv(f"{LANDING}/orders/orders_late_batch.csv", index=False)
order_items.to_csv(f"{LANDING}/order_items/order_items.csv", index=False)
refunds.to_json(f"{LANDING}/refunds/refunds.json", orient="records", lines=True)
fx_rates.to_csv(f"{LANDING}/fx_rates/fx_rates.csv", index=False)
fiscal_calendar.to_csv(f"{LANDING}/fiscal_calendar/fiscal_calendar.csv", index=False)

summary = {
    "customers": len(customers), "customer_updates": len(upd), "products": len(products),
    "orders": len(orders), "duplicate_orders": len(late_batch), "order_items": len(order_items),
    "refunds": len(refunds), "refund_rate": round(len(refunds) / N_ORDERS, 4),
    "bad_negative_total": int(bad_neg.sum()), "bad_missing_customer": int(bad_nocust.sum()),
    "test_accounts": int(is_test.sum()), "deleted_customers": int(is_deleted.sum()),
}
print(summary)