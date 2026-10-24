"""Turn the Planner's slots into concrete focus/baseline dates, and widen them on a verifier retry.

Period semantics (SPEC D11): weekly periods (Mon-Sun); a weekday question compares against the same
weekday over the previous four weeks; a period question compares against the previous period.
Widening (level 0 -> 2) is how the loop answers a small-sample block: more of the same nights, never
a different question.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from app.metrics import Segment

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MAX_LEVEL = 2


@dataclass
class Scope:
    focus: list[str]
    baseline: list[str]
    weekdays: list[str] | None = None
    service: str | None = None
    section: str | None = None
    window: tuple[int, int] | None = None
    level: int = 0
    kind: str = "period"
    slots: dict = field(default_factory=dict)
    as_of: str = ""

    def segment(self, dates: list[str], **override) -> Segment:
        seg = Segment(dates=dates, weekdays=self.weekdays, service=self.service, section=self.section,
                      window=self.window)
        for k, v in override.items():
            setattr(seg, k, v)
        return seg

    @property
    def label(self) -> str:
        parts = []
        if self.service:
            parts.append(f"at {self.service}")
        if self.window:
            parts.append(f"{_hhmm(self.window[0])}-{_hhmm(self.window[1])}")
        if self.section:
            parts.append(f"in section {self.section}")
        when = _dates_label(self.focus, self.kind)
        return (" ".join(parts) + " " if parts else "") + when

    def to_dict(self) -> dict:
        return {"focus": self.focus, "baseline": self.baseline, "weekdays": self.weekdays, "service": self.service,
                "section": self.section, "window": self.window, "level": self.level, "label": self.label,
                "as_of": self.as_of}


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _dates_label(dates: list[str], kind: str) -> str:
    ds = sorted(date.fromisoformat(d) for d in dates)
    if kind in ("period", "weekend") and len(ds) > 1:
        return f"from {ds[0]:%a %d %b} to {ds[-1]:%a %d %b}"
    return "on " + ", ".join(f"{d:%a %d %b}" for d in reversed(ds))


def parse_window(s: str | None) -> tuple[int, int] | None:
    if not s:
        return None
    a, b = s.split("-")
    to_m = lambda x: int(x.split(":")[0]) * 60 + int(x.split(":")[1])  # noqa: E731
    return to_m(a), to_m(b)


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def resolve(slots: dict, as_of: str, first: str, level: int = 0) -> Scope:
    end, start = date.fromisoformat(as_of), date.fromisoformat(first)
    iso = lambda ds: [d.isoformat() for d in ds if start <= d <= end]  # noqa: E731
    weekday, period = slots.get("weekday"), slots.get("period")
    common = dict(service=slots.get("service"), section=slots.get("section"),
                  window=parse_window(slots.get("window")), level=level, slots=dict(slots), as_of=as_of)
    if slots.get("start") and slots.get("end"):  # explicit report period vs the previous period(s)
        a, b = date.fromisoformat(slots["start"]), date.fromisoformat(slots["end"])
        length = (b - a).days + 1
        span = lambda k0, k1: [a - timedelta(days=length * k) + timedelta(days=i)  # noqa: E731
                               for k in range(k0, k1) for i in range(length)]
        return Scope(focus=iso(span(0, level + 1)), baseline=iso(span(level + 1, 2 * (level + 1))),
                     weekdays=[weekday] if weekday else None, kind="period", **common)
    if slots.get("date") or (weekday and period != "weekend"):
        if slots.get("date"):
            anchor = date.fromisoformat(slots["date"])
        else:
            anchor = end - timedelta(days=(end.weekday() - WEEKDAYS.index(weekday)) % 7)
        same = [anchor - timedelta(weeks=k) for k in range(6)]
        n_focus = level + 1
        return Scope(focus=iso(same[:n_focus]), baseline=iso(same[n_focus:n_focus + 4]),
                     weekdays=[WEEKDAYS[anchor.weekday()]], kind="weekday", **common)
    wk = _week_start(end)
    if period == "last_week":
        wk -= timedelta(weeks=1)
    if period == "weekend":
        fri = wk + timedelta(days=4)
        ends = [fri - timedelta(weeks=k) for k in range(6)]
        n_focus = level + 1
        days = lambda fs: [f + timedelta(days=i) for f in fs for i in range(3)]  # noqa: E731
        return Scope(focus=iso(days(ends[:n_focus])), baseline=iso(days(ends[n_focus:n_focus + 4])),
                     weekdays=None, kind="weekend", **common)
    n_focus = level + 1
    weeks = [wk - timedelta(weeks=k) for k in range(6)]
    days = lambda ws: [w + timedelta(days=i) for w in ws for i in range(7)]  # noqa: E731
    # a period comparison is against the previous period of the same length
    base_weeks = weeks[n_focus:n_focus + n_focus] if slots.get("compare_previous") else weeks[n_focus:n_focus + 4]
    return Scope(focus=iso(days(weeks[:n_focus])), baseline=iso(days(base_weeks)),
                 weekdays=[weekday] if weekday else None, kind="period", **common)


def widen(scope: Scope, first: str) -> Scope | None:
    if scope.level >= MAX_LEVEL:
        return None
    return resolve(scope.slots, scope.as_of, first, scope.level + 1)


def with_window(scope: Scope, window: tuple[int, int] | None) -> Scope:
    return replace(scope, window=window)
