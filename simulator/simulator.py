#!/usr/bin/env python3
"""
GreenGauge plant simulator.

Generates minute-level electrical data for a simulated SME foundry, with
switchable faults: air leaks, idle running, APFC failure, motor degradation.

Outputs (in --out):
  machines.csv    one row per machine per minute (what clamp-on CTs would see)
  incomer.csv     one row per minute at the main incomer (what the plant meter sees)
  production.csv  one row per shift (what an operator would log)
  summary.json    headline numbers for the run

Examples:
  python simulator.py --days 7 --faults all  --out output/faulty
  python simulator.py --days 7 --faults none --out output/healthy
  python simulator.py --days 7 --faults leak,idle
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

SQRT3 = math.sqrt(3)
ALL_FAULTS = ["air_leak", "idle_running", "apfc_failure", "motor_degradation"]
FAULT_ALIASES = {"leak": "air_leak", "idle": "idle_running",
                 "pf": "apfc_failure", "motor": "motor_degradation"}


# ---------------------------------------------------------------- helpers
def hm(s: str) -> int:
    """'06:30' -> minutes after midnight."""
    h, m = map(int, s.split(":"))
    return h * 60 + m


def in_windows(minute_of_day: int, windows) -> bool:
    """True if minute_of_day falls in any [start, end) window; windows may wrap midnight."""
    for a, b in windows:
        if a <= b:
            if a <= minute_of_day < b:
                return True
        elif minute_of_day >= a or minute_of_day < b:
            return True
    return False


def tan_phi(pf: float) -> float:
    return math.tan(math.acos(min(max(pf, 0.05), 1.0)))


class Schedule:
    def __init__(self, spec):
        self.working_days = set(spec["working_days"])
        self.shifts = [dict(name=s["name"], start=hm(s["start"]), end=hm(s["end"]),
                            brk=(hm(s["break_start"]), hm(s["break_end"])))
                       for s in spec["shifts"]]
        self.first_start = min(s["start"] for s in self.shifts)
        self.last_end = max(s["end"] for s in self.shifts)

    def at(self, ts):
        """Return (shift_name or None, in_break) for a timestamp."""
        if ts.weekday() not in self.working_days:
            return None, False
        mod = ts.hour * 60 + ts.minute
        for s in self.shifts:
            if s["start"] <= mod < s["end"]:
                return s["name"], s["brk"][0] <= mod < s["brk"][1]
        return None, False


def parse_faults(arg: str) -> set[str]:
    arg = arg.strip().lower()
    if arg == "all":
        return set(ALL_FAULTS)
    if arg in ("none", ""):
        return set()
    out = set()
    for f in arg.split(","):
        f = FAULT_ALIASES.get(f.strip(), f.strip())
        if f not in ALL_FAULTS:
            raise SystemExit(f"Unknown fault '{f}'. Choose from {ALL_FAULTS} or aliases {list(FAULT_ALIASES)}")
        out.add(f)
    return out


# ---------------------------------------------------------------- simulation
def simulate(spec: dict, days: int, start: str, active: set[str], seed: int):
    rng = np.random.default_rng(seed)
    plant = spec["plant"]
    tz = plant.get("timezone", "Asia/Kolkata")
    idx = pd.date_range(start, periods=days * 1440, freq="min", tz=tz)
    n = len(idx)
    sched = Schedule(spec["schedule"])
    fs = spec["faults"]
    fur, comp, motors, light = spec["furnace"], spec["compressor"], spec["motors"], spec["lighting_aux"]
    amb = spec["ambient"]

    names = [fur["name"], comp["name"]] + [m["name"] for m in motors] + [light["name"]]
    col = {nm: i for i, nm in enumerate(names)}
    M = len(names)

    kw = np.zeros((M, n))
    kvar = np.zeros((M, n))
    status = np.full((M, n), "off", dtype=object)
    tags = [[[] for _ in range(n)] for _ in range(M)]
    unb = np.zeros((M, n))
    loaded_s = np.full(n, np.nan)
    pieces = np.zeros(n, dtype=int)
    shift_col = np.full(n, "", dtype=object)
    producing = np.zeros(n, dtype=bool)
    temp = np.zeros(n)

    # persistent per-machine current imbalance (every real motor has a little)
    base_unb = rng.uniform(0.5, 1.5, size=M)
    pattern = rng.normal(size=(M, 3))
    pattern -= pattern.mean(axis=1, keepdims=True)
    pattern /= np.abs(pattern).max(axis=1, keepdims=True)

    def fault_on(f: str, day_float: float) -> bool:
        return f in active and day_float >= fs[f].get("start_day", 0)

    # nightly "left it on" decisions, drawn once per night
    night_draw: dict = {}
    daily_temp_offset: dict = {}

    # state
    fphase, felapsed, flen, fcharge, pour_left = None, 0, 0, 0.0, 0
    pressure = sum(comp["pressure_band_bar"]) / 2
    cloaded = True
    lo, hi = comp["pressure_band_bar"]
    pump_cool = 0
    burst_on = {m["name"]: False for m in motors}

    for t, ts in enumerate(idx):
        day_f = t / 1440.0
        mod = ts.hour * 60 + ts.minute
        shift, brk = sched.at(ts)
        prod = shift is not None and not brk
        shift_col[t] = shift or ""
        producing[t] = prod

        d = ts.date()
        if d not in daily_temp_offset:
            daily_temp_offset[d] = rng.normal(0, 1.0)
        mean_t = (amb["min_c"] + amb["max_c"]) / 2
        amp_t = (amb["max_c"] - amb["min_c"]) / 2
        temp[t] = mean_t + amp_t * math.cos(2 * math.pi * (ts.hour + ts.minute / 60 - amb["hottest_hour"]) / 24) \
            + daily_temp_offset[d] + rng.normal(0, 0.2)

        # is this an after-hours minute following a working day?
        night_owner = (ts - pd.Timedelta(hours=6))
        after_hours = (shift is None and night_owner.weekday() in sched.working_days
                       and (mod >= sched.last_end or mod < sched.first_start))
        left_on = False
        if after_hours and fault_on("idle_running", day_f):
            key = night_owner.date()
            if key not in night_draw:
                night_draw[key] = rng.random() < fs["idle_running"]["overnight_probability"]
            left_on = night_draw[key]
        overnight_list = set(fs["idle_running"]["overnight_left_on"]) if left_on else set()

        # ---------------- induction furnace
        i = col[fur["name"]]
        if prod:
            if fphase is None or felapsed >= flen:
                if fphase == "melt":
                    fphase, flen = "pour", fur["pour_minutes"]
                    pour_left = int(fcharge * fur["casting_yield"] / plant["avg_casting_kg"])
                else:
                    fcharge = rng.uniform(*fur["charge_kg"])
                    fphase = "melt"
                    flen = max(1, round(fur["melt_minutes"] * fcharge / fur["reference_charge_kg"]))
                felapsed = 0
            if fphase == "melt":
                kw[i, t] = fur["rated_kw"] * rng.uniform(0.95, 1.0)
            else:
                kw[i, t] = fur["pour_kw"] * rng.uniform(0.9, 1.1)
                remaining = flen - felapsed
                k = pour_left if remaining <= 1 else int(round(pour_left / remaining))
                pieces[t] += k
                pour_left -= k
            status[i, t] = "running"
            felapsed += 1
        elif brk:
            kw[i, t] = fur["holding_kw"] * rng.uniform(0.9, 1.1)
            status[i, t] = "idle"
        else:
            fphase = None
        kvar[i, t] = kw[i, t] * tan_phi(fur["pf"])

        # ---------------- air compressor (pressure-band load/unload model, 10 s sub-steps)
        i = col[comp["name"]]
        leak_fault = fault_on("air_leak", day_f)
        leak = fs["air_leak"]["leak_m3_min"] if leak_fault else comp["healthy_leak_m3_min"]
        comp_left_on = comp["name"] in overnight_list
        if shift is not None or comp_left_on:
            demand = leak
            if prod:
                demand += comp["production_demand_m3_min"] * max(0.0, 1 + rng.normal(0, comp["demand_noise"]))
            secs = 0
            for _ in range(6):
                if cloaded:
                    secs += 10
                    pressure += (comp["capacity_m3_min"] - demand) * 1.013 / comp["system_volume_m3"] / 6
                else:
                    pressure -= demand * 1.013 / comp["system_volume_m3"] / 6
                if pressure >= hi:
                    cloaded = False
                elif pressure <= lo:
                    cloaded = True
            frac = secs / 60
            tf = 1 + comp["temp_coeff_per_c"] * (temp[t] - 25)
            p_load = frac * comp["load_kw"] * tf
            p_unload = (1 - frac) * comp["unload_kw"]
            kw[i, t] = p_load + p_unload
            kvar[i, t] = p_load * tan_phi(comp["load_pf"]) + p_unload * tan_phi(comp["unload_pf"])
            loaded_s[t] = secs
            status[i, t] = "running" if frac > 0 else "idle"
            if leak_fault:
                tags[i][t].append("air_leak")
            if comp_left_on:
                tags[i][t].append("idle_running")
        else:
            pressure, cloaded = (lo + hi) / 2, True

        # ---------------- motors
        furnace_on = kw[col[fur["name"]], t] > 0
        for m in motors:
            i = col[m["name"]]
            run_kw = m["rated_kw"] * m["load_factor"]
            p = 0.0
            if m["name"] in overnight_list:
                p, status[i, t] = m["idle_kw"] or run_kw, "idle"
                tags[i][t].append("idle_running")
            elif m["runs"] == "furnace":
                if furnace_on:
                    pump_cool = 30
                if furnace_on or pump_cool > 0:
                    p, status[i, t] = run_kw, "running"
                    if not furnace_on:
                        pump_cool -= 1
            elif m["runs"] == "shift":
                if shift is not None:
                    p, status[i, t] = run_kw, "running"
            elif m["runs"] == "intermittent":
                if prod:
                    p_off = 1 / 8                      # mean burst length 8 min
                    p_on = m["duty"] / (1 - m["duty"]) * p_off
                    if burst_on[m["name"]]:
                        burst_on[m["name"]] = rng.random() > p_off
                    else:
                        burst_on[m["name"]] = rng.random() < p_on
                    if burst_on[m["name"]]:
                        p, status[i, t] = run_kw, "running"
                elif brk and fault_on("idle_running", day_f) and m["name"] in fs["idle_running"]["break_idlers"]:
                    p, status[i, t] = m["idle_kw"], "idle"
                    tags[i][t].append("idle_running")
                else:
                    burst_on[m["name"]] = False

            unb[i, t] = base_unb[i]
            if p > 0:
                p *= 1 + rng.normal(0, 0.03)
                md = fs["motor_degradation"]
                if m["name"] == md["machine"] and fault_on("motor_degradation", day_f):
                    sev = min(1.0, (day_f - md["start_day"]) / md["days_to_severe"])
                    p *= 1 + md["max_current_rise_pct"] / 100 * sev * 0.5
                    unb[i, t] = base_unb[i] + sev * (md["max_imbalance_pct"] - base_unb[i])
                    tags[i][t].append("motor_degradation")
            kw[i, t] = p
            kvar[i, t] = p * tan_phi(m["pf"])

        # ---------------- lighting & auxiliaries
        i = col[light["name"]]
        kw[i, t] = (light["shift_kw"] if shift is not None else light["night_kw"]) * rng.uniform(0.95, 1.05)
        kvar[i, t] = kw[i, t] * tan_phi(light["pf"])
        status[i, t] = "running"

    # furnace, compressor and lighting get their baseline imbalance too
    for nm in (fur["name"], comp["name"], light["name"]):
        unb[col[nm], :] = base_unb[col[nm]]

    # ---------------- incomer: APFC, voltage, currents
    total_kw = kw.sum(axis=0)
    total_kvar = kvar.sum(axis=0)
    apfc = spec["apfc"]
    step = apfc["step_kvar"]
    tgt_tan = tan_phi(apfc["target_pf"])
    cap = np.zeros(n)
    apfc_fault = np.zeros(n, dtype=bool)
    for t in range(n):
        avail = apfc["max_kvar"]
        if fault_on("apfc_failure", t / 1440.0):
            avail *= 1 - fs["apfc_failure"]["capacity_lost"]
            apfc_fault[t] = True
        need = max(0.0, total_kvar[t] - total_kw[t] * tgt_tan)
        cap[t] = min(round(need / step) * step, math.floor(avail / step) * step)  # nearest step, capped by working steps
    net_kvar = total_kvar - cap
    kva = np.sqrt(total_kw ** 2 + net_kvar ** 2)
    pf_in = np.where(kva > 0, total_kw / np.maximum(kva, 1e-9), 1.0)

    v_nom = plant["supply_voltage_v"]
    volt = v_nom * (1 - 0.025 * total_kw / plant["contract_demand_kva"] + rng.normal(0, 0.003, n))

    def phase_currents(kva_arr, unb_arr, pat):
        i_avg = kva_arr * 1000 / (SQRT3 * volt)
        noise = rng.normal(0, 0.003, size=(3, n))
        return [i_avg * (1 + unb_arr / 100 * pat[k] + noise[k]) for k in range(3)]

    # ---------------- assemble machine table
    frames = []
    for nm, i in col.items():
        m_kva = np.sqrt(kw[i] ** 2 + kvar[i] ** 2)
        ia, ib, ic = phase_currents(m_kva, unb[i], pattern[i])
        frames.append(pd.DataFrame({
            "timestamp": idx, "machine": nm,
            "kw": kw[i].round(3), "kvar": kvar[i].round(3),
            "ia": ia.round(2), "ib": ib.round(2), "ic": ic.round(2),
            "status": status[i],
            "loaded_s": loaded_s if nm == comp["name"] else np.nan,
            "fault_label": [";".join(x) for x in tags[i]],
        }))
    machines = pd.concat(frames, ignore_index=True).sort_values(["timestamp", "machine"])

    in_pat = np.array([0.6, -1.0, 0.4])
    ia, ib, ic = phase_currents(kva, np.full(n, 1.0), in_pat)
    incomer = pd.DataFrame({
        "timestamp": idx,
        "kw": total_kw.round(3), "kvar": net_kvar.round(3), "kva": kva.round(3),
        "pf": pf_in.round(4), "voltage": volt.round(1),
        "ia": ia.round(2), "ib": ib.round(2), "ic": ic.round(2),
        "apfc_kvar": cap, "ambient_c": temp.round(2),
        "shift": shift_col, "producing": producing, "pieces": pieces,
        "fault_label": np.where(apfc_fault, "apfc_failure", ""),
    })

    prod_df = incomer[incomer["shift"] != ""].copy()
    prod_df["date"] = prod_df["timestamp"].dt.date
    production = (prod_df.groupby(["date", "shift"], as_index=False)["pieces"].sum()
                  .rename(columns={"pieces": "pieces_logged"}))

    return machines, incomer, production


# ---------------------------------------------------------------- summary
def summarise(spec, incomer, machines, active, days):
    tar = spec["tariff"]
    kwh_min = incomer["kw"] / 60
    mods = incomer["timestamp"].dt.hour * 60 + incomer["timestamp"].dt.minute
    peak_w = [(hm(a), hm(b)) for a, b in tar["peak_hours"]]
    off_w = [(hm(a), hm(b)) for a, b in tar["offpeak_hours"]]
    mult = np.array([1 + tar["peak_surcharge_pct"] / 100 if in_windows(m, peak_w)
                     else 1 - tar["offpeak_rebate_pct"] / 100 if in_windows(m, off_w) else 1.0
                     for m in mods])
    energy_cost = float((kwh_min * tar["energy_inr_per_kwh"] * mult).sum())

    total_kwh = float(kwh_min.sum())
    total_kvah = float((incomer["kva"] / 60).sum())
    pieces = int(incomer["pieces"].sum())
    md = incomer.set_index("timestamp")["kva"].resample("30min").mean()
    contract = spec["plant"]["contract_demand_kva"]
    demand_cost = max(float(md.max()), 0.9 * contract) * tar["demand_inr_per_kva_month"] * days / 30

    per_machine = (machines.groupby("machine")["kw"].sum() / 60).round(1).to_dict()
    idle_mask = machines["fault_label"].str.contains("idle_running", na=False)
    idle_kwh = float(machines.loc[idle_mask, "kw"].sum() / 60)
    after_hours_kwh = float(kwh_min[incomer["shift"] == ""].sum())
    ef = tar["emission_factor_kg_per_kwh"]

    return {
        "faults_active": sorted(active),
        "days": days,
        "total_kwh": round(total_kwh, 1),
        "pieces": pieces,
        "kwh_per_piece": round(total_kwh / pieces, 2) if pieces else None,
        "avg_pf": round(total_kwh / total_kvah, 3) if total_kvah else None,
        "max_demand_kva_30min": round(float(md.max()), 1),
        "contract_demand_kva": contract,
        "demand_exceeded_intervals": int((md > contract).sum()),
        "energy_cost_inr": round(energy_cost),
        "demand_cost_inr": round(demand_cost),
        "cost_per_piece_inr": round((energy_cost + demand_cost) / pieces, 2) if pieces else None,
        "co2_tonnes": round(total_kwh * ef / 1000, 2),
        "kg_co2_per_piece": round(total_kwh * ef / pieces, 2) if pieces else None,
        "after_hours_kwh": round(after_hours_kwh, 1),
        "ground_truth_idle_running_kwh": round(idle_kwh, 1),
        "kwh_by_machine": per_machine,
    }


# ---------------------------------------------------------------- CLI
def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="GreenGauge SME foundry simulator")
    ap.add_argument("--spec", default=str(here / "plant_spec.yaml"))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--start", default="2026-09-07", help="start date (a Monday is best)")
    ap.add_argument("--faults", default="all",
                    help="all | none | comma list of: " + ",".join(ALL_FAULTS + list(FAULT_ALIASES)))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=None, help="output folder (default: output/<faulty|healthy|custom>)")
    args = ap.parse_args()

    spec = yaml.safe_load(Path(args.spec).read_text())
    active = parse_faults(args.faults)
    tag = "faulty" if active == set(ALL_FAULTS) else "healthy" if not active else "custom"
    out = Path(args.out) if args.out else here / "output" / tag
    out.mkdir(parents=True, exist_ok=True)

    print(f"Simulating {args.days} days | faults: {sorted(active) or 'none'} | seed {args.seed}")
    machines, incomer, production = simulate(spec, args.days, args.start, active, args.seed)
    summary = summarise(spec, incomer, machines, active, args.days)

    machines.to_csv(out / "machines.csv", index=False)
    incomer.to_csv(out / "incomer.csv", index=False)
    production.to_csv(out / "production.csv", index=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\nSaved to {out}")
    for k, v in summary.items():
        if k != "kwh_by_machine":
            print(f"  {k:32s} {v}")
    print("  kWh by machine:")
    for k, v in summary["kwh_by_machine"].items():
        print(f"    {k:30s} {v}")


if __name__ == "__main__":
    main()
