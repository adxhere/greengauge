"""
GreenGauge analytics engine.

Pure calculations on two DataFrames shaped like the database tables:
  inc: time, kw, kvar, kva, pf, energy_kwh, pieces_total, ambient_c, shift, producing
  mac: time, device, kw, kvar, ia, ib, ic, status, loaded_s

Nothing here touches the database, so every result can be tested against the
simulator's ground truth.
"""
from __future__ import annotations

import copy
import math
from functools import cached_property

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- helpers
def hm(s: str) -> int:
    h, m = map(int, s.split(":"))
    return h * 60 + m


def in_windows(mod: np.ndarray, windows) -> np.ndarray:
    mask = np.zeros(len(mod), dtype=bool)
    for a, b in windows:
        a, b = hm(a), hm(b)
        mask |= ((mod >= a) & (mod < b)) if a <= b else ((mod >= a) | (mod < b))
    return mask


def inr(x: float) -> str:
    """Indian-style rupee formatting: 123456.7 -> '₹1,23,457'."""
    neg, x = x < 0, abs(round(x))
    s = str(int(x))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-₹" if neg else "₹") + s


def duration_text(minutes: float) -> str:
    minutes = int(round(minutes))
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def r(x, nd=2):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def is_off(v) -> bool:
    """Rule value meaning 'must be off' (YAML turns a bare off/no into False)."""
    return v is False or str(v).strip().lower() in ("off", "no", "false", "stop")


def payback_months(capex: float, annual_savings: float):
    return r(capex / annual_savings * 12, 1) if annual_savings > 0 else None


# ---------------------------------------------------------------- engine
class Engine:
    def __init__(self, cfg: dict, inc: pd.DataFrame, mac: pd.DataFrame):
        cfg = copy.deepcopy(cfg)   # per-request tweaks must not leak into the shared config
        self.cfg = cfg
        self.site = cfg["site"]
        self.tar = cfg["tariff"]
        self.det = cfg["detection"]
        self.rec_cfg = cfg["recommendations"]
        tz = self.site.get("timezone", "Asia/Kolkata")

        inc = inc.sort_values("time").reset_index(drop=True).copy()
        inc["time"] = pd.to_datetime(inc["time"], utc=True)
        inc["local"] = inc["time"].dt.tz_convert(tz)
        inc["date"] = inc["local"].dt.date
        inc["shift"] = inc["shift"].fillna("").astype(str)
        inc["producing"] = inc["producing"].astype(bool)

        # energy and pieces per row from the cumulative meter registers (robust to missed polls)
        kwh = inc["energy_kwh"].diff()
        fallback = inc["kw"] / 60
        bad = kwh.isna() | (kwh < 0) | (kwh > fallback.abs() * 30 + 50)   # first row, counter reset, or junk
        inc["kwh"] = np.where(bad, fallback, kwh)
        inc["pieces"] = inc["pieces_total"].diff().fillna(0).clip(lower=0).astype(int)
        ratio = np.where(inc["kw"] > 0.5, inc["kva"] / inc["kw"].where(inc["kw"] > 0.5), np.nan)
        inc["kvah"] = np.where(np.isnan(ratio), inc["kva"] / 60, inc["kwh"] * ratio)

        # plant state per minute
        inc["state"] = np.where(inc["producing"], "production",
                                np.where(inc["shift"] != "", "break", "after_hours"))
        last_shift = inc["time"].where(inc["shift"] != "").ffill()
        inc["mins_since_shift"] = ((inc["time"] - last_shift).dt.total_seconds() / 60).fillna(1e9)

        # time-of-day tariff
        mod = (inc["local"].dt.hour * 60 + inc["local"].dt.minute).to_numpy()
        mult = np.ones(len(inc))
        mult[in_windows(mod, self.tar["peak_hours"])] = 1 + self.tar["peak_surcharge_pct"] / 100
        mult[in_windows(mod, self.tar["offpeak_hours"])] = 1 - self.tar["offpeak_rebate_pct"] / 100
        inc["rate"] = self.tar["energy_inr_per_kwh"] * mult
        inc["cost"] = inc["kwh"] * inc["rate"]
        self.inc = inc

        mac = mac.copy()
        mac["time"] = pd.to_datetime(mac["time"], utc=True)
        mac = mac.merge(inc[["time", "date", "local", "state", "mins_since_shift", "rate"]], on="time", how="inner")
        mac["kwh"] = mac["kw"] / 60
        mac["cost"] = mac["kwh"] * mac["rate"]
        self.mac = mac.sort_values(["device", "time"]).reset_index(drop=True)

        self.t_start = inc["time"].min()
        self.t_end = inc["time"].max()
        self.window_days = max((self.t_end - self.t_start).total_seconds() / 86400, 1 / 24)
        self.annual_factor = 365 / self.window_days
        self.avg_rate = float(inc["cost"].sum() / inc["kwh"].sum()) if inc["kwh"].sum() > 0 else self.tar["energy_inr_per_kwh"]
        self.ef = self.tar["emission_factor_kg_per_kwh"]

    # ------------------------------------------------------------ basic numbers
    def _totals(self, df: pd.DataFrame) -> dict:
        kwh, pieces, cost = float(df["kwh"].sum()), int(df["pieces"].sum()), float(df["cost"].sum())
        kvah = float(df["kvah"].sum())
        return {
            "kwh": r(kwh, 1), "pieces": pieces,
            "kwh_per_piece": r(kwh / pieces) if pieces else None,
            "energy_cost_inr": r(cost, 0),
            "cost_per_piece_inr": r(cost / pieces) if pieces else None,
            "co2_kg": r(kwh * self.ef, 1),
            "kg_co2_per_piece": r(kwh * self.ef / pieces) if pieces else None,
            "pf": r(kwh / kvah, 3) if kvah else None,
        }

    def period(self) -> dict:
        return {"start": self.inc["local"].min().isoformat(), "end": self.inc["local"].max().isoformat(),
                "days": r(self.window_days, 2)}

    @cached_property
    def overview(self) -> dict:
        daily = []
        for d, g in self.inc.groupby("date"):
            daily.append({"date": d.isoformat(), **self._totals(g)})
        return {"period": self.period(), "totals": self._totals(self.inc), "daily": daily,
                "kwh_by_machine": {k: r(v, 1) for k, v in self.mac.groupby("device")["kwh"].sum().items()}}

    # ------------------------------------------------------------ shifts & baseline
    @cached_property
    def shifts(self) -> pd.DataFrame:
        s = self.inc[self.inc["shift"] != ""]
        out = (s.groupby(["date", "shift"], as_index=False)
                .agg(start=("local", "min"), kwh=("kwh", "sum"), pieces=("pieces", "sum"),
                     ambient_c=("ambient_c", "mean"), minutes=("kwh", "size")))
        return out.sort_values("start").reset_index(drop=True)

    @cached_property
    def baseline(self) -> dict:
        """Regression baseline, IPMVP-style: shift energy = a + b*pieces + c*ambient."""
        sh = self.shifts[(self.shifts["pieces"] > 0) & (self.shifts["minutes"] >= 240)].copy()
        cutoff = self.inc["local"].min() + pd.Timedelta(days=self.det["baseline_days"])
        base, rep = sh[sh["start"] < cutoff], sh[sh["start"] >= cutoff]
        if len(base) < self.det["baseline_min_shifts"]:
            return {"status": "insufficient_data",
                    "message": f"Need {self.det['baseline_min_shifts']} complete shifts in the baseline period; "
                               f"have {len(base)}. Let the pipeline run longer."}

        X = np.column_stack([np.ones(len(base)), base["pieces"], base["ambient_c"]])
        y = base["kwh"].to_numpy()
        dof = len(base) - 3
        coef, model = None, "ratio"
        pieces_cv = float(base["pieces"].std() / base["pieces"].mean()) if base["pieces"].mean() else 0.0
        # a 3-term regression only makes sense if production varies enough between shifts
        # to separate fixed energy from per-piece energy; otherwise use the ratio model
        if dof >= 1 and pieces_cv >= 0.10:
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            model = "regression"
            # energy must rise with production; if it doesn't (shifts too similar to separate
            # the effects), use the simpler and more robust ratio model
            if coef[1] <= 0:
                coef = None
        if coef is None:
            coef = np.array([0.0, y.sum() / base["pieces"].sum(), 0.0])
            dof, model = max(len(base) - 1, 1), "ratio"
        fit = X @ coef
        rmse = math.sqrt(((y - fit) ** 2).sum() / dof)
        cv = rmse / y.mean() * 100

        def predict(df):
            return coef[0] + coef[1] * df["pieces"].to_numpy() + coef[2] * df["ambient_c"].to_numpy()

        series = []
        for part, df in (("baseline", base), ("reporting", rep)):
            for (_, row), p in zip(df.iterrows(), predict(df) if len(df) else []):
                series.append({"start": row["start"].isoformat(), "shift": row["shift"], "period": part,
                               "pieces": int(row["pieces"]), "actual_kwh": r(row["kwh"], 1),
                               "expected_kwh": r(p, 1)})

        result = {
            "status": "ok", "model": model,
            "model_note": ("Energy = fixed + per-piece + per-degree terms, fitted on the baseline shifts."
                           if model == "regression" else
                           "Production was too steady to separate fixed and per-piece energy, so the baseline "
                           "is energy per piece in the baseline period."),
            "equation": {"fixed_kwh_per_shift": r(coef[0], 1), "kwh_per_piece": r(coef[1], 2),
                         "kwh_per_degree_c": r(coef[2], 2)},
            "cv_rmse_pct": r(cv, 1),
            "cv_rmse_ok": bool(cv <= 30),   # ASHRAE Guideline 14 threshold for hourly-type models
            "baseline_period": {"shifts": len(base), "until": cutoff.isoformat(),
                                "kwh_per_piece": r(base["kwh"].sum() / base["pieces"].sum())},
            "series": series,
        }
        if len(rep):
            expected, actual = float(predict(rep).sum()), float(rep["kwh"].sum())
            saved = expected - actual
            result["reporting_period"] = {
                "shifts": len(rep), "expected_kwh": r(expected, 1), "actual_kwh": r(actual, 1),
                "saved_kwh": r(saved, 1), "saved_pct": r(saved / expected * 100, 1),
                "saved_inr": r(saved * self.avg_rate, 0), "saved_co2_kg": r(saved * self.ef, 1),
                "kwh_per_piece": r(actual / rep["pieces"].sum()),
            }
        return result

    # ------------------------------------------------------------ idle running
    @cached_property
    def _violations(self) -> pd.DataFrame:
        m, thr = self.mac, self.det["running_kw"]
        default = self.det["default_rule"]
        mask = np.zeros(len(m), dtype=bool)
        for dev, idx in m.groupby("device").groups.items():
            rule = {**default, **self.det["machines"].get(dev, {})}
            g = m.loc[idx]
            on = g["kw"] > thr
            bad = (on & (g["state"] == "break") & is_off(rule["break"])) | \
                  (on & (g["state"] == "after_hours") & is_off(rule["after_hours"])
                   & (g["mins_since_shift"] > rule.get("grace_minutes", 10)))
            mask[idx] = bad.to_numpy()
        return m[mask]

    @cached_property
    def idle(self) -> dict:
        v = self._violations
        by_machine, episodes = [], []
        for dev, g in v.groupby("device"):
            by_machine.append({"device": dev, "kwh": r(g["kwh"].sum(), 1), "hours": r(len(g) / 60, 1),
                               "cost_inr": r(g["cost"].sum(), 0),
                               "after_hours_kwh": r(g.loc[g["state"] == "after_hours", "kwh"].sum(), 1),
                               "break_kwh": r(g.loc[g["state"] == "break", "kwh"].sum(), 1)})
            g = g.sort_values("time")
            new = g["time"].diff() > pd.Timedelta(minutes=2)
            for _, e in g.groupby(new.cumsum()):
                episodes.append({"device": dev, "start": e["local"].iloc[0].isoformat(),
                                 "end": e["local"].iloc[-1].isoformat(), "end_utc": e["time"].iloc[-1],
                                 "minutes": len(e), "state": e["state"].iloc[0],
                                 "kwh": r(e["kwh"].sum(), 1), "cost_inr": r(e["cost"].sum(), 0)})
        by_machine.sort(key=lambda x: -x["kwh"])
        episodes.sort(key=lambda x: x["start"], reverse=True)
        kwh, cost = float(v["kwh"].sum()), float(v["cost"].sum())
        return {"total_kwh": r(kwh, 1), "total_cost_inr": r(cost, 0),
                "annual_kwh": r(kwh * self.annual_factor, 0), "annual_cost_inr": r(cost * self.annual_factor, 0),
                "by_machine": by_machine, "episodes": episodes}

    # ------------------------------------------------------------ compressed-air leaks
    def _leak_on(self, c: pd.DataFrame) -> dict:
        thr = self.det["running_kw"]
        on = c[c["kw"] > thr]
        sample = on[on["state"] != "production"]
        if len(sample) < self.det["leak_min_minutes"]:
            return {"status": "insufficient_data", "sample_minutes": len(sample)}
        return {"status": "ok", "sample_minutes": len(sample),
                "leak_pct": float(sample["loaded_s"].sum() / (len(sample) * 60) * 100)}

    @cached_property
    def leaks(self) -> dict:
        """Standard no-demand leak test: leak % = on-load time / total time while nothing uses air."""
        c = self.mac[self.mac["device"] == self.det["compressor"]]
        if c.empty:
            return {"status": "no_compressor"}
        overall = self._leak_on(c)
        daily = []
        for d, g in c.groupby("date"):
            t = self._leak_on(g)
            if t["status"] == "ok":
                daily.append({"date": d.isoformat(), "leak_pct": r(t["leak_pct"], 1), "sample_minutes": t["sample_minutes"]})
        if overall["status"] != "ok":
            return {**overall, "daily": daily}

        on = c[c["kw"] > self.det["running_kw"]]
        full = on[on["loaded_s"] >= 55]["kw"]
        empty = on[on["loaded_s"] == 0]["kw"]
        load_kw = float(full.median()) if len(full) else float(on["kw"].quantile(0.95))
        unload_kw = float(empty.median()) if len(empty) else 0.3 * load_kw
        run_hours = len(on) / 60
        rate = float(on["rate"].mean())
        pct, target = overall["leak_pct"], self.det["leak_target_pct"]
        leak_kwh = pct / 100 * run_hours * load_kw
        recoverable = max(0.0, pct - target) / 100 * run_hours * load_kw
        unload_kwh = float(((60 - on["loaded_s"].fillna(0)) / 60 * unload_kw / 60).sum())
        status = "alarm" if pct >= self.det["leak_alert_pct"] else "warning" if pct > target else "ok"
        return {
            "status": status, "leak_pct": r(pct, 1), "target_pct": target,
            "sample_minutes": overall["sample_minutes"], "method": "no-demand load/unload test",
            "compressor_load_kw": r(load_kw, 1), "compressor_unload_kw": r(unload_kw, 1),
            "running_hours": r(run_hours, 1), "leak_kwh": r(leak_kwh, 1),
            "leak_cost_inr": r(leak_kwh * rate, 0),
            "recoverable_kwh": r(recoverable, 1), "recoverable_cost_inr": r(recoverable * rate, 0),
            "annual_recoverable_kwh": r(recoverable * self.annual_factor, 0),
            "annual_recoverable_inr": r(recoverable * rate * self.annual_factor, 0),
            "unload_kwh": r(unload_kwh, 1), "daily": daily,
        }

    # ------------------------------------------------------------ power factor & demand
    @cached_property
    def power(self) -> dict:
        p, contract = self.inc, self.site["contract_demand_kva"]
        thr, warn = self.tar["pf_threshold"], self.det["pf_warn"]
        loaded = p[p["kw"] > 0.1 * contract]
        pf_all = float(p["kwh"].sum() / p["kvah"].sum()) if p["kvah"].sum() else None

        daily = []
        for d, g in loaded.groupby("date"):
            daily.append({"date": d.isoformat(), "pf": r(g["kwh"].sum() / g["kvah"].sum(), 3),
                          "hours_below_threshold": r((g["pf"] < thr).sum() / 60, 1)})

        md = p.set_index("time")["kva"].resample("30min").mean().dropna()
        md_local = md.copy()
        md_local.index = md_local.index.tz_convert(self.site.get("timezone", "Asia/Kolkata"))
        exceed = md_local[md_local > contract]
        max_md = float(md.max()) if len(md) else 0.0
        excess_kva = max(0.0, max_md - contract)
        excess_monthly = excess_kva * self.tar["demand_inr_per_kva_month"] * self.tar["excess_demand_multiplier"]

        # APFC health: a sustained PF drop after a good period means failed capacitor steps
        apfc = {"status": "ok"}
        good = [x for x in daily if x["pf"] is not None and x["pf"] >= 0.97]
        if daily and good and daily[-1]["pf"] is not None and daily[-1]["pf"] < warn:
            since = next((x["date"] for x in daily if x["date"] > good[-1]["date"] and x["pf"] < warn), daily[-1]["date"])
            last = loaded[loaded["date"] == loaded["date"].max()]
            need = (last["kvar"] - last["kw"] * math.tan(math.acos(0.98))).clip(lower=0)
            kvar_needed = math.ceil(float(need.median()) / 25) * 25 if len(need) else 0
            apfc = {"status": "suspected_failure", "since": since,
                    "pf_before": good[-1]["pf"], "pf_now": daily[-1]["pf"],
                    "kvar_shortfall": kvar_needed,
                    "message": f"Power factor fell from {good[-1]['pf']:.2f} to {daily[-1]['pf']:.2f} "
                               f"since {since}: likely failed capacitor steps in the APFC panel "
                               f"(about {kvar_needed} kVAR missing)."}

        penalty_monthly = 0.0
        if pf_all is not None and pf_all < thr:
            monthly_energy_cost = float(p["cost"].sum()) * 30 / self.window_days
            penalty_monthly = self.tar["pf_penalty_pct_per_0_01"] * (thr - pf_all) / 0.01 / 100 * monthly_energy_cost

        return {
            "pf": r(pf_all, 3), "pf_threshold": thr, "pf_daily": daily,
            "hours_below_threshold": r((loaded["pf"] < thr).sum() / 60, 1),
            "contract_demand_kva": contract, "max_demand_kva": r(max_md, 1),
            "demand_exceeded_blocks": [{"block_start": t.isoformat(), "kva": r(v, 1)} for t, v in exceed.items()],
            "excess_kva": r(excess_kva, 1), "excess_demand_cost_inr_per_month": r(excess_monthly, 0),
            "pf_penalty_inr_per_month": r(penalty_monthly, 0),
            "apfc": apfc,
        }

    # ------------------------------------------------------------ motor health
    @cached_property
    def motors(self) -> dict:
        m = self.mac[~self.mac["device"].isin(self.det.get("motor_exclude", []))]
        cur = m[["ia", "ib", "ic"]]
        avg = cur.mean(axis=1)
        run = m[(m["kw"] > self.det["running_kw"]) & (avg > 1)].copy()
        a = avg.loc[run.index]
        run["imb"] = run[["ia", "ib", "ic"]].sub(a, axis=0).abs().max(axis=1) / a * 100
        warn, alarm = self.det["motor_imbalance_warn_pct"], self.det["motor_imbalance_alarm_pct"]
        out = []
        for dev, g in run.groupby("device"):
            daily = g.groupby("date").agg(imb=("imb", "mean"), n=("imb", "size"))
            daily = daily[daily["n"] >= self.det["motor_min_running_minutes"]]
            if daily.empty:
                continue
            latest = float(daily["imb"].iloc[-1])
            slope = None
            if len(daily) >= 3:
                x = np.array([(d - daily.index[0]).days for d in daily.index], dtype=float)
                slope = float(np.polyfit(x, daily["imb"].to_numpy(), 1)[0])
            status = "alarm" if latest >= alarm else "warning" if latest >= warn else \
                     "watch" if slope is not None and slope > 0.3 else "ok"
            days_to_alarm = (alarm - latest) / slope if slope and slope > 0.05 and latest < alarm else None
            out.append({"device": dev, "status": status, "imbalance_pct": r(latest, 2),
                        "trend_pct_per_day": r(slope, 2), "days_to_alarm": r(days_to_alarm, 1),
                        "daily": [{"date": d.isoformat(), "imbalance_pct": r(v, 2)} for d, v in daily["imb"].items()]})
        order = {"alarm": 0, "warning": 1, "watch": 2, "ok": 3}
        out.sort(key=lambda x: (order[x["status"]], -(x["imbalance_pct"] or 0)))
        return {"warn_pct": warn, "alarm_pct": alarm, "machines": out}

    # ------------------------------------------------------------ carbon
    @cached_property
    def carbon(self) -> dict:
        t = self._totals(self.inc)
        return {
            "plant": self.site["name"], "location": self.site.get("location"), "product": self.site.get("product"),
            "period": self.period(), "pieces": t["pieces"], "electricity_kwh": t["kwh"],
            "emission_factor_kg_per_kwh": self.ef,
            "scope": "Scope 2 (purchased electricity), location-based",
            "total_co2_kg": t["co2_kg"], "kg_co2_per_piece": t["kg_co2_per_piece"],
            "daily": [{"date": d["date"], "kg_co2_per_piece": d["kg_co2_per_piece"]} for d in self.overview["daily"]],
        }

    # ------------------------------------------------------------ recommendations
    @cached_property
    def recommendations(self) -> list[dict]:
        rc, recs = self.rec_cfg, []

        def add(**k):
            k.setdefault("savings_kwh_per_year", 0)
            k["co2_t_per_year"] = r(k["savings_kwh_per_year"] * self.ef / 1000, 1)
            k["payback_months"] = None if k.get("savings_kind") else payback_months(k["capex_inr"], k["savings_inr_per_year"])
            recs.append(k)

        lk = self.leaks
        if lk.get("status") in ("warning", "alarm") and lk["annual_recoverable_inr"] > 0:
            add(id="fix_air_leaks", category="compressed_air", confidence="high",
                title="Fix compressed-air leaks",
                finding=f"Leak test shows {lk['leak_pct']}% of compressor capacity lost to leaks "
                        f"(target ≤{lk['target_pct']}%).",
                action="Ultrasonic leak survey, then fix fittings, hoses and drain valves. Re-test monthly.",
                capex_inr=rc["leak_repair_capex_inr"],
                savings_kwh_per_year=lk["annual_recoverable_kwh"], savings_inr_per_year=lk["annual_recoverable_inr"])

        for mch in self.idle["by_machine"]:
            if mch["kwh"] <= 0:
                continue
            where = "after hours" if mch["after_hours_kwh"] >= mch["break_kwh"] else "during breaks"
            add(id=f"stop_idle_{mch['device']}", category="idle_running", confidence="high",
                title=f"Stop {mch['device'].replace('_', ' ')} running {where}",
                finding=f"Ran {mch['hours']} h with no production in this period "
                        f"({mch['kwh']} kWh, {inr(mch['cost_inr'])}).",
                action="Add a timer or interlock so it stops with the line; add it to the shift-end checklist.",
                capex_inr=rc["idle_interlock_capex_inr_per_machine"],
                savings_kwh_per_year=r(mch["kwh"] * self.annual_factor, 0),
                savings_inr_per_year=r(mch["cost_inr"] * self.annual_factor, 0))

        pw = self.power
        if pw["apfc"]["status"] == "suspected_failure" or pw["excess_kva"] > 0:
            kvar = pw["apfc"].get("kvar_shortfall") or 50
            savings = (pw["excess_demand_cost_inr_per_month"] + pw["pf_penalty_inr_per_month"]) * 12
            add(id="repair_apfc", category="power_quality", confidence="medium",
                title="Repair the APFC capacitor panel",
                finding=pw["apfc"].get("message") or
                        f"Demand hit {pw['max_demand_kva']} kVA against a {pw['contract_demand_kva']} kVA contract.",
                action=f"Replace failed capacitor steps (~{kvar} kVAR) and contactors; check the APFC relay.",
                capex_inr=kvar * rc["apfc_repair_inr_per_kvar"], savings_inr_per_year=r(savings, 0))

        if lk.get("status") in ("ok", "warning", "alarm") and lk.get("unload_kwh"):
            kwh = lk["unload_kwh"] * rc["vfd_unload_savings_share"] * self.annual_factor
            add(id="compressor_vfd", category="compressed_air", confidence="medium",
                title="Retrofit a variable-speed drive on the compressor",
                finding=f"The compressor spends a lot of time running unloaded "
                        f"({lk['unload_kwh']} kWh at ~{lk['compressor_unload_kw']} kW doing no useful work).",
                action="Fit a variable-speed drive so output follows demand. Fix leaks first, then re-evaluate.",
                capex_inr=rc["compressor_vfd_capex_inr"],
                savings_kwh_per_year=r(kwh, 0), savings_inr_per_year=r(kwh * self.avg_rate, 0))

        for mo in self.motors["machines"]:
            if mo["status"] in ("warning", "alarm", "watch"):
                risk = rc["downtime_cost_inr_per_hour"] * rc["expected_breakdown_hours"]
                eta = f" At this rate it reaches alarm level in ~{mo['days_to_alarm']:.0f} days." if mo["days_to_alarm"] else ""
                add(id=f"inspect_{mo['device']}", category="maintenance",
                    confidence="high" if mo["status"] == "alarm" else "medium",
                    title=f"Inspect the {mo['device'].replace('_', ' ')} motor",
                    finding=f"Current imbalance is {mo['imbalance_pct']}% and rising "
                            f"{mo['trend_pct_per_day'] or 0}%/day.{eta}",
                    action="Check terminal connections, supply voltage balance and bearings before it fails.",
                    capex_inr=rc["motor_inspection_capex_inr"],
                    savings_inr_per_year=r(risk, 0), savings_kind="breakdown risk avoided",
                    urgent=mo["status"] == "alarm")

        recs.sort(key=lambda x: (not x.get("urgent", False), x["payback_months"] is None, x["payback_months"] or 0))
        return recs

    # ------------------------------------------------------------ live alerts
    def alerts(self, lookback_minutes: int = 30) -> list[dict]:
        T, out = self.t_end, []
        tz = self.site.get("timezone", "Asia/Kolkata")

        for e in self.idle["episodes"]:
            if e["end_utc"] >= T - pd.Timedelta(minutes=3):   # still running now
                dev = e["device"].replace("_", " ")
                when = "after hours" if e["state"] == "after_hours" else "during the break"
                out.append({"id": f"idle:{e['device']}:{e['start']}", "severity": "warning", "category": "idle_running",
                            "device": e["device"], "since": e["start"],
                            "title": f"{dev.capitalize()} running {when}",
                            "message": f"{dev.capitalize()} has been running {when} for {duration_text(e['minutes'])}: "
                                       f"{inr(e['cost_inr'])} wasted so far.",
                            "values": {"minutes": e["minutes"], "kwh": e["kwh"], "cost_inr": e["cost_inr"], "when": e["state"]}})

        c = self.mac[(self.mac["device"] == self.det["compressor"]) & (self.mac["time"] > T - pd.Timedelta(hours=self.det.get("leak_alert_window_hours", 12)))]
        lt = self._leak_on(c) if len(c) else {"status": "insufficient_data"}
        if lt["status"] == "ok" and lt["leak_pct"] > self.det["leak_target_pct"]:
            sev = "alarm" if lt["leak_pct"] >= self.det["leak_alert_pct"] else "warning"
            day = T.tz_convert(tz).date().isoformat()
            out.append({"id": f"leak:{day}", "severity": sev, "category": "air_leak", "device": self.det["compressor"],
                        "since": day, "title": "Compressed-air leak detected",
                        "message": f"Compressor keeps cycling when no air is being used: about {lt['leak_pct']:.0f}% "
                                   f"of its output is leaking (target ≤{self.det['leak_target_pct']}%).",
                        "values": {"leak_pct": r(lt["leak_pct"], 1)}})

        recent = self.inc[self.inc["time"] > T - pd.Timedelta(minutes=lookback_minutes)]
        loaded = recent[recent["kw"] > 0.1 * self.site["contract_demand_kva"]]
        if len(loaded) >= 10:
            pf = float(loaded["kwh"].sum() / loaded["kvah"].sum())
            if pf < self.det["pf_warn"]:
                sev = "alarm" if pf < self.tar["pf_threshold"] else "warning"
                day = T.tz_convert(tz).date().isoformat()
                out.append({"id": f"pf:{day}:{sev}", "severity": sev, "category": "power_factor", "device": "main_incomer",
                            "since": day, "title": "Low power factor",
                            "message": f"Power factor is {pf:.2f} (should be above {self.det['pf_warn']:.2f}). "
                                       f"Check the APFC capacitor panel.",
                            "values": {"pf": r(pf, 3)}})

        block = T.floor("30min")
        cur = self.inc[self.inc["time"] >= block]
        contract = self.site["contract_demand_kva"]
        if len(cur) >= 5:
            kva = float(cur["kva"].mean())
            if kva >= contract * self.det["md_warning_pct"] / 100:
                sev = "alarm" if kva > contract else "warning"
                out.append({"id": f"md:{block.isoformat()}", "severity": sev, "category": "max_demand",
                            "device": "main_incomer", "since": block.tz_convert(tz).isoformat(),
                            "title": "Maximum demand close to contract limit" if sev == "warning" else "Contract demand exceeded",
                            "message": f"This half-hour is averaging {kva:.0f} kVA against a {contract} kVA contract. "
                                       f"Delay starting large loads until the next block.",
                            "values": {"kva": r(kva, 1), "contract_kva": contract}})

        for mo in self.motors["machines"]:
            if mo["status"] in ("warning", "alarm"):
                out.append({"id": f"motor:{mo['device']}:{mo['status']}", "severity": mo["status"],
                            "category": "motor_health", "device": mo["device"], "since": mo["daily"][-1]["date"],
                            "title": f"{mo['device'].replace('_', ' ').capitalize()} motor needs inspection",
                            "message": f"Current imbalance is {mo['imbalance_pct']}% "
                                       f"(alarm at {self.det['motor_imbalance_alarm_pct']}%). "
                                       f"Schedule an inspection before it fails.",
                            "values": {"imbalance_pct": mo["imbalance_pct"]}})

        sev_order = {"alarm": 0, "warning": 1}
        out.sort(key=lambda a: sev_order.get(a["severity"], 2))
        return out

    # ------------------------------------------------------------ live snapshot
    def live(self) -> dict:
        last = self.inc.iloc[-1]
        latest = self.mac[self.mac["time"] == self.mac["time"].max()]
        T = self.t_end
        active = {e["device"]: e for e in self.idle["episodes"] if e["end_utc"] >= T - pd.Timedelta(minutes=3)}
        machines, waste_kw = [], 0.0
        for _, x in latest.sort_values("kw", ascending=False).iterrows():
            flag = None
            if x["device"] in active:
                e = active[x["device"]]
                flag = {"state": e["state"], "since": e["start"], "minutes": e["minutes"],
                        "kwh": e["kwh"], "cost_inr": e["cost_inr"]}
                waste_kw += float(x["kw"])
            machines.append({"device": x["device"], "kw": r(x["kw"], 1), "status": x["status"],
                             "ia": r(x["ia"], 1), "ib": r(x["ib"], 1), "ic": r(x["ic"], 1), "idle_flag": flag})
        return {
            "time": last["local"].isoformat(), "shift": last["shift"] or None, "state": last["state"],
            "kw": r(last["kw"], 1), "kva": r(last["kva"], 1), "pf": r(last["pf"], 3),
            "contract_demand_kva": self.site["contract_demand_kva"],
            "waste_kw": r(waste_kw, 1), "expected_kw": r(float(last["kw"]) - waste_kw, 1),
            "rate_inr_per_kwh": r(last["rate"], 2), "waste_inr_per_hour": r(waste_kw * float(last["rate"]), 0),
            "machines": machines,
        }

    # ------------------------------------------------------------ one-call summary for the dashboard
    def summary(self) -> dict:
        recs = self.recommendations
        money = [x for x in recs if x.get("savings_kind") is None]
        b = self.baseline
        return {
            "plant": {k: self.site.get(k) for k in ("name", "location", "product", "contract_demand_kva")},
            "period": self.period(),
            "totals": self.overview["totals"],
            "waste": {
                "idle_cost_inr": self.idle["total_cost_inr"],
                "leak_cost_inr": self.leaks.get("recoverable_cost_inr", 0),
                "excess_demand_cost_inr_per_month": self.power["excess_demand_cost_inr_per_month"],
            },
            "opportunity": {
                "savings_inr_per_year": r(sum(x["savings_inr_per_year"] for x in money), 0),
                "savings_kwh_per_year": r(sum(x["savings_kwh_per_year"] for x in money), 0),
                "capex_inr": r(sum(x["capex_inr"] for x in money), 0),
            },
            "baseline": b.get("reporting_period") if b.get("status") == "ok" else None,
            "top_recommendations": recs[:3],
            "alerts": self.alerts(),
        }
