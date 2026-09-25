#!/usr/bin/env python3
"""
Quick visual check of a simulator run.

  python plot.py --data output/faulty
  python plot.py --data output/faulty --day 2026-09-10
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(here / "output" / "faulty"))
    ap.add_argument("--day", default=None, help="day to zoom into (YYYY-MM-DD); default: 4th day")
    args = ap.parse_args()
    d = Path(args.data)

    inc = pd.read_csv(d / "incomer.csv", parse_dates=["timestamp"])
    mac = pd.read_csv(d / "machines.csv", parse_dates=["timestamp"], dtype={"fault_label": "string"})
    day = pd.Timestamp(args.day).date() if args.day else sorted(inc["timestamp"].dt.date.unique())[3]

    fig, ax = plt.subplots(4, 1, figsize=(14, 14))

    # 1. whole run at the incomer
    ax[0].plot(inc["timestamp"], inc["kw"], lw=0.5, label="kW")
    ax[0].plot(inc["timestamp"], inc["kva"].rolling(30).mean(), lw=1, label="kVA (30-min avg)")
    ax[0].set_title("Main incomer: whole run")
    ax[0].legend(loc="upper right")

    # 2. one day, stacked by machine
    md = mac[mac["timestamp"].dt.date == day].pivot(index="timestamp", columns="machine", values="kw")
    ax[1].stackplot(md.index, md.T.values, labels=md.columns, lw=0)
    ax[1].set_title(f"Load by machine: {day}")
    ax[1].legend(loc="upper left", fontsize=8, ncol=4)

    # 3. compressor on that day, with shift/production shading
    c = mac[(mac["machine"] == "air_compressor") & (mac["timestamp"].dt.date == day)]
    idd = inc[inc["timestamp"].dt.date == day]
    ax[2].plot(c["timestamp"], c["kw"], lw=0.7, color="tab:red")
    ax[2].fill_between(idd["timestamp"], 0, 40, where=idd["producing"], alpha=0.1, label="production")
    ax[2].set_title("Air compressor kW (cycling in breaks and after hours = leaks)")
    ax[2].legend(loc="upper right")

    # 4. power factor & cooling pump imbalance across the run
    ax[3].plot(inc["timestamp"], inc["pf"].where(inc["kw"] > 50).rolling(60).mean(), lw=0.8, label="incomer PF (1-h avg)")
    ax[3].set_ylim(0.8, 1.0)
    ax3b = ax[3].twinx()
    p = mac[(mac["machine"] == "cooling_pump") & (mac["kw"] > 0)].copy()
    i_avg = p[["ia", "ib", "ic"]].mean(axis=1)
    p["unb"] = (p[["ia", "ib", "ic"]].sub(i_avg, axis=0).abs().max(axis=1) / i_avg * 100)
    ax3b.plot(p["timestamp"], p["unb"], ".", ms=1, color="tab:purple", label="cooling pump imbalance %")
    ax[3].set_title("Power factor (APFC failure) and cooling-pump current imbalance (degradation)")
    ax[3].legend(loc="lower left")
    ax3b.legend(loc="upper left")

    fig.tight_layout()
    out = d / "overview.png"
    fig.savefig(out, dpi=110)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
