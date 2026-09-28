#!/usr/bin/env python3
"""
GreenGauge edge gateway.

Polls every meter listed in config/devices.yaml over Modbus TCP, decodes the
registers, and publishes one JSON message per new reading to MQTT:

  greengauge/<plant_id>/<device>/telemetry

This is exactly the code that would run on an ESP32/Raspberry Pi-class box
on a real plant; only config/devices.yaml changes.

Usage (local, outside Docker):
  MODBUS_HOST=127.0.0.1 MQTT_HOST=127.0.0.1 python gateway.py
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
import yaml
from pymodbus.client import AsyncModbusTcpClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common.registers import N_REGISTERS, SHIFT_NAMES, STATUS_NAMES, decode  # noqa: E402

log = logging.getLogger("gateway")


def build_payload(plant_id: str, dev: dict, d: dict) -> dict:
    p = {
        "ts": datetime.fromtimestamp(d["timestamp"], tz=timezone.utc).isoformat(),
        "plant_id": plant_id,
        "device": dev["name"],
        "type": dev["type"],
        **{k: round(d[k], 4) for k in ("kw", "kvar", "kva", "pf", "voltage", "ia", "ib", "ic")},
        "energy_kwh": round(d["energy_wh"] / 1000, 3),
    }
    if dev["type"] == "incomer":
        p.update(pieces_total=d["pieces_total"], ambient_c=round(d["ambient_c"], 2),
                 shift=SHIFT_NAMES.get(d["shift"], ""), producing=bool(d["producing"]))
    else:
        p.update(status=STATUS_NAMES.get(d["status"], "off"), loaded_s=d["loaded_s"])
    return p


async def run():
    cfg = yaml.safe_load((ROOT / "config" / "devices.yaml").read_text())
    plant_id = cfg["plant_id"]
    mb_host = os.getenv("MODBUS_HOST", cfg["modbus"]["host"])
    mb_port = int(os.getenv("MODBUS_PORT", cfg["modbus"]["port"]))
    poll = float(os.getenv("POLL_SECONDS", cfg["modbus"]["poll_seconds"]))
    mq_host = os.getenv("MQTT_HOST", cfg["mqtt"]["host"])
    mq_port = int(os.getenv("MQTT_PORT", cfg["mqtt"]["port"]))
    root = cfg["mqtt"]["topic_root"]

    mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"gg-gateway-{plant_id}")
    mq.reconnect_delay_set(1, 10)
    while True:
        try:
            mq.connect(mq_host, mq_port)
            break
        except OSError as e:
            log.warning("MQTT broker %s:%d not reachable (%s), retrying...", mq_host, mq_port, e)
            await asyncio.sleep(2)
    mq.loop_start()
    log.info("connected to MQTT %s:%d", mq_host, mq_port)

    client = AsyncModbusTcpClient(mb_host, port=mb_port, timeout=2, retries=1)
    last_ts: dict[int, int] = {}
    sent = 0
    while True:
        if not client.connected:
            if not await client.connect():
                log.warning("meters at %s:%d not reachable, retrying...", mb_host, mb_port)
                await asyncio.sleep(2)
                continue
            log.info("connected to Modbus meters at %s:%d, polling every %.2fs", mb_host, mb_port, poll)

        for dev in cfg["devices"]:
            try:
                rr = await client.read_holding_registers(0, count=N_REGISTERS, slave=dev["unit"])
            except Exception as e:
                log.warning("read failed for %s (unit %d): %s", dev["name"], dev["unit"], e)
                continue
            if rr.isError():
                log.warning("Modbus error for %s (unit %d): %s", dev["name"], dev["unit"], rr)
                continue
            d = decode(rr.registers)
            if d["timestamp"] == 0 or last_ts.get(dev["unit"]) == d["timestamp"]:
                continue  # meter not ready yet, or no new reading since last poll
            last_ts[dev["unit"]] = d["timestamp"]
            topic = f"{root}/{plant_id}/{dev['name']}/telemetry"
            mq.publish(topic, json.dumps(build_payload(plant_id, dev, d)), qos=1)
            sent += 1
            if sent % 500 == 0:
                log.info("published %d readings (latest meter time %s)", sent,
                         datetime.fromtimestamp(d["timestamp"], tz=timezone.utc).isoformat())
        await asyncio.sleep(poll)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("pymodbus").setLevel(logging.ERROR)
    asyncio.run(run())


if __name__ == "__main__":
    main()
