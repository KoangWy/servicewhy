"""Deterministic restaurant simulator: same seed -> identical tables (hash per table in the manifest).

1 venue, 20 tables in 4 sections, 4 section servers per service + 2 bussers, 5 weeks, lunch + dinner peaks.
Incidents come only from the config; ground truth is returned separately and is never loaded by the agent.
Each incident may carry `active_from` / `active_to` dates (inclusive): a staffing change has an onset, so
before/after contrasts exist in the data.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import date, datetime, timedelta
from typing import Any

from .incidents import DEFAULT_CONFIG

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SECTIONS = ["A", "B", "C", "D"]
TABLES = [(f"T{i + 1:02d}", SECTIONS[i // 5]) for i in range(20)]
SERVICES = {"lunch": (11 * 60, 14 * 60 + 30), "dinner": (17 * 60, 21 * 60 + 30)}
PEAKS = {"lunch": 12 * 60 + 40, "dinner": 19 * 60 + 30}
MENU = {"food": [("Margherita", 14.0), ("Ribeye", 32.0), ("Salmon", 26.0), ("Risotto", 19.0), ("Burger", 17.0)],
        "beverage": [("Lemonade", 4.5), ("House Red", 9.0), ("Espresso", 3.5)],
        "dessert": [("Tiramisu", 8.0), ("Gelato", 6.5)]}
BASE_TPS = (4, 4, 5, 5, 6)
BASE_PARTIES = {"lunch": (12, 20), "dinner": (20, 32)}  # (weekday, fri/sat/sun)
EXTRAS_ELASTICITY = 1.2  # items per cover fall as f ** -elasticity when service slows


def _hm(minutes: float, d: date) -> datetime:
    return datetime(d.year, d.month, d.day) + timedelta(minutes=minutes)


def _window(s: str) -> tuple[int, int]:
    a, b = s.split("-")
    return int(a[:2]) * 60 + int(a[3:]), int(b[:2]) * 60 + int(b[3:])


def _active(incident: dict, d: date) -> bool:
    lo, hi = incident.get("active_from"), incident.get("active_to")
    return (lo is None or d >= date.fromisoformat(lo)) and (hi is None or d <= date.fromisoformat(hi))


def content_manifest(tables: dict[str, list[dict]]) -> dict[str, dict]:
    """Per table: row count + sha256 over the sorted canonical-JSON rows (content hash, not file bytes)."""
    out = {}
    for name, rows in tables.items():
        lines = sorted(json.dumps(r, sort_keys=True, separators=(",", ":"), default=str) for r in rows)
        out[name] = {"rows": len(rows), "sha256": hashlib.sha256("\n".join(lines).encode()).hexdigest()}
    return out


class Simulator:
    def __init__(self, config: dict[str, Any] | None = None, *, seed: int | None = None, days: int = 35,
                 start: date = date(2026, 8, 31)):
        self.cfg = config or DEFAULT_CONFIG
        self.seed = self.cfg["seed"] if seed is None else seed
        self.cv = self.cfg["noise"]["duration_cv"]
        self.days, self.start = days, start
        self.rng = random.Random(self.seed)
        self.t: dict[str, list[dict]] = {k: [] for k in
                                         ("pos_tickets", "ticket_items", "table_events", "shifts",
                                          "plate_returns", "reviews")}
        self.gt_obs: dict[str, list] = {"i1_delay": [], "i1_base": [], "i4_reset": [], "i4_base": []}
        self.rainy: list[date] = []

    # ---- helpers -------------------------------------------------------------------------------
    def _dur(self, mean: float) -> float:
        sigma = math.sqrt(math.log(1 + self.cv ** 2))
        return mean * self.rng.lognormvariate(-sigma ** 2 / 2, sigma)

    def _incidents(self, typ: str, d: date | None = None):
        return [i for i in self.cfg["incidents"] if i["type"] == typ and (d is None or _active(i, d))]

    def _server_incident(self, d: date, section: str):
        for i in self._incidents("staffing_overload", d):
            p = i["params"]
            if p["role"] == "server" and section in p["sections"] and WEEKDAYS[d.weekday()] in p["weekdays"]:
                return i
        return None

    def _busser_incident(self, d: date):
        for i in self._incidents("staffing_overload", d):
            p = i["params"]
            if p["role"] == "busser" and WEEKDAYS[d.weekday()] in p["weekdays"]:
                return i
        return None

    # ---- run -----------------------------------------------------------------------------------
    def run(self) -> tuple[dict[str, list[dict]], dict[str, Any], dict[str, Any]]:
        dates = [self.start + timedelta(days=n) for n in range(self.days)]
        for i in self._incidents("arrival_multiplier"):
            want = i["params"]["dates"]
            # "auto" = the last Saturday in range, i.e. inside the most recent reporting week
            self.rainy = ([[d for d in dates if d.weekday() == 5][-1]] if want == "auto"
                          else [date.fromisoformat(x) for x in want])
        for d in dates:
            for service in SERVICES:
                self._service(d, service)
        manifest = {"seed": self.seed, "days": self.days, "start": self.start.isoformat(),
                    "tables": content_manifest(self.t)}
        return self.t, self._ground_truth(), manifest

    def _service(self, d: date, service: str) -> None:
        wd = WEEKDAYS[d.weekday()]
        rng, lo, hi = self.rng, *SERVICES[service]
        tps = {}
        for s in SECTIONS:
            inc = self._server_incident(d, s) if service == "dinner" else None
            tps[s] = inc["params"]["tables_per_server"] if inc else rng.choice(BASE_TPS)
        sid = {s: f"S{n + 1}" for n, s in enumerate(SECTIONS)}
        for s in SECTIONS:
            self.t["shifts"].append({"shift_id": f"SH-{d:%m%d}-{service[0]}-{sid[s]}", "staff_id": sid[s],
                                     "role": "server", "section_id": s, "business_date": d.isoformat(),
                                     "start_time": _hm(lo - 30, d).isoformat(), "end_time": _hm(hi + 60, d).isoformat(),
                                     "tables_assigned": tps[s]})
        bi = self._busser_incident(d) if service == "dinner" else None
        for n_b, b in enumerate(("B1", "B2")):
            # under a busser incident only `staff_on` bussers remain once the window opens
            off = bool(bi) and n_b >= bi["params"]["staff_on"]
            end = _window(bi["params"]["window"])[0] if off else hi + 60
            self.t["shifts"].append({"shift_id": f"SH-{d:%m%d}-{service[0]}-{b}", "staff_id": b, "role": "busser",
                                     "section_id": None, "business_date": d.isoformat(),
                                     "start_time": _hm(lo - 30, d).isoformat(), "end_time": _hm(end, d).isoformat(),
                                     "tables_assigned": 20 if (bi and not off) else 10})
        weekend = wd in ("fri", "sat", "sun")
        n = max(4, round(rng.gauss(BASE_PARTIES[service][weekend], 2.5)))
        free_at = {t: 0.0 for t, _ in TABLES}
        arrivals = sorted(min(hi, max(lo, rng.gauss(PEAKS[service], 55))) for _ in range(n))
        for k, arr in enumerate(arrivals):
            walk_in = rng.random() < 0.6
            if d in self.rainy and walk_in and rng.random() > self._incidents("arrival_multiplier")[0]["params"]["walkin_multiplier"]:
                continue  # walk-in lost to the decoy; see ground truth
            self._party(d, service, k, arr, free_at, tps, sid, bi)

    def _party(self, d, service, k, arr, free_at, tps, sid, busser_inc) -> None:
        rng = self.rng
        table, section = min(TABLES, key=lambda t: max(free_at[t[0]], arr))
        seated = max(free_at[table], arr)
        covers = rng.choice((1, 2, 2, 2, 3, 4, 4, 5, 6))
        pid = f"P-{d:%m%d}-{service[0]}-{k:03d}"
        tid = f"TK-{d:%m%d}-{service[0]}-{k:03d}"
        server = sid[section]
        inc = self._server_incident(d, section) if service == "dinner" else None
        in_win = bool(inc) and _window(inc["params"]["window"])[0] <= seated < _window(inc["params"]["window"])[1]
        eff_tps = tps[section] if (inc is None or in_win) else rng.choice(BASE_TPS)
        f = 1 + 0.25 * max(0, eff_tps - 4)
        greeted = seated + self._dur(2.0 * f)
        ordered = greeted + self._dur(5.0 * f)
        fired = ordered + self._dur(1.5 * f)
        bumped = fired + self._dur(12.0)
        delivered = bumped + self._dur(4.0 * f ** 2)
        paid = delivered + self._dur(28 + 4 * covers) + self._dur(4.0 * f)
        left = paid + self._dur(3.0)
        b_in = busser_inc is not None and _window(busser_inc["params"]["window"])[0] <= left < _window(busser_inc["params"]["window"])[1]
        reset = left + self._dur(4.0 * (2.2 if b_in else 1.0))
        free_at[table] = reset
        for name, ts in (("seated", seated), ("greeted", greeted), ("ordered", ordered), ("fired", fired),
                         ("bumped", bumped), ("delivered", delivered), ("paid", paid), ("left", left), ("reset", reset)):
            self.t["table_events"].append({"event_id": f"{tid}-{name}", "business_date": d.isoformat(),
                                           "table_id": table, "party_id": pid, "event_type": name,
                                           "occurred_at": _hm(ts, d).isoformat(),
                                           "server_id": server if name not in ("left", "reset") else None})
        total = comp_total = 0.0
        late = (delivered - bumped) > 10.0
        worst = max((greeted - seated, "greet"), (delivered - ordered, "food"), (reset - left, "reset"))[1]
        # slow service costs spend: guests skip extra rounds and desserts
        for li in range(max(1, round(covers * rng.uniform(1.2, 2.0) / f ** EXTRAS_ELASTICITY))):
            cat = rng.choices(("food", "beverage", "dessert"), (6, 3, 1))[0]
            name, price = rng.choice(MENU[cat])
            qty = rng.choice((1, 1, 1, 2))
            comp = "cold_food" if (cat == "food" and late and rng.random() < 0.55) else None
            line = round(price * qty, 2)
            total += line
            comp_total += line if comp else 0.0
            self.t["ticket_items"].append({"line_id": f"{tid}-L{li:02d}", "ticket_id": tid, "item_name": name,
                                           "category": cat, "qty": qty, "unit_price": price,
                                           "fired_at": _hm(fired, d).isoformat(), "bumped_at": _hm(bumped, d).isoformat(),
                                           "delivered_at": _hm(delivered, d).isoformat(), "comp_reason": comp})
            if rng.random() < 0.25:
                self.t["plate_returns"].append({"return_id": f"{tid}-R{li:02d}", "business_date": d.isoformat(),
                                                "ticket_id": tid, "item_name": name,
                                                "leftover_share": round(rng.uniform(0.0, 0.6), 2)})
        self.t["pos_tickets"].append({"ticket_id": tid, "business_date": d.isoformat(), "service": service,
                                      "table_id": table, "party_id": pid, "server_id": server, "covers": covers,
                                      "opened_at": _hm(seated, d).isoformat(), "closed_at": _hm(left, d).isoformat(),
                                      "total": round(total, 2), "comp_total": round(comp_total, 2)})
        if rng.random() < 0.35:
            excess = max(0.0, (delivered - ordered) - 20) + max(0.0, (greeted - seated) - 4)
            rating = int(min(5, max(1, round(4.6 - 0.18 * excess + rng.gauss(0, 0.6)))))
            text = {"food": "Food took a long time to arrive.", "greet": "Waited a while before anyone greeted us.",
                    "reset": "Had to wait for a table to be cleared."}[worst] if rating <= 3 else "Lovely evening, thank you."
            self.t["reviews"].append({"review_id": f"RV-{tid}", "business_date": d.isoformat(), "rating": rating,
                                      "text": text})
        if inc and service == "dinner" and section in inc["params"]["sections"]:
            (self.gt_obs["i1_delay"] if in_win else self.gt_obs["i1_base"]).append(delivered - ordered)
        if busser_inc is not None and service == "dinner":
            (self.gt_obs["i4_reset"] if b_in else self.gt_obs["i4_base"]).append(reset - left)

    def _ground_truth(self) -> dict[str, Any]:
        mean = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
        out = []
        for i in self.cfg["incidents"]:
            rec = {"id": i["id"], "type": i["type"], "params": i["params"]}
            if i["id"] == "I1":
                rec["metric_delta"] = {"order_to_delivery_min": {"affected": mean(self.gt_obs["i1_delay"]),
                                                                 "baseline": mean(self.gt_obs["i1_base"]),
                                                                 "n_affected": len(self.gt_obs["i1_delay"])}}
            elif i["id"] == "I4":
                rec["metric_delta"] = {"table_reset_min": {"affected": mean(self.gt_obs["i4_reset"]),
                                                           "baseline": mean(self.gt_obs["i4_base"]),
                                                           "n_affected": len(self.gt_obs["i4_reset"])}}
            elif i["id"] == "D2":
                rec["resolved_dates"] = [d.isoformat() for d in self.rainy]
            out.append(rec)
        return {"seed": self.seed, "incidents": out}
