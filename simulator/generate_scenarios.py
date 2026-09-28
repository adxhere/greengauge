#!/usr/bin/env python3
"""
Generate every scenario the meter emulator can switch between during a demo.

  python generate_scenarios.py --out ../data --days 7

Skips scenarios that already exist unless --force is given.
"""
import argparse
import json
from pathlib import Path

import yaml

from simulator import simulate, summarise, parse_faults

SCENARIOS = {
    "healthy": "none",
    "faulty": "all",
    "leak": "leak",
    "idle": "idle",
    "pf": "pf",
    "motor": "motor",
}


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(here.parent / "data"))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--start", default="2026-09-07")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--spec", default=str(here / "plant_spec.yaml"))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    spec = yaml.safe_load(Path(args.spec).read_text())
    out_root = Path(args.out)
    for name, faults in SCENARIOS.items():
        out = out_root / name
        if (out / "incomer.csv").exists() and not args.force:
            print(f"[skip] {name} already exists")
            continue
        out.mkdir(parents=True, exist_ok=True)
        active = parse_faults(faults)
        machines, incomer, production = simulate(spec, args.days, args.start, active, args.seed)
        machines.to_csv(out / "machines.csv", index=False)
        incomer.to_csv(out / "incomer.csv", index=False)
        production.to_csv(out / "production.csv", index=False)
        summary = summarise(spec, incomer, machines, active, args.days)
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        print(f"[done] {name:8s} {summary['total_kwh']:>9} kWh  {summary['kwh_per_piece']} kWh/piece")


if __name__ == "__main__":
    main()
