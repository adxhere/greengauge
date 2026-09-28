#!/usr/bin/env python3
"""
GreenGauge Modbus meter emulator.

Replays simulator output as a set of live Modbus TCP energy meters:
unit 1 is the main incomer, units 11-17 are clamp-on CT meters on each machine
(see config/devices.yaml and common/registers.py for the register map).

Time runs faster than real life (SPEED simulated seconds per real second;
the default 60 plays one simulated minute every second), and the scenario
can be switched live over MQTT, which is how you "flip a fault switch" in the demo:

  mosquitto_pub -t greengauge/control/scenario -m leak

Usage:
  python meter_server.py --data ../data --scenario healthy --speed 60
"""
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.server import StartAsyncTcpServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common.registers import N_REGISTERS, SHIFT_CODES, STATUS_CODES, encode  # noqa: E402

log = logging.getLogger("meter")
FIELDS = ["kw", "kvar", "kva", "pf", "voltage", "ia", "ib", "ic"]
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def to_unix(series: pd.Series) -> np.ndarray:
    """Timestamps -> unix seconds, independent of pandas' internal time resolution."""
    return ((pd.to_datetime(series, utc=True) - EPOCH) // pd.Timedelta(seconds=1)).to_numpy("int64")


# ---------------------------------------------------------------- data loading
def load_scenario(folder: Path, devices: list[dict]) -> dict:
    """Load one scenario folder into numpy arrays, one entry per device."""
    inc = pd.read_csv(folder / "incomer.csv")
    ts = to_unix(inc["timestamp"])
    n = len(inc)
    mac = pd.read_csv(folder / "machines.csv", dtype={"fault_label": "string"})
    mac["ts"] = to_unix(mac["timestamp"])

    data = {"ts": ts, "n": n, "devices": {}}
    for dev in devices:
        if dev["type"] == "incomer":
            d = {f: inc[f].to_numpy(float) for f in FIELDS}
            d["ambient_c"] = inc["ambient_c"].to_numpy(float)
            d["shift"] = inc["shift"].fillna("").map(SHIFT_CODES).to_numpy(int)
            d["producing"] = inc["producing"].astype(bool).to_numpy(int)
            d["pieces"] = inc["pieces"].to_numpy(int)
        else:
            m = mac[mac["machine"] == dev["name"]].sort_values("ts")
            if len(m) != n:
                raise SystemExit(f"{folder.name}: machine '{dev['name']}' has {len(m)} rows, expected {n}")
            d = {f: m[f].to_numpy(float) for f in ("kw", "kvar", "ia", "ib", "ic")}
            d["kva"] = np.sqrt(d["kw"] ** 2 + d["kvar"] ** 2)
            d["pf"] = np.where(d["kva"] > 0, d["kw"] / np.maximum(d["kva"], 1e-9), 1.0)
            d["voltage"] = inc["voltage"].to_numpy(float)
            d["status"] = m["status"].map(STATUS_CODES).fillna(0).to_numpy(int)
            d["loaded_s"] = m["loaded_s"].fillna(0).to_numpy(int)
        data["devices"][dev["unit"]] = d
    return data


# ---------------------------------------------------------------- meter state
class Meters:
    def __init__(self, scenarios: dict, devices: list[dict], scenario: str, start_idx: int):
        self.scenarios = scenarios
        self.devices = devices
        self.scenario = scenario
        self.idx = start_idx
        self.loop = 0
        first = next(iter(scenarios.values()))
        self.n = first["n"]
        self.duration = int(first["ts"][-1] - first["ts"][0]) + 60
        # counters live in the meter, so they stay continuous across scenario switches and loops
        self.energy_wh = {d["unit"]: 0.0 for d in devices}
        self.pieces_total = 0

    def set_scenario(self, name: str):
        if name in self.scenarios and name != self.scenario:
            log.info("scenario switched: %s -> %s", self.scenario, name)
            self.scenario = name
        elif name not in self.scenarios:
            log.warning("unknown scenario '%s' (have: %s)", name, ", ".join(self.scenarios))

    def step(self) -> dict[int, list[int]]:
        """Advance one simulated minute and return register values per unit."""
        data = self.scenarios[self.scenario]
        i = self.idx
        ts = int(data["ts"][i]) + self.loop * self.duration
        regs = {}
        for dev in self.devices:
            u = dev["unit"]
            d = data["devices"][u]
            self.energy_wh[u] += d["kw"][i] * 1000 / 60
            v = {f: d[f][i] for f in FIELDS}
            v["timestamp"] = ts
            v["energy_wh"] = self.energy_wh[u]
            if dev["type"] == "incomer":
                self.pieces_total += int(d["pieces"][i])
                v.update(pieces_total=self.pieces_total, ambient_c=d["ambient_c"][i],
                         shift=d["shift"][i], producing=d["producing"][i])
            else:
                v.update(status=d["status"][i], loaded_s=d["loaded_s"][i])
            regs[u] = encode(v)
        self.idx += 1
        if self.idx >= self.n:
            self.idx, self.loop = 0, self.loop + 1
            log.info("reached end of data, looping (time keeps moving forward)")
        return regs


# ---------------------------------------------------------------- MQTT control (optional)
def start_control(meters: Meters, host: str, port: int, topic: str):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        log.warning("paho-mqtt not installed; live scenario switching disabled")
        return

    def on_connect(client, userdata, flags, rc, props=None):
        client.subscribe(topic)
        log.info("listening for scenario switches on MQTT topic '%s'", topic)

    def on_message(client, userdata, msg):
        meters.set_scenario(msg.payload.decode().strip().lower())

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="gg-meter-control")
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(1, 10)
    try:
        client.connect_async(host, port)
        client.loop_start()
    except Exception as e:  # broker not up yet: paho keeps retrying in the background
        log.warning("MQTT control not connected yet (%s)", e)


# ---------------------------------------------------------------- main
async def run(args):
    cfg = yaml.safe_load((ROOT / "config" / "devices.yaml").read_text())
    devices = cfg["devices"]

    data_root = Path(args.data)
    folders = sorted(p for p in data_root.iterdir() if (p / "incomer.csv").exists()) if data_root.exists() else []
    if not folders:
        raise SystemExit(f"No scenarios found in {data_root}. Run simulator/generate_scenarios.py first.")
    scenarios = {}
    for f in folders:
        scenarios[f.name] = load_scenario(f, devices)
        log.info("loaded scenario '%s' (%d minutes)", f.name, scenarios[f.name]["n"])
    if args.scenario not in scenarios:
        raise SystemExit(f"Scenario '{args.scenario}' not found. Have: {', '.join(scenarios)}")

    start_idx = 0
    if args.start:
        ts0 = scenarios[args.scenario]["ts"]
        target = (pd.Timestamp(args.start, tz="Asia/Kolkata") - EPOCH) // pd.Timedelta(seconds=1)
        start_idx = int(np.clip(np.searchsorted(ts0, target), 0, len(ts0) - 1))

    meters = Meters(scenarios, devices, args.scenario, start_idx)

    store = {d["unit"]: ModbusSlaveContext(hr=ModbusSequentialDataBlock(0, [0] * (N_REGISTERS + 10)))
             for d in devices}
    context = ModbusServerContext(slaves=store, single=False)

    start_control(meters, args.mqtt_host, args.mqtt_port, args.control_topic)

    tick = 60.0 / args.speed

    async def ticker():
        while True:
            for unit, regs in meters.step().items():
                context[unit].setValues(3, 0, regs)
            await asyncio.sleep(tick)

    asyncio.create_task(ticker())
    log.info("Modbus meters on port %d | units %s | scenario '%s' | speed x%g (1 sim-minute every %.2fs)",
             args.port, [d["unit"] for d in devices], args.scenario, args.speed, tick)
    await StartAsyncTcpServer(context=context, address=("0.0.0.0", args.port))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("pymodbus").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(description="GreenGauge Modbus meter emulator")
    ap.add_argument("--data", default=os.getenv("DATA_DIR", str(ROOT / "data")))
    ap.add_argument("--scenario", default=os.getenv("SCENARIO", "healthy"))
    ap.add_argument("--speed", type=float, default=float(os.getenv("SPEED", "60")),
                    help="simulated seconds per real second (60 = 1 sim-minute per second)")
    ap.add_argument("--start", default=os.getenv("START", ""),
                    help="simulated time to start from, e.g. '2026-09-10 05:30'")
    ap.add_argument("--port", type=int, default=int(os.getenv("MODBUS_PORT", "5020")))
    ap.add_argument("--mqtt-host", default=os.getenv("MQTT_HOST", "127.0.0.1"))
    ap.add_argument("--mqtt-port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    ap.add_argument("--control-topic", default="greengauge/control/scenario")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
