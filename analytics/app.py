"""
GreenGauge analytics API.

  uvicorn analytics.app:app --port 8000          (from the project root)

Interactive docs at http://localhost:8000/docs
"""
from __future__ import annotations

import datetime as dt
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analytics import db  # noqa: E402
from analytics.engine import Engine  # noqa: E402

CFG = yaml.safe_load((ROOT / "config" / "analytics.yaml").read_text())
PLANT = CFG["site"]["plant_id"]

app = FastAPI(title="GreenGauge Analytics", version="1.0",
              description="Energy, money and carbon per piece for SME plants.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def clean(o):
    """Make engine output JSON-safe: numpy -> python, NaN -> null, timestamps -> ISO."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items() if k != "end_utc"}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if math.isnan(o) or math.isinf(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, dt.datetime, dt.date)):
        return o.isoformat()
    return o


def engine(days: float) -> Engine:
    try:
        inc, mac = db.load(PLANT, days)
    except db.NoData as e:
        raise HTTPException(503, str(e))
    except db.psycopg.OperationalError:
        raise HTTPException(503, "Database not reachable. Is the db container running?")
    if len(inc) < 10:
        raise HTTPException(503, "Not enough data yet. Let the pipeline run for a few minutes.")
    return Engine(CFG, inc, mac)


Days = Query(7.0, gt=0, le=90, description="Analysis window: the last N days of data")


@app.get("/api/health")
def health():
    try:
        e = engine(1 / 24)
        return {"status": "ok", "latest_reading": e.inc["local"].max().isoformat(), "rows_last_hour": len(e.inc)}
    except HTTPException as ex:
        return {"status": "waiting_for_data", "detail": ex.detail}


@app.get("/api/summary", summary="Everything the dashboard home screen needs, in one call")
def summary(days: float = Days):
    return clean(engine(days).summary())


@app.get("/api/overview", summary="Totals and daily energy, cost, carbon per piece")
def overview(days: float = Days):
    return clean(engine(days).overview)


@app.get("/api/baseline", summary="Regression baseline and measured savings (IPMVP-style)")
def baseline(days: float = Days, baseline_days: float | None = Query(None, gt=0)):
    e = engine(days)
    if baseline_days is not None:
        e.det["baseline_days"] = baseline_days
    return clean(e.baseline)


@app.get("/api/idle", summary="Machines running when they should be off")
def idle(days: float = Days):
    return clean(engine(days).idle)


@app.get("/api/leaks", summary="Compressed-air leak test")
def leaks(days: float = Days):
    return clean(engine(days).leaks)


@app.get("/api/power", summary="Power factor, maximum demand and APFC health")
def power(days: float = Days):
    return clean(engine(days).power)


@app.get("/api/motors", summary="Motor health from current imbalance")
def motors(days: float = Days):
    return clean(engine(days).motors)


@app.get("/api/carbon", summary="Carbon-per-piece certificate data")
def carbon(days: float = Days):
    return clean(engine(days).carbon)


@app.get("/api/recommendations", summary="Fixes ranked by payback")
def recommendations(days: float = Days):
    return clean(engine(days).recommendations)


@app.get("/api/alerts", summary="Problems happening right now")
def alerts(lookback_minutes: int = Query(30, ge=5, le=240)):
    return clean(engine(1).alerts(lookback_minutes))


@app.get("/api/live", summary="Latest reading for every meter, with machines wasting power right now")
def live():
    return clean(engine(1).live())


@app.get("/api/config", summary="Plant, tariff and threshold settings (for the dashboard)")
def config():
    t, d = CFG["tariff"], CFG["detection"]
    return {"site": CFG["site"],
            "tariff": {k: t[k] for k in ("energy_inr_per_kwh", "peak_hours", "peak_surcharge_pct", "offpeak_hours",
                                         "offpeak_rebate_pct", "pf_threshold", "emission_factor_kg_per_kwh")},
            "thresholds": {"pf_warn": d["pf_warn"], "leak_target_pct": d["leak_target_pct"],
                           "leak_alert_pct": d["leak_alert_pct"], "md_warning_pct": d["md_warning_pct"],
                           "motor_warn_pct": d["motor_imbalance_warn_pct"], "motor_alarm_pct": d["motor_imbalance_alarm_pct"]}}


@app.get("/api/timeseries", summary="Bucketed readings for one meter, for charts")
def timeseries(device: str = "main_incomer", hours: float = Query(24, gt=0, le=24 * 31),
               bucket_minutes: int = Query(5, ge=1, le=1440)):
    try:
        df = db.timeseries(PLANT, device, hours, bucket_minutes)
    except (db.NoData, db.psycopg.OperationalError) as e:
        raise HTTPException(503, str(e).splitlines()[0])
    return clean({"device": device, "bucket_minutes": bucket_minutes,
                  "points": df.round({c: 3 for c in df.columns if c != "time"}).to_dict(orient="records")})


@app.get("/api/timeseries/machines", summary="kW per machine per bucket (stacked load chart)")
def timeseries_machines(hours: float = Query(24, gt=0, le=24 * 31), bucket_minutes: int = Query(15, ge=1, le=1440)):
    try:
        df = db.machines_timeseries(PLANT, hours, bucket_minutes)
    except (db.NoData, db.psycopg.OperationalError) as e:
        raise HTTPException(503, str(e).splitlines()[0])
    wide = df.pivot_table(index="time", columns="device", values="kw").round(2).reset_index()
    return clean({"bucket_minutes": bucket_minutes, "points": wide.to_dict(orient="records")})
