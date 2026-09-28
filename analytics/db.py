"""
Loads readings from TimescaleDB into DataFrames for the analytics engine.

"Now" is the latest reading in the database, not the wall clock, so the analytics
work the same on replayed simulator data and on a live plant.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import timedelta

import pandas as pd
import psycopg

DB_URL = os.getenv("DATABASE_URL", "postgresql://greengauge:greengauge@127.0.0.1:5433/greengauge")
CACHE_SECONDS = float(os.getenv("CACHE_SECONDS", "5"))

INC_COLS = ["time", "kw", "kvar", "kva", "pf", "voltage", "ia", "ib", "ic",
            "energy_kwh", "pieces_total", "ambient_c", "shift", "producing"]
MAC_COLS = ["time", "device", "kw", "kvar", "ia", "ib", "ic", "status", "loaded_s"]

_cache: dict = {}
_lock = threading.Lock()


class NoData(Exception):
    pass


def _query(conn, sql: str, params: tuple, cols: list[str]) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return pd.DataFrame(cur.fetchall(), columns=cols)


def latest_time(conn, plant_id: str):
    with conn.cursor() as cur:
        cur.execute("SELECT max(time) FROM incomer_readings WHERE plant_id = %s", (plant_id,))
        return cur.fetchone()[0]


def load(plant_id: str, days: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (incomer, machines) for the last `days` of data, cached for a few seconds."""
    with psycopg.connect(DB_URL) as conn:
        latest = latest_time(conn, plant_id)
        if latest is None:
            raise NoData("No readings in the database yet. Is the pipeline running?")
        key = (plant_id, days, latest)
        with _lock:
            hit = _cache.get(key)
            if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
                return hit[1]
        since = latest - timedelta(days=days)
        inc = _query(conn, f"SELECT {', '.join(INC_COLS)} FROM incomer_readings "
                           "WHERE plant_id = %s AND time > %s ORDER BY time", (plant_id, since), INC_COLS)
        mac = _query(conn, f"SELECT {', '.join(MAC_COLS)} FROM machine_readings "
                           "WHERE plant_id = %s AND time > %s ORDER BY time", (plant_id, since), MAC_COLS)
    for df in (inc, mac):
        for c in df.columns:
            if c not in ("time", "device", "status", "shift", "producing"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
    with _lock:
        _cache.clear()
        _cache[key] = (time.monotonic(), (inc, mac))
    return inc, mac


def timeseries(plant_id: str, device: str, hours: float, bucket_minutes: int) -> pd.DataFrame:
    """Averaged readings in time buckets, for charts."""
    table = "incomer_readings" if device == "main_incomer" else "machine_readings"
    extra = ", avg(pf) AS pf, max(kva) AS kva_max" if table == "incomer_readings" else ", avg(loaded_s) AS loaded_s"
    sql = (f"SELECT date_bin(make_interval(mins => %s), time, TIMESTAMPTZ '2000-01-01') AS bucket, "
           f"avg(kw) AS kw, avg(kva) AS kva{extra} "
           f"FROM {table} WHERE plant_id = %s AND device = %s AND time > %s "
           f"GROUP BY bucket ORDER BY bucket")
    with psycopg.connect(DB_URL) as conn:
        latest = latest_time(conn, plant_id)
        if latest is None:
            raise NoData("No readings in the database yet. Is the pipeline running?")
        cols = ["time", "kw", "kva"] + (["pf", "kva_max"] if table == "incomer_readings" else ["loaded_s"])
        return _query(conn, sql, (bucket_minutes, plant_id, device, latest - timedelta(hours=hours)), cols)


def machines_timeseries(plant_id: str, hours: float, bucket_minutes: int) -> pd.DataFrame:
    """kW per machine per bucket (for a stacked load chart)."""
    sql = ("SELECT date_bin(make_interval(mins => %s), time, TIMESTAMPTZ '2000-01-01') AS bucket, device, avg(kw) "
           "FROM machine_readings WHERE plant_id = %s AND time > %s GROUP BY bucket, device ORDER BY bucket")
    with psycopg.connect(DB_URL) as conn:
        latest = latest_time(conn, plant_id)
        if latest is None:
            raise NoData("No readings in the database yet. Is the pipeline running?")
        return _query(conn, sql, (bucket_minutes, plant_id, latest - timedelta(hours=hours)), ["time", "device", "kw"])
