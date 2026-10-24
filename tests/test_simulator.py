import copy
from datetime import date
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.sim.incidents import DEFAULT_CONFIG
from app.sim.simulator import Simulator

ROOT = Path(__file__).resolve().parent.parent


def test_same_seed_gives_identical_tables():
    a = Simulator(seed=7).run()
    b = Simulator(seed=7).run()
    assert a[2]["tables"] == b[2]["tables"] and a[1] == b[1]
    assert Simulator(seed=8).run()[2]["tables"] != a[2]["tables"]


def test_default_volume_and_referential_integrity():
    t, _, _ = Simulator().run()
    assert 1000 <= len(t["pos_tickets"]) <= 1600
    tickets = {r["ticket_id"] for r in t["pos_tickets"]}
    assert all(r["ticket_id"] in tickets for r in t["ticket_items"])
    assert all(r["ticket_id"] in tickets for r in t["plate_returns"])
    assert len({r["ticket_id"] for r in t["pos_tickets"]}) == len(t["pos_tickets"])
    assert {r["event_type"] for r in t["table_events"]} >= {"seated", "ordered", "delivered", "reset"}
    assert all(1 <= r["rating"] <= 5 for r in t["reviews"])


def test_no_table_double_booked():
    t, _, _ = Simulator().run()
    by_table: dict = {}
    for r in t["pos_tickets"]:
        by_table.setdefault((r["business_date"], r["table_id"]), []).append((r["opened_at"], r["closed_at"]))
    for spans in by_table.values():
        spans.sort()
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))


def test_i1_overload_is_detectable_from_tables_alone():
    """The injected staffing overload must be visible without reading ground truth."""
    t, gt, _ = Simulator().run()
    d = gt["incidents"][0]["metric_delta"]["order_to_delivery_min"]
    assert d["n_affected"] >= 20 and d["affected"] - d["baseline"] >= 5
    shifts = [s for s in t["shifts"] if s["role"] == "server" and s["section_id"] == "B"]
    overloaded = {(s["business_date"], s["staff_id"]) for s in shifts if s["tables_assigned"] == 7}
    assert overloaded and all(d >= "2026-09-21" for d, _ in overloaded)  # onset is in the roster
    # the dose-response segment (all parties served at 7 tables/server) clears the verifier's n >= 30
    dinner_7 = [p for p in t["pos_tickets"] if p["service"] == "dinner"
                and (p["business_date"], p["server_id"]) in overloaded]
    assert len(dinner_7) >= 30


def test_busser_incident_is_visible_in_the_roster():
    t, _, _ = Simulator().run()
    short = [s for s in t["shifts"] if s["role"] == "busser" and s["end_time"].endswith("T20:00:00")]
    assert short and all(s["business_date"] >= "2026-09-21" for s in short)


def test_i4_busser_shortage_slows_resets():
    _, gt, _ = Simulator().run()
    d = gt["incidents"][1]["metric_delta"]["table_reset_min"]
    assert d["affected"] > 1.5 * d["baseline"]


def test_arrival_multiplier_reduces_covers_on_resolved_date():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["incidents"][-1]["params"]["walkin_multiplier"] = 0.0
    t, gt, _ = Simulator(cfg).run()
    rainy = gt["incidents"][-1]["resolved_dates"][0]
    counts: dict = {}
    for r in t["pos_tickets"]:
        counts[r["business_date"]] = counts.get(r["business_date"], 0) + 1
    other_sats = [v for k, v in counts.items() if k != rainy and date.fromisoformat(k).weekday() == 5]
    assert counts[rainy] < 0.8 * (sum(other_sats) / len(other_sats))


def test_incidents_change_only_via_config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["incidents"] = []
    _, gt, _ = Simulator(cfg).run()
    assert gt["incidents"] == []


def test_agent_side_packages_never_import_ground_truth():
    banned = re.compile(r"ground_truth|app\.sim|from app import sim")
    for pkg in ("agent", "adapters", "worldmodel"):
        for f in (ROOT / "app" / pkg).glob("**/*.py"):
            assert not banned.search(f.read_text()), f"{f} references ground truth / simulator"
