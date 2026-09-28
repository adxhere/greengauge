#!/usr/bin/env python3
"""
Record a snapshot of the running analytics API for the Vercel demo site.

Saves every API response the dashboard uses into dashboard/public/demo/, so the
deployed dashboard shows this exact moment without needing the backend.

  python tools/export_demo.py                       # from the project folder, while the stack runs
  python tools/export_demo.py --api http://localhost:8000
"""
import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENDPOINTS = ["summary", "overview", "baseline", "power", "idle", "leaks", "recommendations", "motors", "carbon"]
FIXED = ["/api/health", "/api/config", "/api/live", "/api/alerts",
         "/api/timeseries?device=main_incomer&hours=24&bucket_minutes=15"]


def file_name(path: str) -> str:
    # must match demoPath() in dashboard/src/api.js
    return re.sub(r"[?&=/]", "_", path[len("/api/"):]) + ".json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--out", default=str(ROOT / "dashboard" / "public" / "demo"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    paths = FIXED + [f"/api/{e}?days={d}" for d in (1, 7, 30) for e in ENDPOINTS]
    for p in paths:
        with urllib.request.urlopen(args.api + p, timeout=60) as r:
            data = json.loads(r.read())
        (out / file_name(p)).write_text(json.dumps(data, ensure_ascii=False))
        print(f"saved {file_name(p)}")

    live = json.loads((out / file_name("/api/live")).read_text())
    (out / "meta.json").write_text(json.dumps({"snapshot_of": live.get("time"),
                                               "recorded_at": datetime.now(timezone.utc).isoformat()}))
    print(f"\nSnapshot of plant time {live.get('time')} saved to {out} ({len(paths)} files).")


if __name__ == "__main__":
    main()
