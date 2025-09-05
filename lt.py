import RPi.GPIO as GPIO
GPIO.setwarnings(False)
from flask import Flask, render_template, jsonify, send_from_directory, request, redirect, url_for
from threading import Lock, Timer
from datetime import datetime
import pigpio
import json
import csv
import os
import atexit
import time
import subprocess
import zoneinfo
from config import *
from ir_receiver import RawIRDecoder
from collections import defaultdict

# --- Globale Variablen ---
lap_data = []
data_lock = Lock()
letzte_zeiten = {}   # Anzeigezeit als String "dd.mm.yy HH:MM:SS"
letzte_ts = {}       # Hochauflösender Zeitstempel via time.perf_counter()
sender_map = {}
app = Flask(__name__)

@app.context_processor
def inject_year():
    return {"current_year": datetime.now().year}

LED_PIN = 23
BATTERY_PIN = 26

pi = pigpio.pi()

# RTC-Zeit laden
subprocess.run(["sudo", "hwclock", "-s"])

# --- Zeit-/Geschwindigkeits-Helfer ---
def format_mmsshh_from_seconds(sek: float) -> str:
    """Sekunden (float) -> 'MM:SS:HH' (Hundertstel)."""
    if sek < 0:
        sek = 0.0
    total_hh = int(round(sek * 100))
    m = total_hh // 6000
    s = (total_hh // 100) % 60
    hh = total_hh % 100
    return f"{m:02}:{s:02}:{hh:02}"

def parse_time_to_seconds(zeit_str: str) -> float:
    """
    'MM:SS:HH' (Hundertstel) ODER 'HH:MM:SS' (optional mit .xx) -> Sekunden (float).
    So bleiben alte Daten kompatibel.
    """
    try:
        a, b, c = zeit_str.split(":")
        # MM:SS:HH (c genau 2 Ziffern)
        if len(c) == 2 and a.isdigit() and b.isdigit() and c.isdigit():
            return int(a) * 60 + int(b) + int(c) / 100.0
        # Fallback HH:MM:SS(.xx)
        return int(a) * 3600 + int(b) * 60 + float(c)
    except:
        return 0.0

def kmh_from_seconds(sek: float) -> float:
    """km/h aus Streckenlänge (m) und Zeit (s)."""
    try:
        if sek <= 0:
            return 0.0
        return round((RUNDENLAENGE / 1000.0) / (sek / 3600.0), 1)
    except:
        return 0.0

# --- Datei-/Sonstige Helfer ---
def lade_sender_map():
    global sender_map
    if os.path.exists(SENDER_MAP_FILE):
        with open(SENDER_MAP_FILE, "r") as f:
            sender_map = json.load(f)
    else:
        sender_map = {}

def speichere_sender_map():
    with open(SENDER_MAP_FILE, "w") as f:
        json.dump(sender_map, f, indent=2)

def battery_status_info():
    return "OK" if GPIO.input(BATTERY_PIN) == GPIO.HIGH else "LOW"

# --- IR Callback ---
def ir_callback(raw_code):
    sender_id = str(raw_code)   # kein RAW-Präfix mehr
    datum = datetime.now().strftime("%d.%m.%y")
    uhrzeit = datetime.now().strftime("%H:%M:%S")
    aktuelle_zeit = f"{datum} {uhrzeit}"

    # hochauflösende Zeit jetzt (für exakte Rundenzeit mit Hundertsteln)
    ts_now = time.perf_counter()

    # kurze LED-Bestätigung
    GPIO.output(LED_PIN, GPIO.HIGH)
    Timer(0.2, lambda: GPIO.output(LED_PIN, GPIO.LOW)).start()

    # neuen Fahrer defaultmäßig anlegen
    if sender_id not in sender_map:
        sender_map[sender_id] = f"Fahrer {sender_id}"
        speichere_sender_map()

    with data_lock:
        last_ts = letzte_ts.get(sender_id)

        if last_ts is not None:
            # exakte Rundenzeit in Sekunden (float)
            sek = ts_now - last_ts

            if sek < MIN_RUNDENZEIT:
                print(f"❌ Runde ignoriert ({sek:.2f}s) für {sender_id}")
                return

            # Rundenzeit als MM:SS:HH + km/h aus Sekunden
            rundenzeit = format_mmsshh_from_seconds(sek)
            geschwindigkeit = kmh_from_seconds(sek)
        else:
            rundenzeit = "Erste Runde"
            geschwindigkeit = 0.0

        # Anzeigezeit (nur fürs UI/CSV) + hochauflösende Zeit aktualisieren
        letzte_zeiten[sender_id] = aktuelle_zeit
        letzte_ts[sender_id] = ts_now

        lap_data.append({
            "datum": datum,
            "uhrzeit": uhrzeit,
            "rundenzeit": rundenzeit,
            "geschwindigkeit": geschwindigkeit,
            "sender_id": sender_id,
            "fahrername": sender_map.get(sender_id, sender_id)
        })

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Signal von {sender_id} – Rundenzeit: {rundenzeit}")

        with open(CSV_FILE, "w") as f:
            writer = csv.writer(f)
            writer.writerow(["Runde", "Datum", "Uhrzeit", "Sender-ID", "Fahrer", "Dauer", "Geschwindigkeit"])
            for i, r in enumerate(lap_data, 1):
                writer.writerow([
                    i, r["datum"], r["uhrzeit"], r["sender_id"], r["fahrername"], r["rundenzeit"], r["geschwindigkeit"]
                ])

# --- Flask-Routen ---
@app.route("/")
def index():
    filter_an = request.args.get("filter", "on") == "on"
    gefiltert = []

    for r in lap_data:
        try:
            if r["rundenzeit"] not in ("Erste Runde", "START"):
                sek = parse_time_to_seconds(r["rundenzeit"])
                if not filter_an or (MIN_RUNDENZEIT <= sek <= MAX_RUNDENZEIT):
                    gefiltert.append(r)
            else:
                gefiltert.append(r)
        except:
            pass

    # Durchschnitt berechnen
    durchschnitt = 0.0
    if gefiltert:
        summe = sum(
            r["geschwindigkeit"]
            for r in gefiltert
            if isinstance(r["geschwindigkeit"], (int, float))
        )
        if len(gefiltert) > 0:
            durchschnitt = round(summe / len(gefiltert), 1)

    battery_status = battery_status_info()

    # --- Sortierung nach schnellster Runde ---
    def sort_key(r):
        if r["rundenzeit"] in ("Erste Runde", "START"):
            return float("inf")  # diese nach hinten
        return parse_time_to_seconds(r["rundenzeit"])

    sortierte_runden = sorted(gefiltert, key=sort_key)

    return render_template(
        "index.html",
        rundendaten=sortierte_runden[:300],  # schnellste zuerst
        rundenlaenge=RUNDENLAENGE,
        gesamt_geschwindigkeit=durchschnitt,
        letzte_aktualisierung=datetime.now().strftime("%d.%m.%y %H:%M:%S"),
        gefiltert=filter_an,
        anzahl_runden=len(gefiltert),
        battery_status=battery_status,
        current_year=datetime.now().year
    )

@app.route("/fahrer")
def fahrer():
    # beste Zeit intern als Sekunden vergleichen, Anzeige wieder MM:SS:HH
    stats = defaultdict(lambda: {"runden": 0, "summe_kmh": 0.0, "beste_sek": None})
    for r in lap_data:
        name = r["fahrername"]
        stats[name]["runden"] += 1
        if isinstance(r["geschwindigkeit"], (int, float)):
            stats[name]["summe_kmh"] += r["geschwindigkeit"]
        if r["rundenzeit"] not in ("Erste Runde", "START"):
            sek = parse_time_to_seconds(r["rundenzeit"])
            if sek > 0 and (stats[name]["beste_sek"] is None or sek < stats[name]["beste_sek"]):
                stats[name]["beste_sek"] = sek

    fahrer_stats = []
    for name, d in stats.items():
        avg_kmh = d["summe_kmh"] / d["runden"] if d["runden"] > 0 else 0
        best_time = format_mmsshh_from_seconds(d["beste_sek"]) if d["beste_sek"] is not None else "-"
        fahrer_stats.append({
            "Fahrer": name,
            "Gesamt_Runden": d["runden"],
            "Durchschnitt_kmh": avg_kmh,
            "Beste_Rundenzeit": best_time
        })

    return render_template("fahrer.html", fahrer_stats=fahrer_stats)

@app.route("/set_time", methods=["POST"])
def set_time():
    data = request.get_json()
    client_time_str = data.get('time')

    try:
        dt_utc = datetime.fromisoformat(client_time_str.replace("Z", "+00:00"))
        berlin_tz = zoneinfo.ZoneInfo("Europe/Berlin")
        local_time = dt_utc.astimezone(berlin_tz)

        subprocess.run(["sudo", "date", "-s", local_time.strftime("%Y-%m-%d %H:%M:%S")], check=True)
        subprocess.run(["sudo", "hwclock", "-w"], check=True)

        print(f"⏱ Systemzeit synchronisiert: {local_time}")
        return jsonify({"status": "ok", "zeit": local_time.isoformat()})

    except Exception as e:
        return jsonify({"status": "Fehler", "details": str(e)}), 400

@app.route("/shutdown", methods=["POST"])
def shutdown():
    try:
        subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
        return jsonify({"status": "ok", "message": "Der Raspberry Pi wird heruntergefahren..."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/sender", methods=["GET", "POST"])
def sender():
    if request.method == "POST":
        for sid in list(sender_map.keys()):
            name = request.form.get(sid)
            if name is not None:
                if name.strip() == "":
                    del sender_map[sid]
                else:
                    sender_map[sid] = name.strip()
        speichere_sender_map()
        return redirect(url_for("sender"))
    return render_template("sender.html", sender_map=sender_map)

@app.route("/reset")
def reset():
    global lap_data, letzte_zeiten, letzte_ts
    with data_lock:
        lap_data = []
        letzte_zeiten = {}
        letzte_ts = {}
        if os.path.exists(CSV_FILE):
            os.remove(CSV_FILE)
    return redirect(url_for("index"))

@app.route("/download")
def download():
    return send_from_directory(os.getcwd(), CSV_FILE, as_attachment=True)

@app.route("/api/laps")
def api():
    return jsonify(lap_data[-300:])

# --- Aufräumen ---
def cleanup():
    GPIO.output(LED_PIN, GPIO.LOW)
    GPIO.cleanup()
    pi.stop()
    subprocess.run(["sudo", "hwclock", "-w"])

# --- Start ---
if __name__ == "__main__":
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(IR_RX_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(LED_PIN, GPIO.OUT)
    GPIO.setup(BATTERY_PIN, GPIO.IN)
    GPIO.output(LED_PIN, GPIO.LOW)

    # Boot-Blink
    GPIO.output(LED_PIN, GPIO.HIGH)
    time.sleep(0.5)
    GPIO.output(LED_PIN, GPIO.LOW)

    lade_sender_map()
    decoder = RawIRDecoder(pi, IR_RX_PIN, ir_callback)
    atexit.register(cleanup)

    print(f"🏁 Empfänger bereit auf GPIO{IR_RX_PIN}. Webinterface: http://<IP>:5000")

    # Wichtig: kein Debug, kein Reloader, kein Threading
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False, threaded=False)












































