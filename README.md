# GreenGauge

Energy, money and carbon per piece for Indian SMEs. This repo currently contains **Step 1: the plant simulator**.

## Run it in VS Code

1. Open this folder in VS Code (File → Open Folder).
2. Open the terminal (Ctrl + `) and run:

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# Mac / Linux:  source .venv/bin/activate
pip install -r requirements.txt

cd simulator
python simulator.py --days 7 --faults all     # plant before GreenGauge
python simulator.py --days 7 --faults none    # same plant with problems fixed
python plot.py --data output/faulty           # opens output/faulty/overview.png
```

A 7-day run takes a few seconds. Use `--days 30` for a month.

## Faults you can switch on

`--faults all`, `--faults none`, or any comma list:

| Flag | What happens | Starts |
|---|---|---|
| `leak` | Compressed-air leaks rise from 5% to 30% of capacity | day 0 |
| `idle` | Mixer and shot-blast idle through breaks; fan and compressor sometimes left on overnight | day 0 |
| `pf` | 90% of APFC capacitor steps fail: PF drops, contract demand gets breached | day 3 |
| `motor` | Cooling pump current imbalance creeps up to 8% | day 2 |

Start days and severities live in `plant_spec.yaml`.

## Output files (in `simulator/output/<scenario>/`)

- **machines.csv**: one row per machine per minute. Columns: `kw, kvar, ia, ib, ic, status, loaded_s` (compressor only: seconds loaded in that minute) and `fault_label` (ground truth for testing your detectors).
- **incomer.csv**: the main plant meter, one row per minute. Columns: `kw, kvar, kva, pf, voltage, ia/ib/ic, apfc_kvar, ambient_c, shift, producing, pieces, fault_label`.
- **production.csv**: pieces per shift, the way an operator would log them.
- **summary.json**: kWh, pieces, kWh/piece, PF, max demand, cost, CO2, idle waste.

Compare `output/faulty/summary.json` with `output/healthy/summary.json`. The difference is your quantified benefit against a stated baseline.

## Assumptions

All plant, tariff and emission-factor numbers are in `plant_spec.yaml`, and each one is a modelling assumption.
Before submission, replace them with cited sources: BEE/SIDBI cluster studies, equipment datasheets, the current TNERC tariff order, and the CEA CO2 Baseline Database.

## Next steps

1. Modbus meter emulator (pymodbus) serving incomer data, and a gateway that polls it and publishes over MQTT.
2. TimescaleDB storage.
3. FastAPI analytics: baseline regression, leak test, idle detection, PF/MD alerts, motor health, recommendations.
4. Dashboard and alerts.
