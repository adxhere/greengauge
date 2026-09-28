#!/usr/bin/env python3
"""
Instantly load simulated history into the database, so the analytics have a
"before GreenGauge" baseline without waiting hours for the live replay.

It loads everything from the start of the scenario up to --until (default: the
meter's START time), so the live stream carries on seamlessly from there.

In Docker:
  docker compose exec analytics python tools/backfill.py --scenario faulty

Any existing rows before --until are replaced.
"""
import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.getenv("DATA_DIR", "/data" if Path("/data").exists() else str(ROOT / "data")))
    ap.add_argument("--scenario", default="faulty")
    ap.add_argument("--until", default=os.getenv("START", "2026-09-10 05:50"),
                    help="load history up to this simulated time (IST)")
    ap.add_argument("--db", default=os.getenv("DATABASE_URL",
                                              "postgresql://greengauge:greengauge@127.0.0.1:5433/greengauge"))
    args = ap.parse_args()

    plant = yaml.safe_load((ROOT / "config" / "devices.yaml").read_text())["plant_id"]
    folder = Path(args.data) / args.scenario
    if not (folder / "incomer.csv").exists():
        raise SystemExit(f"Scenario data not found in {folder}")
    until = pd.Timestamp(args.until, tz="Asia/Kolkata")

    inc = pd.read_csv(folder / "incomer.csv")
    mac = pd.read_csv(folder / "machines.csv", dtype={"fault_label": "string"})
    inc = inc[pd.to_datetime(inc["timestamp"], utc=True) < until].copy()
    mac = mac[pd.to_datetime(mac["timestamp"], utc=True) < until].copy()
    if inc.empty:
        raise SystemExit(f"No data before {until} in scenario '{args.scenario}'")

    # shape it exactly like the gateway + ingester would have written it
    inc["energy_kwh"] = (inc["kw"] / 60).cumsum()
    inc["pieces_total"] = inc["pieces"].cumsum()
    inc["shift"] = inc["shift"].fillna("")
    mac["kva"] = np.sqrt(mac["kw"] ** 2 + mac["kvar"] ** 2)
    mac["pf"] = np.where(mac["kva"] > 0, mac["kw"] / mac["kva"].where(mac["kva"] > 0), 1.0)
    mac["energy_kwh"] = (mac["kw"] / 60).groupby(mac["machine"]).cumsum()
    mac = mac.merge(inc[["timestamp", "voltage"]], on="timestamp")

    with psycopg.connect(args.db) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM incomer_readings WHERE plant_id = %s AND time < %s", (plant, until))
        cur.execute("DELETE FROM machine_readings WHERE plant_id = %s AND time < %s", (plant, until))
        with cur.copy("COPY incomer_readings (time, plant_id, device, kw, kvar, kva, pf, voltage, ia, ib, ic, "
                      "energy_kwh, pieces_total, ambient_c, shift, producing) FROM STDIN") as cp:
            for x in inc.itertuples():
                cp.write_row((x.timestamp, plant, "main_incomer", x.kw, x.kvar, x.kva, x.pf, x.voltage,
                              x.ia, x.ib, x.ic, x.energy_kwh, int(x.pieces_total), x.ambient_c,
                              x.shift, bool(x.producing)))
        with cur.copy("COPY machine_readings (time, plant_id, device, kw, kvar, kva, pf, voltage, ia, ib, ic, "
                      "energy_kwh, status, loaded_s) FROM STDIN") as cp:
            for x in mac.itertuples():
                cp.write_row((x.timestamp, plant, x.machine, x.kw, x.kvar, x.kva, x.pf, x.voltage,
                              x.ia, x.ib, x.ic, x.energy_kwh, x.status,
                              None if pd.isna(x.loaded_s) else int(x.loaded_s)))
        conn.commit()

    first = pd.to_datetime(inc["timestamp"].iloc[0], utc=True).tz_convert("Asia/Kolkata")
    print(f"Loaded '{args.scenario}' history: {first:%d %b %H:%M} to {until:%d %b %H:%M} IST "
          f"({len(inc):,} incomer rows, {len(mac):,} machine rows)")


if __name__ == "__main__":
    main()
