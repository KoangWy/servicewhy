"""Investigator: executes query plans only through the data-access adapter and records contrasts.

Every result becomes an EvidenceItem in the World Model with provenance (source, query, rows, values,
n) and a contrast: focus vs baseline, or worst group vs the rest along one dimension (section =
cross-section, tables_per_server = dose-response, bussers_on = staffing level, window = time of day).
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from app.agent.scope import Scope
from app.metrics import METRICS, Dialect, Metric, Segment, as_float, build_query, period_case

ROW_LIMIT = 20000
CONTRAST_TYPES = {"section": "cross_section", "tables_per_server": "dose_response", "bussers_on": "staffing_level",
                  "window": "time_window", "theme": "composition"}
MIN_GROUP_N = 15  # worst group is chosen among groups at least this large when any exist


class Investigator:
    name = "Investigator"
    role = "Runs federated queries through Zetaris and turns results into contrast-backed evidence"

    def __init__(self, data, *, pg: str, fs: str, trace, ingest):
        self.data, self.pg, self.fs, self.trace, self.ingest = data, pg, fs, trace, ingest
        self.dl = Dialect(getattr(data, "dialect", "spark"))
        self.channel = getattr(data, "channel", "Zetaris federated SQL (REST)")

    # ---- data access -------------------------------------------------------------------------------
    def _query(self, sql: str, *, purpose: str, agent: str = "Investigator", retry: int = 0) -> list[dict]:
        rows = self.data.query(sql, limit=ROW_LIMIT)
        self.trace.emit("query", agent, "federated_query", input_summary=purpose,
                        output_summary=f"{len(rows)} rows via {self.channel}", query=sql, rows_used=len(rows),
                        retry_count=retry)
        return rows

    def as_of(self) -> tuple[str, str]:
        rows = self._query(f"SELECT MIN(business_date) AS first_date, MAX(business_date) AS last_date "
                           f"FROM {self.pg}.pos_tickets", purpose="find the data's date range")
        return str(rows[0]["first_date"])[:10], str(rows[0]["last_date"])[:10]

    def _source(self, m: Metric) -> str:
        pg = [t for t in m.sources if t in ("pos_tickets", "ticket_items", "table_events")]
        fs = [t for t in m.sources if t in ("shifts", "plate_returns", "reviews")]
        tables = (["table_events"] if m.base == "party" else []) + pg
        parts = ([f"{'+'.join(dict.fromkeys(tables))} ({self.pg})"] if pg or m.base == "party" else []) + \
                ([f"{'+'.join(fs)} ({self.fs})"] if fs else [])
        return " x ".join(parts) + f" via {self.channel}"

    # ---- plans -------------------------------------------------------------------------------------
    def spec(self, plan: dict, scope: Scope) -> dict[str, Any]:
        f = dict(plan.get("filters") or {})
        return {"metric": plan["metric"], "contrast": plan["contrast"], "dim": plan.get("dim"),
                "focus": scope.focus, "baseline": scope.baseline, "weekdays": scope.weekdays,
                "service": f.get("service", scope.service), "section": scope.section, "window": scope.window,
                "low_rating_only": bool(f.get("low_rating_only")), "descriptive": bool(plan.get("descriptive"))}

    def _segment(self, spec: dict, dates: list[str]) -> Segment:
        # a cross-section or dose-response contrast needs the other sections as its comparison group
        section = None if spec.get("dim") in ("section", "tables_per_server") else spec["section"]
        return Segment(dates=dates, weekdays=spec["weekdays"], service=spec["service"], section=section,
                       window=tuple(spec["window"]) if spec["window"] else None,
                       low_rating_only=spec["low_rating_only"])

    def sql_for(self, spec: dict, *, raw: bool = False, independent: bool = False) -> str:
        m = METRICS[spec["metric"]]
        if spec["contrast"] == "compare":
            groups = {"grp": period_case(spec["focus"], spec["baseline"], self.dl)}
            if m.agg in ("sum", "count"):
                groups["day"] = "business_date"
            seg = self._segment(spec, spec["focus"] + spec["baseline"])
        else:
            groups = {"g": spec["dim"]}
            seg = self._segment(spec, spec["focus"])
        return build_query(m.id, self.dl, self.pg, self.fs, seg, groups=groups, raw=raw, independent=independent)

    def compute(self, spec: dict, rows: list[dict], *, raw: bool = False) -> dict[str, Any]:
        """Turn aggregate rows (or raw per-row values) into a contrast. Shared with the Verifier's V1."""
        m = METRICS[spec["metric"]]
        if raw:
            rows = _aggregate_raw(rows, m, spec)
        if spec["contrast"] == "compare":
            out = {}
            for side in ("focus", "baseline"):
                rs = [r for r in rows if r["grp"] == side]
                n = int(sum(as_float(r["n"]) for r in rs))
                if m.agg == "avg":
                    v = (sum(as_float(r["value"]) * as_float(r["n"]) for r in rs) / n) if n else None
                else:  # per-day totals averaged over the days in the window
                    v = mean(as_float(r["value"]) for r in rs) if rs else None
                out[side] = (v, n, len(rs))
            (v, n, _), (b, nb, _) = out["focus"], out["baseline"]
            return {"value": v, "baseline": b, "n": n, "n_baseline": nb, "group": None, "groups": []}
        groups = [{"group": _label(r["g"]), "value": as_float(r["value"]), "n": int(as_float(r["n"]))}
                  for r in rows if r["g"] is not None]
        if m.agg == "count":  # composition: share of all rows
            total = sum(g["n"] for g in groups) or 1
            for g in groups:
                g["value"] = g["n"] / total
        groups.sort(key=lambda g: g["group"])
        big = [g for g in groups if g["n"] >= MIN_GROUP_N] or groups
        if not big:
            return {"value": None, "baseline": None, "n": 0, "n_baseline": 0, "group": None, "groups": groups}
        pick = max if (m.worse == "higher" or m.agg == "count") else min
        named = spec.get("section") if spec.get("dim") == "section" else None
        if spec.get("dim") == "tables_per_server":  # dose-response: the highest load is the treated group
            worst = max(groups, key=lambda g: float(g["group"]))
        elif spec.get("dim") == "bussers_on":  # fewest bussers actually rostered (0 = after the last shift)
            worst = min([g for g in big if g["group"] != "0"] or big, key=lambda g: float(g["group"]))
        else:
            worst = next((g for g in groups if g["group"] == named), None) or pick(big, key=lambda g: g["value"])
        rest = [g for g in groups if g is not worst]
        nb = sum(g["n"] for g in rest)
        b = (sum(g["value"] * g["n"] for g in rest) / nb) if (nb and m.agg != "count") else None
        return {"value": worst["value"], "baseline": b, "n": worst["n"], "n_baseline": nb, "group": worst["group"],
                "groups": groups}

    def run_plan(self, hypothesis_id: str, plan: dict, scope: Scope, *, retry: int = 0) -> dict[str, Any]:
        spec = self.spec(plan, scope)
        m = METRICS[spec["metric"]]
        sql = self.sql_for(spec)
        rows = self._query(sql, purpose=f"{m.label}: {_contrast_text(spec, scope)}", retry=retry)
        res = self.compute(spec, rows)
        ev = {**res, **_effect(m, res, spec), "metric": m.id, "metric_label": m.label, "unit": m.unit,
              "contrast_type": "period_vs_baseline" if spec["contrast"] == "compare" else CONTRAST_TYPES[spec["dim"]],
              "contrast": _contrast_text(spec, scope), "descriptive": spec["descriptive"], "spec": spec,
              "rows_used": len(rows), "segment": scope.label, "level": scope.level}
        eid = self.ingest.ingest_evidence(hypothesis_id, source=self._source(m), query=sql, metric=m.id,
                                          value=_round(ev["value"]), contrast=ev["contrast"], n=ev["n"],
                                          agent_id="investigator",
                                          **{k: v for k, v in ev.items() if k not in ("metric", "value", "contrast", "n")})
        self.trace.emit("evidence", self.name, "record_evidence", input_summary=f"{hypothesis_id} - {m.id}",
                        output_summary=_evidence_text(eid, ev), retry_count=retry,
                        data={"evidence_id": eid, "hypothesis_id": hypothesis_id, "metric": m.id,
                              "value": _round(ev["value"]), "baseline": _round(ev["baseline"]), "n": ev["n"],
                              "n_baseline": ev["n_baseline"], "group": ev["group"], "supports": ev["supports"],
                              "contrast_type": ev["contrast_type"]})
        return {"id": eid, **ev, "source": self._source(m), "query": sql}

    def investigate(self, hypothesis: dict, scope: Scope, *, retry: int = 0) -> list[dict[str, Any]]:
        return [self.run_plan(hypothesis["wm_id"], p, scope, retry=retry) for p in hypothesis["plans"]]


def _aggregate_raw(rows: list[dict], m: Metric, spec: dict) -> list[dict]:
    """Python-side aggregation of raw rows: the independent half of the Verifier's re-query."""
    if spec["contrast"] == "compare":
        key = lambda r: (r["grp"], r.get("day") if m.agg != "avg" else None)  # noqa: E731
    else:
        key = lambda r: (r["g"], None)  # noqa: E731
    acc: dict = defaultdict(list)
    for r in rows:
        acc[key(r)].append(as_float(r["v"]))
    out = []
    for (g, day), vs in acc.items():
        value = {"avg": mean(vs), "sum": sum(vs), "count": len(vs)}[m.agg]
        out.append({"grp": g, "g": g, "day": day, "value": value, "n": len(vs)})
    return out


def _label(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


def _round(v: Any, nd: int = 3) -> Any:
    return round(v, nd) if isinstance(v, float) else v


def _effect(m: Metric, res: dict, spec: dict) -> dict[str, Any]:
    v, b = res["value"], res["baseline"]
    if v is None or b is None or spec["descriptive"]:
        return {"delta": None, "rel": None, "supports": False}
    delta = v - b
    rel = (delta / b) if b else None
    bad = (delta if m.worse == "higher" else -delta)
    bad_rel = (bad / abs(b)) if b else 0.0
    return {"delta": round(delta, 3), "rel": None if rel is None else round(rel, 4),
            "supports": bool(bad_rel >= m.min_rel and bad >= m.min_abs)}


def _contrast_text(spec: dict, scope: Scope) -> str:
    if spec["contrast"] == "compare":
        return f"{scope.label} vs baseline of {len(spec['baseline'])} matching days"
    return {"section": "worst section vs the other sections", "tables_per_server": "highest-load bucket vs lower tables-per-server buckets",
            "bussers_on": "fewest bussers on duty vs more bussers", "window": "slowest time window vs the rest of service",
            "theme": "share of low-rated reviews by complaint theme"}[spec["dim"]] + f", {scope.label}"


def fmt(v: Any, unit: str) -> str:
    if v is None:
        return "n/a"
    if unit == "$":
        return f"${v:,.2f}"
    if unit == "share":
        return f"{100 * v:.1f}%"
    if unit == "min":
        return f"{v:.1f} min"
    return f"{v:.1f}"


def _evidence_text(eid: str, ev: dict) -> str:
    g = f" [{ev['group']}]" if ev["group"] else ""
    return (f"{eid}: {ev['metric']}{g} {fmt(ev['value'], ev['unit'])} vs {fmt(ev['baseline'], ev['unit'])} "
            f"(n={ev['n']} vs {ev['n_baseline']}) supports={ev['supports']}")
