"""Record the SAMPLE_MODE bundle from real runs of the configured backends.

  python scripts/seed_sample.py            # canned questions + one report + one drill-down
  python scripts/seed_sample.py --out DIR  # write somewhere else (tests)

On the QA machine (DATA_BACKEND=zetaris, MODEL_MODE=record) this produces the FULL-mode exemplar;
on a keyless machine (DATA_BACKEND=local, MODEL_MODE=fake|replay) it produces a provisional bundle
whose `recorded_with` says so. Secrets are masked in traces at write time.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from app.config import Settings, load_dotenv  # noqa: E402
from app.report import generator  # noqa: E402
from app.runtime import orchestrator as make_orchestrator  # noqa: E402

QUESTIONS = ROOT / "app" / "scorecard" / "questions.yaml"


def record(settings: Settings, out: Path, *, with_report: bool = True) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    orch = make_orchestrator(settings)
    bundle = {"recorded_with": None, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "seed": settings.seed, "synthetic_data": True, "runs": [], "drilldowns": {}}
    used = []

    def keep(resp: dict) -> None:
        used.append(resp["run_id"])
        src = settings.logs_dir / f"trace-{resp['run_id']}.jsonl"
        if src.exists():
            shutil.copy(src, out / src.name)

    for q in yaml.safe_load(QUESTIONS.read_text(encoding="utf-8")):
        resp = orch.run(q["question"], run_id=f"sample-{q['id'].lower()}", context=q.get("context"))
        keep(resp)
        bundle["runs"].append({"id": q["id"], "question": q["question"], "context": q.get("context"), "response": resp})
        if resp["status"] == "success" and bundle["recorded_with"] is None:
            bundle["recorded_with"] = {"data": resp["output"]["mode"]["data"], "model": resp["output"]["mode"]["model"],
                                       "model_mode": resp["output"]["mode"]["model_mode"]}
    demo = bundle["runs"][0]["response"]
    if demo["status"] == "success" and demo["output"]["findings"]:
        f = demo["output"]["findings"][0]
        override = {"intent": "explain", "target_metric": f["effect_size"]["metric"],
                    "slots": demo["output"]["plan"]["slots"], "hypotheses": [f["library_id"]], "missing_data": None,
                    "reason": "drill-down on one finding", "policy_notes": [f"Drill-down on {f['id']}"]}
        dd = orch.run(f"Why: {f['cause_hypothesis']}?", run_id="sample-drilldown", plan_override=override,
                      parent_finding=f["id"])
        keep(dd)
        bundle["drilldowns"][f["id"]] = dd
    if with_report:
        as_of = demo.get("output", {}).get("data_as_of")
        if as_of:
            rep = generator.generate(orch, generator.default_period(as_of), report_id="sample-report")
            for r in rep.pop("_runs"):
                keep(r)
                bundle["runs"].append({"id": r["run_id"], "question": r["question"], "context": None, "response": r})
            bundle["report"] = rep
    (out / "sample_bundle.json").write_text(json.dumps(bundle, indent=1, default=str), encoding="utf-8", newline="\n")
    return bundle


EXAMPLES = {"Q1": "example_1", "Q8": "example_2", "Q2": "example_3"}  # demo, non-cause probe, abstention


def write_examples(bundle: dict, root: Path = ROOT) -> list[Path]:
    """Three judge-facing input/output pairs, taken from the recorded runs (Technical Execution Guide)."""
    written = []
    for r in bundle["runs"]:
        name = EXAMPLES.get(r["id"])
        if not name:
            continue
        inp = {"run_id": r["response"]["run_id"], "input": {"query": r["question"]}, "options": {"sample_mode": False}}
        if r.get("context"):
            inp["input"]["context"] = r["context"]
        for folder, doc in (("input_examples", inp), ("output_examples", r["response"])):
            p = root / folder / f"{name}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
            written.append(p)
    return written


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Record the SAMPLE_MODE bundle")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    s = Settings.from_env()
    if s.sample_mode:
        print("refusing to record while SAMPLE_MODE=true", file=sys.stderr)
        return 2
    out = args.out or s.sample_dir
    b = record(s, out)
    if args.out is None:
        write_examples(b)
    ok = sum(r["response"]["status"] == "success" for r in b["runs"])
    print(json.dumps({"out": str(out), "runs": len(b["runs"]), "succeeded": ok, "recorded_with": b["recorded_with"]}))
    return 0 if ok == len(b["runs"]) else 1


if __name__ == "__main__":
    sys.exit(main())
