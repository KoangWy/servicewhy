"""Metric catalog: the one place a metric formula lives (Investigator, Verifier and scorecard import it).

SQL is written once and rendered per dialect: `spark` for the Zetaris federated surface (Spark SQL over
`<source>.<table>` names) and `sqlite` for the keyless local store used in tests. Every metric is
computed over a per-party view that joins POS tickets and table events (PostgreSQL) with the roster
(Parquet filestore) — the cross-store join is the point of the federation layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

WEEKDAY_NUM = {"sun": 1, "mon": 2, "tue": 3, "wed": 4, "thu": 5, "fri": 6, "sat": 7}  # Spark dayofweek
WINDOWS = [("11:00-13:00", 660, 780), ("13:00-15:00", 780, 900), ("15:00-17:00", 900, 1020),
           ("17:00-19:00", 1020, 1140), ("19:00-21:00", 1140, 1260), ("21:00-23:59", 1260, 1440)]


class Dialect:
    def __init__(self, name: str):
        if name not in ("spark", "sqlite"):
            raise ValueError(name)
        self.name = name

    def ts(self, x: str) -> str:
        return f"CAST({x} AS TIMESTAMP)" if self.name == "spark" else x

    def d(self, x: str) -> str:
        return f"CAST({x} AS DATE)" if self.name == "spark" else f"DATE({x})"

    def dlit(self, s: str) -> str:
        return f"DATE '{s}'" if self.name == "spark" else f"'{s}'"

    def num(self, x: str) -> str:
        return f"CAST({x} AS DOUBLE)" if self.name == "spark" else f"CAST({x} AS REAL)"

    def int(self, x: str) -> str:
        return f"CAST({x} AS INT)" if self.name == "spark" else f"CAST({x} AS INTEGER)"

    def mins(self, a: str, b: str) -> str:
        """Minutes from timestamp a to timestamp b."""
        if self.name == "spark":
            return f"(unix_timestamp({self.ts(b)}) - unix_timestamp({self.ts(a)})) / 60.0"
        return f"(julianday({b}) - julianday({a})) * 1440.0"

    def dow(self, x: str) -> str:
        return f"dayofweek({self.d(x)})" if self.name == "spark" else f"(CAST(strftime('%w', {x}) AS INTEGER) + 1)"

    def tod(self, x: str) -> str:
        """Minutes since midnight."""
        if self.name == "spark":
            return f"(hour({self.ts(x)}) * 60 + minute({self.ts(x)}))"
        return f"(CAST(strftime('%H', {x}) AS INTEGER) * 60 + CAST(strftime('%M', {x}) AS INTEGER))"


@dataclass(frozen=True)
class Metric:
    id: str
    label: str
    unit: str
    expr: str                 # per-row expression over the base view
    agg: str = "avg"          # avg | sum | count
    worse: str = "higher"     # direction that counts as a problem
    base: str = "party"       # party | review
    tod_col: str = "seated_tod"
    min_rel: float = 0.15     # smallest relative change treated as an effect
    min_abs: float = 0.0      # and smallest absolute change
    sources: tuple[str, ...] = field(default=("pos_tickets", "table_events", "shifts"))


METRICS: dict[str, Metric] = {m.id: m for m in [
    Metric("net_revenue", "net revenue per service day", "$", "revenue", agg="sum", worse="lower", min_rel=0.08,
           sources=("pos_tickets", "shifts")),
    Metric("parties", "parties per service day", "parties", "1", agg="count", worse="lower", min_rel=0.08,
           sources=("pos_tickets", "shifts")),
    Metric("net_revenue_per_party", "net revenue per party", "$", "revenue", worse="lower", min_rel=0.06,
           min_abs=2.0, sources=("pos_tickets", "ticket_items", "shifts")),
    Metric("comp_rate", "share of tickets with a comp", "share", "comped", min_rel=0.25, min_abs=0.02,
           sources=("pos_tickets", "shifts")),
    Metric("greet_min", "seated-to-greeted time", "min", "greet_min", min_abs=0.5),
    Metric("order_to_delivery_min", "order-to-delivery time", "min", "order_to_delivery_min", min_abs=2.0),
    Metric("kitchen_min", "kitchen fire-to-bump time", "min", "kitchen_min", min_abs=1.5),
    Metric("reset_min", "table reset time after guests leave", "min", "reset_min", tod_col="left_tod",
           min_abs=1.0),
    Metric("low_rating_share", "share of reviews rated 3 or lower", "share", "low_rating", base="review",
           min_rel=0.25, min_abs=0.05, sources=("reviews",)),
    Metric("review_count", "low-rated reviews by theme", "reviews", "1", agg="count", base="review",
           sources=("reviews",)),
]}

GROUP_DIMS = {  # dimension -> (base, SQL expression); never an individual staff id (SPEC §6 framing rule)
    "section": ("party", "section"),
    "tables_per_server": ("party", "tables_per_server"),
    "bussers_on": ("party", "bussers_on"),
    "business_date": ("any", "business_date"),
    "theme": ("review", "theme"),
}


def _window_case(col: str) -> str:
    return "CASE " + " ".join(f"WHEN {col} >= {lo} AND {col} < {hi} THEN '{lbl}'" for lbl, lo, hi in WINDOWS) + " END"


def party_view(dl: Dialect, pg: str, fs: str, *, revenue_from_items: bool = False) -> str:
    stages = ("seated", "greeted", "ordered", "fired", "bumped", "delivered", "paid", "left", "reset")
    pivots = ",\n    ".join(f"MAX(CASE WHEN event_type = '{s}' THEN occurred_at END) AS {s}_at" for s in stages)
    items = (f",\nit AS (SELECT ticket_id, SUM(CASE WHEN comp_reason IS NULL THEN {dl.num('qty')} * "
             f"{dl.num('unit_price')} ELSE 0 END) AS rev FROM {pg}.ticket_items GROUP BY ticket_id)"
             if revenue_from_items else "")
    revenue = "it.rev" if revenue_from_items else f"({dl.num('t.total')} - {dl.num('t.comp_total')})"
    return f"""ev AS (
  SELECT party_id, MAX(business_date) AS business_date,
    {pivots}
  FROM {pg}.table_events GROUP BY party_id),
bo AS (
  SELECT ev.party_id, COUNT(b.staff_id) AS bussers_on FROM ev
  JOIN {fs}.shifts b ON b.role = 'busser' AND {dl.d('b.business_date')} = {dl.d('ev.business_date')}
    AND {dl.ts('ev.left_at')} >= {dl.ts('b.start_time')} AND {dl.ts('ev.left_at')} < {dl.ts('b.end_time')}
  GROUP BY ev.party_id){items},
base AS (
  SELECT t.ticket_id, {dl.d('t.business_date')} AS business_date, t.service, {dl.dow('t.business_date')} AS dow,
    s.section_id AS section, {dl.int('s.tables_assigned')} AS tables_per_server,
    {revenue} AS revenue,
    CASE WHEN {dl.num('t.comp_total')} > 0 THEN 1.0 ELSE 0.0 END AS comped,
    {dl.tod('ev.seated_at')} AS seated_tod, {dl.tod('ev.left_at')} AS left_tod,
    {dl.mins('ev.seated_at', 'ev.greeted_at')} AS greet_min,
    {dl.mins('ev.ordered_at', 'ev.delivered_at')} AS order_to_delivery_min,
    {dl.mins('ev.fired_at', 'ev.bumped_at')} AS kitchen_min,
    {dl.mins('ev.left_at', 'ev.reset_at')} AS reset_min,
    COALESCE(bo.bussers_on, 0) AS bussers_on
  FROM {pg}.pos_tickets t
  JOIN ev ON ev.party_id = t.party_id
  JOIN {fs}.shifts s ON s.role = 'server' AND s.staff_id = t.server_id
    AND {dl.d('s.business_date')} = {dl.d('t.business_date')}
    AND {dl.ts('t.opened_at')} >= {dl.ts('s.start_time')} AND {dl.ts('t.opened_at')} <= {dl.ts('s.end_time')}
  LEFT JOIN bo ON bo.party_id = t.party_id{' LEFT JOIN it ON it.ticket_id = t.ticket_id' if revenue_from_items else ''})"""


def review_view(dl: Dialect, fs: str) -> str:
    return f"""base AS (
  SELECT {dl.d('business_date')} AS business_date, {dl.dow('business_date')} AS dow,
    {dl.int('rating')} AS rating, CASE WHEN {dl.int('rating')} <= 3 THEN 1.0 ELSE 0.0 END AS low_rating,
    text AS theme
  FROM {fs}.reviews)"""


@dataclass
class Segment:
    """Filters over the base view. Dates are ISO strings; weekdays are 'mon'..'sun'."""
    dates: list[str] | None = None
    weekdays: list[str] | None = None
    service: str | None = None
    section: str | None = None
    window: tuple[int, int] | None = None   # minutes since midnight, [lo, hi)
    low_rating_only: bool = False

    def where(self, dl: Dialect, metric: Metric) -> list[str]:
        w = []
        if self.dates is not None:
            w.append(f"business_date IN ({', '.join(dl.dlit(x) for x in self.dates)})")
        if self.weekdays:
            w.append(f"dow IN ({', '.join(str(WEEKDAY_NUM[x]) for x in self.weekdays)})")
        if metric.base == "party":
            if self.service:
                w.append(f"service = '{self.service}'")
            if self.section:
                w.append(f"section = '{self.section}'")
            if self.window:
                w.append(f"{metric.tod_col} >= {self.window[0]} AND {metric.tod_col} < {self.window[1]}")
        if metric.base == "review" and self.low_rating_only:
            w.append("low_rating = 1.0")
        return w


def _agg(metric: Metric) -> str:
    return {"avg": f"AVG({metric.expr})", "sum": f"SUM({metric.expr})", "count": "COUNT(*)"}[metric.agg]


def group_expr(dim: str, metric: Metric) -> str:
    if dim == "window":
        return _window_case(metric.tod_col)
    return GROUP_DIMS[dim][1]


def build_query(metric_id: str, dl: Dialect, pg: str, fs: str, segment: Segment, *,
                groups: dict[str, str] | None = None, raw: bool = False, independent: bool = False) -> str:
    """One federated SELECT. `groups` maps output column -> SQL expression (or a dimension name).

    raw=True returns per-row values (the Verifier's independent recomputation path); independent=True
    also switches revenue to a ticket_items-derived formulation so the re-query shares no aggregate
    with the original.
    """
    m = METRICS[metric_id]
    view = (party_view(dl, pg, fs, revenue_from_items=independent) if m.base == "party" else review_view(dl, fs))
    cols = [(name, group_expr(e, m) if (e in GROUP_DIMS or e == "window") else e) for name, e in (groups or {}).items()]
    where = segment.where(dl, m) + [f"{m.expr} IS NOT NULL"] if m.expr not in ("1",) else segment.where(dl, m)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    sel = ", ".join(f"{e} AS {n}" for n, e in cols)
    if raw:
        return f"WITH {view}\nSELECT {sel + ', ' if sel else ''}{m.expr} AS v FROM base{where_sql}"
    gb = (" GROUP BY " + ", ".join(e for _, e in cols)) if cols else ""
    return (f"WITH {view}\nSELECT {sel + ', ' if sel else ''}{_agg(m)} AS value, COUNT(*) AS n "
            f"FROM base{where_sql}{gb}")


def period_case(focus: list[str], baseline: list[str], dl: Dialect) -> str:
    f = ", ".join(dl.dlit(x) for x in focus)
    b = ", ".join(dl.dlit(x) for x in baseline)
    return f"CASE WHEN business_date IN ({f}) THEN 'focus' WHEN business_date IN ({b}) THEN 'baseline' END"


def as_float(v: Any) -> float | None:
    """Zetaris REST returns filestore columns (and some aggregates) as strings."""
    if v is None or v == "":
        return None
    return float(v)
