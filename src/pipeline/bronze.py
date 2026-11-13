# Bronze layer: ingest raw files from the landing Volume, exactly as they arrived.
# Auto Loader ("cloudFiles") picks up only NEW files on each run, so re-runs are cheap.
# Every column is kept as a string; typing and cleaning happen in silver.

from pyspark import pipelines as dp
from pyspark.sql import functions as F

CATALOG = spark.conf.get("catalog", "workspace")
LANDING = f"/Volumes/{CATALOG}/bronze/landing"

SOURCES = {
    "customers": "csv",
    "products": "csv",
    "orders": "csv",
    "order_items": "csv",
    "refunds": "json",
    "fx_rates": "csv",
    "fiscal_calendar": "csv",
}


def make_bronze_table(source: str, fmt: str):
    @dp.table(
        name=f"{CATALOG}.bronze.{source}_raw",
        comment=f"Raw {source} files from {LANDING}/{source}/, loaded incrementally with Auto Loader. All columns are strings.",
    )
    def bronze():
        reader = (
            spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", fmt)
            .option("cloudFiles.inferColumnTypes", "false")
        )
        if fmt == "csv":
            reader = reader.option("header", "true")
        return (
            reader.load(f"{LANDING}/{source}/")
            .withColumn("_ingested_at", F.current_timestamp())
            .withColumn("_source_file", F.col("_metadata.file_path"))
        )

    return bronze


for source, fmt in SOURCES.items():
    make_bronze_table(source, fmt)