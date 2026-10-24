"""Incident configuration (spec §4.5): the only place incidents are defined.

Plain dict so the simulator has no YAML dependency; the shape mirrors sim/incidents.yaml in the spec.
"""
DEFAULT_CONFIG = {
    "seed": 20261024,
    "noise": {"duration_cv": 0.25},
    "incidents": [
        {"id": "I1", "type": "staffing_overload",
         "params": {"role": "server", "sections": ["B"], "weekdays": ["fri", "sat"],
                    "window": "19:00-21:00", "tables_per_server": 7},
         "active_from": "2026-09-21"},
        {"id": "I4", "type": "staffing_overload",
         "params": {"role": "busser", "weekdays": ["thu", "fri", "sat"],
                    "window": "20:00-22:00", "staff_on": 1},
         "active_from": "2026-09-21"},
        {"id": "D2", "type": "arrival_multiplier",
         "params": {"dates": "auto", "walkin_multiplier": 0.9, "revenue_share_target": 0.33}},
    ],
}
