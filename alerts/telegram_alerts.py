#!/usr/bin/env python3
"""
GreenGauge alerts: sends new problems to the shift supervisor on Telegram, in English and Tamil.

Watches /api/alerts on the analytics service. Each new alert is sent once; repeats of the same
kind of problem on the same machine are held back for a cool-down period, and when a machine
that was left running is finally switched off, a "resolved" message reports what it cost.

Settings (environment variables, usually from the project's .env file):
  TELEGRAM_BOT_TOKEN   from @BotFather            (leave empty for dry-run: messages are only logged)
  TELEGRAM_CHAT_ID     the supervisor's chat id    (see tools/telegram_chat_id.py)
  API_URL              default http://analytics:8000
  POLL_SECONDS         default 15
  LANGUAGES            default "en,ta"
  SEND_EXISTING        "true" to also send alerts already active when the service starts
  DASHBOARD_URL        optional link added to each message
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from html import escape

log = logging.getLogger("alerts")

API_URL = os.getenv("API_URL", "http://analytics:8000").rstrip("/")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
POLL = float(os.getenv("POLL_SECONDS", "15"))
LANGS = [x.strip() for x in os.getenv("LANGUAGES", "en,ta").split(",") if x.strip()]
SEND_EXISTING = os.getenv("SEND_EXISTING", "false").lower() == "true"
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "").strip()

# minutes before the same kind of alert on the same machine is sent again
COOLDOWN = {"idle_running": 0, "air_leak": 360, "power_factor": 240, "max_demand": 120, "motor_health": 720}

NAMES = {
    "en": {"air_compressor": "Air compressor", "dust_collector_fan": "Dust collector fan", "sand_mixer": "Sand mixer",
           "shot_blast": "Shot blast", "cooling_pump": "Cooling pump", "induction_furnace": "Induction furnace",
           "lighting_aux": "Lighting", "main_incomer": "Main incomer"},
    "ta": {"air_compressor": "காற்று அமுக்கி (கம்ப்ரஸர்)", "dust_collector_fan": "தூசு சேகரிப்பான் விசிறி",
           "sand_mixer": "மணல் கலவை இயந்திரம்", "shot_blast": "ஷாட் பிளாஸ்ட் இயந்திரம்",
           "cooling_pump": "குளிரூட்டும் பம்ப்", "induction_furnace": "இண்டக்ஷன் உலை",
           "lighting_aux": "விளக்குகள்", "main_incomer": "முதன்மை மின் இணைப்பு"},
}


def name(dev: str, lang: str) -> str:
    return NAMES.get(lang, {}).get(dev) or dev.replace("_", " ").capitalize()


def inr(n) -> str:
    s = str(int(round(float(n or 0))))
    if len(s) <= 3:
        return "₹" + s
    head, parts = s[:-3], []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "₹" + ",".join(parts) + "," + s[-3:]


def duration(minutes, lang: str) -> str:
    m = int(round(float(minutes or 0)))
    h, m = divmod(m, 60)
    if lang == "ta":
        return f"{h} மணி {m} நிமிடம்" if h else f"{m} நிமிடம்"
    return f"{h} h {m} min" if h else f"{m} min"


# ---------------------------------------------------------------- message templates
def render(alert: dict, lang: str) -> str:
    cat, dev, v = alert.get("category"), alert.get("device", ""), alert.get("values") or {}
    n = name(dev, lang)
    if cat == "idle_running":
        after = v.get("when") == "after_hours"
        if lang == "ta":
            when = "ஷிப்ட் முடிந்த பிறகும்" if after else "இடைவேளையின் போதும்"
            return (f"⚠️ {n} {when} இயங்குகிறது: {duration(v.get('minutes'), 'ta')}, "
                    f"இதுவரை {inr(v.get('cost_inr'))} வீணானது. தயவுசெய்து அணைக்கவும்.")
        when = "after the shift ended" if after else "through the break"
        return (f"⚠️ {n} is still running {when}: {duration(v.get('minutes'), 'en')}, "
                f"{inr(v.get('cost_inr'))} wasted so far. Please switch it off.")
    if cat == "air_leak":
        pct = round(float(v.get("leak_pct", 0)))
        if lang == "ta":
            return (f"🔧 அழுத்தக் காற்று கசிவு: கம்ப்ரஸர் உற்பத்தியில் சுமார் {pct}% கசிகிறது (இலக்கு 10% அல்லது குறைவு). "
                    f"குழாய்கள், இணைப்புகள், வடிகால் வால்வுகளைச் சரிபார்க்கவும்.")
        return (f"🔧 Compressed-air leak: about {pct}% of the compressor's output is leaking (target 10% or less). "
                f"Check hoses, fittings and drain valves.")
    if cat == "power_factor":
        pf = float(v.get("pf", 0))
        if lang == "ta":
            return f"⚡ பவர் ஃபேக்டர் குறைவு: {pf:.2f} (0.95-க்கு மேல் இருக்க வேண்டும்). APFC கெபாசிட்டர் பேனலைச் சரிபார்க்கவும்."
        return f"⚡ Low power factor: {pf:.2f} (should be above 0.95). Check the APFC capacitor panel."
    if cat == "max_demand":
        kva, contract = round(float(v.get("kva", 0))), v.get("contract_kva")
        if lang == "ta":
            return (f"📈 இந்த அரை மணி நேரத்தில் தேவை {kva} kVA, ஒப்பந்த வரம்பு {contract} kVA. "
                    f"அடுத்த அரை மணி நேரம் வரை பெரிய இயந்திரங்களைத் தொடங்க வேண்டாம்.")
        return (f"📈 Demand is {kva} kVA this half-hour against a {contract} kVA contract. "
                f"Hold off starting large machines until the next half-hour.")
    if cat == "motor_health":
        x = float(v.get("imbalance_pct", 0))
        if lang == "ta":
            return f"🛠️ {n} மோட்டார்: மின்னோட்ட சமநிலையின்மை {x:.1f}% (5%-ல் அபாய நிலை). பழுதாகும் முன் பரிசோதனை செய்யவும்."
        return f"🛠️ {n} motor: current imbalance {x:.1f}% (alarm at 5%). Schedule an inspection before it fails."
    return alert.get("message", "") if lang == "en" else ""


def render_resolved(alert: dict, lang: str) -> str:
    v, n = alert.get("values") or {}, name(alert.get("device", ""), lang)
    if lang == "ta":
        return f"✅ {n} அணைக்கப்பட்டது. மொத்த வீணடிப்பு: {inr(v.get('cost_inr'))} ({duration(v.get('minutes'), 'ta')})."
    return f"✅ {n} is off. Total wasted: {inr(v.get('cost_inr'))} over {duration(v.get('minutes'), 'en')}."


def compose(parts: list[str], severity: str | None = None) -> str:
    head = "<b>GreenGauge</b>" + (" · <b>ALARM</b>" if severity == "alarm" else "")
    body = "\n\n".join(escape(p) for p in parts if p)
    link = f'\n\n<a href="{escape(DASHBOARD_URL)}">Open dashboard</a>' if DASHBOARD_URL else ""
    return f"{head}\n\n{body}{link}"


# ---------------------------------------------------------------- state machine
class Tracker:
    """Decides which alerts to send: new ones, respecting cool-downs, plus 'resolved' for idle machines."""

    def __init__(self, send_existing: bool = False):
        self.active: dict[str, dict] = {}
        self.last_sent: dict[tuple, float] = {}
        self.first = not send_existing

    def update(self, alerts: list[dict], now: float) -> list[str]:
        out = []
        current = {a["id"]: a for a in alerts}
        for aid, a in current.items():
            if aid in self.active:
                continue
            key = (a.get("category"), a.get("device"))
            cool = COOLDOWN.get(a.get("category"), 60) * 60
            if self.first:
                log.info("already active at start (not sent): %s", a.get("title"))
            elif key in self.last_sent and now - self.last_sent[key] < cool:
                log.info("cool-down, not re-sent: %s", a.get("title"))
            else:
                out.append(compose([render(a, lang) for lang in LANGS], a.get("severity")))
                self.last_sent[key] = now
        for aid, a in self.active.items():
            if aid not in current and a.get("category") == "idle_running" and not self.first:
                out.append(compose([render_resolved(a, lang) for lang in LANGS]))
        # keep the latest values of each active alert (running cost keeps growing)
        self.active = current
        self.first = False
        return out


# ---------------------------------------------------------------- I/O
def get_alerts() -> list[dict]:
    with urllib.request.urlopen(f"{API_URL}/api/alerts", timeout=30) as r:
        return json.loads(r.read())


def send(text: str) -> bool:
    if not (TOKEN and CHAT_ID):
        log.info("DRY RUN (no Telegram token/chat set), would send:\n%s\n", text)
        return True
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data, timeout=20) as r:
            ok = json.loads(r.read()).get("ok", False)
            if not ok:
                log.warning("Telegram refused the message")
            return ok
    except urllib.error.HTTPError as e:
        log.warning("Telegram error %s: %s", e.code, e.read().decode(errors="replace")[:200])
    except OSError as e:
        log.warning("Telegram not reachable: %s", e)
    return False


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    mode = "Telegram" if TOKEN and CHAT_ID else "DRY RUN (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to send)"
    log.info("GreenGauge alerts: %s | languages %s | polling %s every %.0fs", mode, LANGS, API_URL, POLL)
    tracker = Tracker(send_existing=SEND_EXISTING)
    while True:
        try:
            for msg in tracker.update(get_alerts(), time.time()):
                send(msg)
        except (urllib.error.URLError, OSError, ValueError) as e:
            log.warning("analytics not reachable yet (%s), retrying...", e)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
