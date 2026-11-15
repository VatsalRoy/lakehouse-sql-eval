"""Prompt templates for the four experimental conditions.

A_raw          : table + column names and types only
B_comments     : A + data-catalog comments (src/catalog/column_comments.yaml)
C_metric_view  : A + the metric view definitions (with synonyms / agent metadata)
C_nosyn        : A + the metric view definitions with synonyms, display names and comments removed (H3 ablation)

Plain Python (no Spark) so it can be unit-tested locally.
"""
import copy
import hashlib
import json
import re

import yaml

CONDITIONS = ["A_raw", "B_comments", "C_metric_view", "C_nosyn"]

RULES = """Rules:
- Write exactly ONE Databricks SQL SELECT query that answers the question.
- Use fully qualified names (catalog.schema.table).
- Return only the columns needed to answer: a single value -> one column; a breakdown -> the grouping column(s) first, then the value(s).
- Return ratios as fractions (0.08 means 8%) unless the question asks for a percentage.
- Only use LIMIT when the question asks for a top-N or a single item.
- Respond with the SQL inside one ```sql code block and nothing else."""

TEMPLATE = """You are an expert analytics engineer writing SQL for a retail company's Databricks lakehouse.

{{context}}

""" + RULES + """

Question: {{question}}
"""

TEMPLATE_VERSION = hashlib.sha1(TEMPLATE.encode()).hexdigest()[:8]

METRIC_VIEW_GUIDE = """How to query a metric view:
  SELECT <dimension>, MEASURE(<measure>) AS <alias>
  FROM {catalog}.gold.<metric_view>
  WHERE <filters on dimensions>
  GROUP BY <dimension>
- Wrap every measure in MEASURE(). Filter and group only by the view's dimensions.
- Never SELECT * from a metric view and never join a metric view to other tables.
- Use the metric views for business metrics (revenue, sales, orders, customers, refunds, AOV).
- Use the raw tables only for things the metric views cannot answer (single records, catalog counts, raw record counts)."""

AGENT_METADATA = ("synonyms", "display_name", "comment", "format")


def strip_metadata(spec: dict) -> dict:
    """Same ablation as create_metric_views.py: drop text written for humans/agents, keep the logic."""
    s = copy.deepcopy(spec)
    s.pop("comment", None)
    for section in ("dimensions", "measures"):
        for item in s.get(section, []):
            for key in AGENT_METADATA:
                item.pop(key, None)
    return s


def schema_ddl(schema: dict, catalog: str, comments: dict | None = None) -> str:
    """schema = {table: [(column, type), ...]}; comments = parsed column_comments.yaml or None."""
    blocks = []
    for table, cols in schema.items():
        tdoc = (comments or {}).get("tables", {}).get(table, {})
        header = f"TABLE {catalog}.gold.{table}"
        if comments and tdoc.get("comment"):
            header += f"  -- {tdoc['comment']}"
        lines = []
        for i, (col, typ) in enumerate(cols):
            sep = "," if i < len(cols) - 1 else ""
            line = f"  {col} {typ}{sep}"
            cdoc = tdoc.get("columns", {}).get(col) if comments else None
            if cdoc:
                line += f"  -- {cdoc}"
            lines.append(line)
        blocks.append(header + "\n(\n" + "\n".join(lines) + "\n)")
    return "\n\n".join(blocks)


def metric_view_context(metric_views: dict, catalog: str, nosyn: bool) -> str:
    """metric_views = {view_name: yaml_text_with_catalog_filled_in}."""
    parts = []
    for name, text in metric_views.items():
        spec = yaml.safe_load(text)
        if nosyn:
            spec = strip_metadata(spec)
            name = f"{name}_nosyn"
        body = yaml.safe_dump(spec, sort_keys=False, width=1000)
        parts.append(f"METRIC VIEW {catalog}.gold.{name}\n```yaml\n{body}```")
    return "\n\n".join(parts) + "\n\n" + METRIC_VIEW_GUIDE.format(catalog=catalog)


def build_context(condition: str, schema: dict, catalog: str, comments: dict, metric_views: dict) -> str:
    if condition == "A_raw":
        return "## Tables\n" + schema_ddl(schema, catalog)
    if condition == "B_comments":
        return "## Tables (with data catalog descriptions)\n" + schema_ddl(schema, catalog, comments)
    if condition in ("C_metric_view", "C_nosyn"):
        return ("## Tables\n" + schema_ddl(schema, catalog)
                + "\n\n## Metric views (governed business metrics)\n"
                + metric_view_context(metric_views, catalog, nosyn=condition == "C_nosyn"))
    raise ValueError(f"unknown condition {condition}")


def condition_template(context: str) -> str:
    """Template with the context baked in; only {{question}} remains. This is what goes in the Prompt Registry."""
    return TEMPLATE.replace("{{context}}", context)


def render(template: str, question: str) -> str:
    return template.replace("{{question}}", question)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha1(prompt.encode()).hexdigest()[:12]


_SQL_BLOCK = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def response_text(response) -> str | None:
    """Some reasoning models return a JSON list of content blocks ([{"type": "reasoning"...}, {"type": "text", "text": ...}]).
    Keep only the final text blocks; plain strings pass through unchanged."""
    if response is None:
        return None
    if not isinstance(response, str):
        response = json.dumps(response, default=str)
    s = response.strip()
    if s.startswith("[") and '"type"' in s:
        try:
            blocks = json.loads(s)
            texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
            if texts:
                return "\n".join(texts)
        except ValueError:
            pass
    return response


def extract_sql(response) -> str | None:
    """Pull the SQL out of the model's reply. Takes the LAST ```sql block (reasoning models may draft first)."""
    response = response_text(response)
    if not response:
        return None
    blocks = _SQL_BLOCK.findall(response)
    sql = blocks[-1] if blocks else response
    sql = sql.strip().rstrip(";").strip()
    m = re.search(r"\b(WITH|SELECT)\b", sql, re.IGNORECASE)   # drop any prose before the query
    return sql[m.start():] if m else (sql or None)



# ----------------------------------------------------------------------------- LLM judge 
JUDGE_TEMPLATE = """You are a senior analytics engineer reviewing SQL that a colleague wrote for a retail company's Databricks lakehouse.

{{context}}

Question: {{question}}

Proposed SQL:
```sql
{{sql}}
```

Does this SQL correctly answer the question, the way the business would expect? Check the tables, joins, filters,
time periods and the meaning of any business terms - not only whether the query would run.
Reply in exactly this format:
VERDICT: CORRECT or VERDICT: INCORRECT
REASON: <one sentence>"""

JUDGE_VERSION = hashlib.sha1(JUDGE_TEMPLATE.encode()).hexdigest()[:8]


def render_judge(context: str, question: str, sql: str) -> str:
    return (JUDGE_TEMPLATE.replace("{{context}}", context)
            .replace("{{question}}", question).replace("{{sql}}", sql or ""))