#!/usr/bin/env python3
"""
GreenGauge ingester: subscribes to all telemetry on MQTT and writes it to TimescaleDB
in small batches.

Usage (local, outside Docker):
  MQTT_HOST=127.0.0.1 DATABASE_URL=postgresql://greengauge:greengauge@127.0.0.1:5433/greengauge python ingest.py
"""
import json
import logging
import os
import queue
import time

import paho.mqtt.client as mqtt
import psycopg

log = logging.getLogger("ingest")

TOPIC = os.getenv("MQTT_TOPIC", "greengauge/+/+/telemetry")
COMMON = ["kw", "kvar", "kva", "pf", "voltage", "ia", "ib", "ic", "energy_kwh"]
TABLES = {
    "incomer": ("incomer_readings", COMMON + ["pieces_total", "ambient_c", "shift", "producing"]),
    "machine": ("machine_readings", COMMON + ["status", "loaded_s"]),
}
BATCH_ROWS = 500
BATCH_SECONDS = 1.0


def insert_sql(table: str, cols: list[str]) -> str:
    all_cols = ["time", "plant_id", "device"] + cols
    ph = ", ".join(["%s"] * len(all_cols))
    return (f"INSERT INTO {table} ({', '.join(all_cols)}) VALUES ({ph}) "
            f"ON CONFLICT (plant_id, device, time) DO NOTHING")


def connect_db(url: str):
    while True:
        try:
            conn = psycopg.connect(url, autocommit=False)
            log.info("connected to database")
            return conn
        except psycopg.OperationalError as e:
            log.warning("database not ready (%s), retrying...", str(e).strip().splitlines()[0])
            time.sleep(2)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    db_url = os.getenv("DATABASE_URL", "postgresql://greengauge:greengauge@127.0.0.1:5433/greengauge")
    mq_host = os.getenv("MQTT_HOST", "127.0.0.1")
    mq_port = int(os.getenv("MQTT_PORT", "1883"))

    q: queue.Queue = queue.Queue(maxsize=100_000)

    def on_connect(client, userdata, flags, rc, props=None):
        client.subscribe(TOPIC, qos=1)
        log.info("subscribed to %s", TOPIC)

    def on_message(client, userdata, msg):
        try:
            q.put_nowait(json.loads(msg.payload))
        except (json.JSONDecodeError, queue.Full) as e:
            log.warning("dropped message on %s: %s", msg.topic, e)

    mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="gg-ingest")
    mq.on_connect = on_connect
    mq.on_message = on_message
    mq.reconnect_delay_set(1, 10)
    while True:
        try:
            mq.connect(mq_host, mq_port)
            break
        except OSError as e:
            log.warning("MQTT broker %s:%d not reachable (%s), retrying...", mq_host, mq_port, e)
            time.sleep(2)
    mq.loop_start()

    conn = connect_db(db_url)
    sql = {k: insert_sql(t, cols) for k, (t, cols) in TABLES.items()}
    total = 0
    while True:
        batch = {k: [] for k in TABLES}
        deadline = time.monotonic() + BATCH_SECONDS
        n = 0
        while n < BATCH_ROWS and time.monotonic() < deadline:
            try:
                m = q.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            kind = m.get("type")
            if kind not in TABLES:
                continue
            cols = TABLES[kind][1]
            batch[kind].append([m["ts"], m["plant_id"], m["device"]] + [m.get(c) for c in cols])
            n += 1
        if n == 0:
            continue
        try:
            with conn.cursor() as cur:
                for kind, rows in batch.items():
                    if rows:
                        cur.executemany(sql[kind], rows)
            conn.commit()
            total += n
            if total // 1000 != (total - n) // 1000:
                log.info("stored %d readings so far", total)
        except psycopg.Error as e:
            log.error("write failed: %s", e)
            try:
                conn.rollback()
            except psycopg.Error:
                conn = connect_db(db_url)


if __name__ == "__main__":
    main()
