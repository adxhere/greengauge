# GreenGauge

Energy, money and carbon per piece for Indian SMEs.

```
simulated plant ──► Modbus meters ──► edge gateway ──► MQTT ──► ingester ──► TimescaleDB ──► analytics API ──► dashboard
 (simulator/)        (meter/)          (gateway/)     (mosquitto) (ingest/)    (db/)          (analytics/)      (dashboard/)
```

| Folder | What it is |
|---|---|
| `simulator/` | Step 1: simulated Coimbatore foundry with switchable faults |
| `meter/` | Replays simulator data as live Modbus TCP energy meters (1 incomer + 7 machine CTs) |
| `gateway/` | Edge gateway: polls the meters, publishes JSON to MQTT |
| `ingest/` | Subscribes to MQTT, writes to TimescaleDB |
| `common/registers.py` | The Modbus register map (shared by meter and gateway) |
| `config/devices.yaml` | Which meters the gateway polls: the only file you'd change for a real plant |
| `db/init.sql` | Database tables |
| `analytics/` | FastAPI service: energy per piece, baseline, leaks, idle waste, PF/demand, motor health, recommendations, alerts |
| `config/analytics.yaml` | Tariff, detection rules and cost assumptions for the analytics |
| `dashboard/` | React dashboard: overview, live plant, fixes & payback, plant health, carbon certificate |
| `tools/backfill.py` | Instantly loads "before GreenGauge" history so the analytics have a baseline |

## Run the full pipeline (Docker)

Needs Docker Desktop running. From the project folder:

```bash
docker compose up --build
```

The first run takes a few minutes (it downloads images and generates the scenarios).
After that, a new minute of plant data flows through every second.

Useful commands (in a second terminal):

```bash
# watch live messages
docker compose exec mqtt mosquitto_sub -t "greengauge/#" -v

# flip a fault live during a demo
docker compose exec mqtt mosquitto_pub -t greengauge/control/scenario -m leak
#   scenarios: healthy, faulty (all faults), leak, idle, pf, motor

# stop (data kept) / stop and wipe everything
docker compose down
docker compose down -v
```

Browse the database at **http://localhost:8080** (Adminer):
System `PostgreSQL`, server `db`, user `greengauge`, password `greengauge`, database `greengauge`.

Tables:
- `incomer_readings`: the main meter, per minute
- `machine_readings`: each machine, per minute
- `incomer_with_pieces`: a view that adds pieces produced per minute

Change the replay settings with environment variables, for example in PowerShell:

```powershell
$env:SPEED="120"; $env:SCENARIO="faulty"; $env:START="2026-09-11 05:50"; docker compose up
```

`SPEED` is simulated seconds per real second (60 = one minute per second). Keep it at 120 or below,
or the gateway may skip minutes.

## Analytics (step 3)

Once `docker compose up` is running, load three days of "before GreenGauge" history (in a second terminal):

```bash
docker compose exec analytics python tools/backfill.py --scenario faulty
```

The live replay (healthy by default) then continues from where the history ends, so the
analytics can measure the improvement against the faulty baseline.

Open **http://localhost:8000/docs** to try every endpoint in the browser.

| Endpoint | What it returns |
|---|---|
| `/api/summary` | Everything the dashboard home screen needs, in one call |
| `/api/overview` | Totals and daily kWh, ₹, kgCO2 per piece |
| `/api/baseline` | Baseline model (IPMVP-style), CV(RMSE), measured savings |
| `/api/idle` | Machines running when they should be off, in kWh and ₹ |
| `/api/leaks` | Compressed-air leak test (load/unload method) |
| `/api/power` | Power factor, maximum demand vs contract, APFC health |
| `/api/motors` | Motor current imbalance, trend, days to alarm |
| `/api/carbon` | Carbon-per-piece certificate data |
| `/api/recommendations` | Fixes ranked by payback, with capex and ₹/year |
| `/api/alerts` | Problems happening right now |
| `/api/live` | Latest reading for every meter |
| `/api/timeseries`, `/api/timeseries/machines` | Chart data |

Most endpoints take `?days=7` (analysis window). "Now" is the latest reading in the
database, so the analytics work the same on replayed and live data.

Detection rules, tariff and cost assumptions live in `config/analytics.yaml`.

## Dashboard (step 4)

With the stack running, open **http://localhost:3000**.

| Screen | What it shows |
|---|---|
| Overview | Cost, kWh and CO2 per casting, money wasted, savings on the table, alerts, top fixes |
| Live plant | Every meter, updating every 3 seconds; machines wasting power turn amber with ₹ counting up |
| Fixes & payback | Tick fixes on and off; cost, savings, payback and CO2 recalculate instantly |
| Plant health | Power factor trend, maximum demand gauge, air leak test, motor health |
| Carbon certificate | Printable kg CO2 per casting statement (Print or save as PDF) |

Demo tip: open the Live plant screen, then flip a fault in another terminal
(`docker compose exec mqtt mosquitto_pub -t greengauge/control/scenario -m faulty`)
and watch the machines react.

To work on the dashboard without Docker (hot reload):

```bash
cd dashboard
npm install
npm run dev          # http://localhost:3000, talks to the API on localhost:8000
```

## Telegram alerts (step 5)

New problems go to the shift supervisor on Telegram, in English and Tamil. When a machine
that was left running is switched off, a follow-up message reports what it cost.

1. On Telegram, message **@BotFather**, send `/newbot`, and copy the token.
2. From the supervisor's phone, send the new bot any message.
3. Find the chat id: `python tools/telegram_chat_id.py YOUR_TOKEN`
4. Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
   (`.env` is git-ignored: never commit your token.)
5. `docker compose up -d alerts` (or restart the whole stack).

Without a token the service runs in dry-run mode and only prints messages in its logs:
`docker compose logs -f alerts`

Alerts already active when the service starts are not re-sent; flip a fault
(`mosquitto_pub ... -m faulty`) to trigger fresh ones during a demo.

## Public demo site (Vercel)

Vercel can host the dashboard but not the backend (Docker, database, MQTT), so the
deployed site runs in **snapshot mode**: it shows a recorded moment of the real system,
stored in `dashboard/public/demo/`. The live system still runs locally with Docker.

Deploy:
1. Push the repo to GitHub.
2. On vercel.com: **Add New → Project**, import the repo.
3. Set **Root Directory** to `dashboard`. Everything else comes from `dashboard/vercel.json`.
4. Deploy.

Record a new snapshot (with the stack running and the moment you want on screen):

```bash
python tools/export_demo.py
git add dashboard/public/demo && git commit -m "New demo snapshot" && git push
```

Vercel redeploys automatically after every push.

## Run step 1 only (no Docker)

```bash
python -m venv .venv
.venv\Scripts\activate            # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cd simulator
python simulator.py --faults all
python plot.py --data output/faulty
```

## Modbus register map

Holding registers, big-endian, high word first. Unit 1 = incomer, units 11-17 = machines.
See `common/registers.py` for the full table.

| Addr | Field | Type |
|---|---|---|
| 0 | timestamp (unix s) | uint32 |
| 2-16 | kW, kVAR, kVA, PF, voltage, Ia, Ib, Ic | float32 |
| 18 | cumulative energy (Wh) | uint32 |
| 20 | status (0 off, 1 idle, 2 running) | uint16 |
| 21 | compressor loaded seconds | uint16 |
| 22 | production pulse counter | uint32 |
| 24 | ambient °C | float32 |
| 26 | shift (0 none, 1 A, 2 B) | uint16 |
| 27 | producing | uint16 |

Ground-truth fault labels are deliberately **not** sent through the meters (a real meter
can't know why power is wasted). They stay in the simulator CSVs for testing the analytics.

## Assumptions and sources

- Tariff: TNERC Tariff Order No. 6 of 2025 (HT I-A, effective 1 July 2025): ₹7.50/kWh, ₹608/kVA/month,
  +25% peak (06-10, 18-22), -5% off-peak. Set in `config/analytics.yaml`.
- Grid emission factor: CEA CO2 Baseline Database v21.0, FY 2024-25: 0.710 tCO2/MWh.
- Plant: a typical small induction foundry (equipment sizes, schedules, fault severities) in
  `simulator/plant_spec.yaml`. These are modelling assumptions, not measurements.
- Fix costs in `config/analytics.yaml` are indicative estimates: use vendor quotes for a real plant.

## Next steps

All five build steps are complete. See `config/analytics.yaml` for tariff and emission-factor sources.
