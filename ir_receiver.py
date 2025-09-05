# ir_receiver.py
import pigpio

# --- Konfiguration ---
# Beliebig erweiterbar: "Name": [p1_us, p2_us, p3_us, ...]
PATTERNS = {
    "082501":   [1500, 3500, 1500],
    "082502":    [3000, 4500, 3000],   # <- dein zweiter Sender
    # "sig3": [2000, 4000, 2000],    # Beispiel: einfach hinzufügen
}

TOLERANZ = 0.17          # ±17% Abweichung pro Puls
LONG_GAP_US = 8000       # Langer Abstand -> Paketgrenze/Neustart
MAX_PULSE_COUNT = 100    # Sicherheitslimit gegen Rauschen

def _within(meas: int, target: int, tol: float) -> bool:
    return abs(meas - target) <= target * tol

def _match_any_pattern(pulses):
    """
    Versucht, 'pulses' gegen alle PATTERNS zu matchen.
    Verglichen werden nur die ersten len(pattern) Pulse.
    Rückgabe: Name des Treffers oder None.
    """
    for name, pattern in PATTERNS.items():
        if len(pulses) < len(pattern):
            continue
        ok = True
        for meas, tgt in zip(pulses[:len(pattern)], pattern):
            if not _within(meas, tgt, TOLERANZ):
                ok = False
                break
        if ok:
            return name
    return None

class RawIRDecoder:
    def __init__(self, pi, gpio, callback):
        self.pi = pi
        self.gpio = gpio
        self.callback = callback
        self.last_tick = 0
        self.in_code = False
        self.pulses = []

        # GPIO einrichten
        pi.set_mode(gpio, pigpio.INPUT)
        pi.set_pull_up_down(gpio, pigpio.PUD_UP)
        pi.callback(gpio, pigpio.FALLING_EDGE, self._cb)

    def _cb(self, gpio, level, tick):
        diff = pigpio.tickDiff(self.last_tick, tick)
        self.last_tick = tick

        # Langer Abstand => voriges Paket auswerten, neues starten
        if diff > LONG_GAP_US:
            self._auswerten()
            self.pulses = []
            self.in_code = True
            return

        if self.in_code:
            self.pulses.append(diff)
            if len(self.pulses) > MAX_PULSE_COUNT:
                # Zu lang / Rauschen -> auswerten & abbrechen
                self._auswerten()
                self.in_code = False
                self.pulses = []

    def _auswerten(self):
        if not self.pulses:
            return
        name = _match_any_pattern(self.pulses)
        if name:
            # z.B. lt.py macht daraus "RAW<code>", also "RAWmycar"/"RAWcar2"
            print(f"✅ Signatur erkannt: {name} -> {self.pulses[:len(PATTERNS[name])]}")
            self.callback(name)
        else:
            print(f"⚠️ Unbekanntes Muster (erste 10 Pulse): {self.pulses[:10]}")
