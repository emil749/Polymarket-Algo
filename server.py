"""
Polymarket Empfehlungs-Algorithmus
Starte mit: python server.py
"""

from flask import Flask, jsonify, send_from_directory
import requests, numpy as np, os, threading, time
from datetime import datetime, timedelta

app = Flask(__name__, static_folder=".")

# ──────────────────────────────────────────
# DEIN KAPITAL (anpassen!)
# ──────────────────────────────────────────
BANKROLL   = 200.0   # Dein Startkapital in Dollar
MIN_EDGE   = 0.05    # Mindestens 5% Vorteil für eine Empfehlung
KELLY      = 0.25    # Konservativ: nur 25% des vollen Kelly-Einsatzes

# ──────────────────────────────────────────
# DATEN (wird alle 5 Minuten aktualisiert)
# ──────────────────────────────────────────
daten = {
    "empfehlungen": [],
    "alle_maerkte":  [],
    "letztes_update": "—",
    "naechstes_update": "—",
    "status": "Startet...",
    "quelle": "—",
}
lock = threading.Lock()


def maerkte_laden():
    """Lädt live Märkte von Polymarket."""
    try:
        r = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"active": True, "closed": False, "limit": 60},
            timeout=10,
        )
        r.raise_for_status()
        print(f"  ✓ {len(r.json())} Märkte geladen")
        return r.json(), "🟢 Live"
    except Exception as e:
        print(f"  ✗ API Fehler: {e} — nutze Beispieldaten")
        return beispiel_maerkte(), "🟡 Beispieldaten"


def beispiel_maerkte():
    """Fallback wenn Polymarket nicht erreichbar."""
    themen = [
        "Will Bitcoin reach $120k by end of 2026?",
        "Will the Fed cut rates in May 2026?",
        "Will AI beat humans at IMO 2026?",
        "Will Tesla stock exceed $400 in 2026?",
        "Will there be a US recession in 2026?",
        "Will Germany's GDP grow in Q2 2026?",
        "Will OpenAI release GPT-5 by June 2026?",
        "Will S&P 500 hit 6500 before July 2026?",
    ]
    ergebnis = []
    for i, frage in enumerate(themen):
        rng = np.random.RandomState(i * 13 + int(time.time()) % 50)
        p = round(float(rng.uniform(0.10, 0.90)), 2)
        ergebnis.append({
            "id": f"demo_{i}",
            "question": frage,
            "outcomePrices": f"[{p}, {round(1-p,2)}]",
            "volume":    round(float(rng.uniform(1000, 50000))),
            "liquidity": round(float(rng.uniform(2000, 30000))),
            "endDate":   (datetime.now() + timedelta(days=int(rng.randint(10, 180)))).isoformat(),
        })
    return ergebnis


def markt_auswerten(m):
    """Wertet einen einzelnen Markt aus."""
    try:
        # Preis parsen
        roh = m.get("outcomePrices", "[0.5,0.5]")
        if isinstance(roh, str):
            preise = [float(x.strip()) for x in roh.strip("[]").split(",")]
        else:
            preise = list(roh)

        ja_preis = float(preise[0])
        if ja_preis < 0.03 or ja_preis > 0.97:
            return None

        volumen   = float(m.get("volume", 0) or 0)
        liquidit  = float(m.get("liquidity", 0) or 0)
        if liquidit < 500 and volumen < 500:
            return None

        # Tage bis Ende
        try:
            ende = datetime.fromisoformat(m.get("endDate","").replace("Z","+00:00"))
            tage = max(0, (ende.replace(tzinfo=None) - datetime.now()).days)
        except Exception:
            tage = 30

        return {
            "id":       m.get("id",""),
            "frage":    m.get("question","Unbekannt"),
            "ja_preis": ja_preis,
            "volumen":  volumen,
            "liquidit": liquidit,
            "tage":     tage,
            "liq_score": min(liquidit / 10000, 1.0),
        }
    except Exception:
        return None


def modell_wahrscheinlichkeit(markt):
    """
    Schätzt die 'wahre' Wahrscheinlichkeit eines Marktes.
    Märkte mit extremen Preisen (sehr hoch/niedrig) sind oft
    vom Markt übertrieben — das nutzen wir aus.
    """
    p   = markt["ja_preis"]
    liq = markt["liq_score"]

    # Korrekturfaktor: extreme Preise werden etwas zur Mitte gezogen
    if   p < 0.10: anp = p * 0.70
    elif p < 0.20: anp = p * 0.85
    elif p > 0.90: anp = p + (1 - p) * 0.12
    elif p > 0.80: anp = p + (1 - p) * 0.06
    else:          anp = p

    # Kleines Rauschen (weniger bei liquiden Märkten)
    rauschen = np.random.normal(0, 0.04 * (1 - liq))
    return float(np.clip(anp + rauschen, 0.03, 0.97))


def kelly_einsatz(modell_p, markt_p):
    """Berechnet empfohlenen Einsatz nach Kelly-Kriterium."""
    edge = modell_p - markt_p
    if abs(edge) < MIN_EDGE:
        return 0.0, None

    if edge > 0:
        b         = (1 - markt_p) / (markt_p + 1e-9)
        p, q      = modell_p, 1 - modell_p
        richtung  = "JA"
    else:
        b         = markt_p / (1 - markt_p + 1e-9)
        p, q      = 1 - modell_p, modell_p
        richtung  = "NEIN"

    k = (b * p - q) / (b + 1e-9)
    einsatz = min(KELLY * k * BANKROLL, 0.05 * BANKROLL)
    return round(max(0.0, einsatz), 2), richtung


def pipeline():
    """Läuft im Hintergrund und aktualisiert alle 5 Minuten."""
    while True:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Update läuft...")
        with lock:
            daten["status"] = "Aktualisiert..."

        roh, quelle = maerkte_laden()
        alle, empfehlungen = [], []

        for m in roh:
            markt = markt_auswerten(m)
            if not markt:
                continue

            modell_p        = modell_wahrscheinlichkeit(markt)
            edge            = modell_p - markt["ja_preis"]
            einsatz, richt  = kelly_einsatz(modell_p, markt["ja_preis"])
            gewinn          = round(einsatz * abs(edge) / (markt["ja_preis"] + 1e-9), 2) if einsatz > 0 else 0

            eintrag = {
                "id":           markt["id"],
                "frage":        markt["frage"],
                "markt_p":      round(markt["ja_preis"] * 100, 1),   # in %
                "modell_p":     round(modell_p * 100, 1),             # in %
                "edge":         round(edge * 100, 1),                 # in %
                "richtung":     richt,
                "einsatz":      einsatz,
                "erw_gewinn":   gewinn,
                "volumen":      int(markt["volumen"]),
                "liquidit":     int(markt["liquidit"]),
                "tage":         markt["tage"],
                "hat_edge":     einsatz > 0,
            }
            alle.append(eintrag)
            if einsatz > 0:
                empfehlungen.append(eintrag)

        empfehlungen.sort(key=lambda x: abs(x["edge"]), reverse=True)
        jetzt     = datetime.now()
        naechstes = jetzt + timedelta(minutes=5)

        with lock:
            daten["alle_maerkte"]      = alle
            daten["empfehlungen"]      = empfehlungen
            daten["letztes_update"]    = jetzt.strftime("%H:%M:%S")
            daten["naechstes_update"]  = naechstes.strftime("%H:%M:%S")
            daten["status"]            = "OK"
            daten["quelle"]            = quelle
            daten["bankroll"]          = BANKROLL
            daten["gesamt_einsatz"]    = round(sum(e["einsatz"] for e in empfehlungen), 2)
            daten["gesamt_gewinn"]     = round(sum(e["erw_gewinn"] for e in empfehlungen), 2)

        print(f"  → {len(empfehlungen)} Empfehlungen | Einsatz: ${daten['gesamt_einsatz']}")
        time.sleep(300)   # 5 Minuten warten


# ──────────────────────────────────────────
# ROUTEN
# ──────────────────────────────────────────

@app.route("/")
def startseite():
    return send_from_directory(".", "index.html")

@app.route("/api/daten")
def api_daten():
    with lock:
        return jsonify(dict(daten))


# ──────────────────────────────────────────
# START
# ──────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    print("=" * 50)
    print("  POLYMARKET ALGORITHMUS")
    print(f"  Öffne: http://localhost:{port}")
    print(f"  Kapital: ${BANKROLL}")
    print("=" * 50)

    t = threading.Thread(target=pipeline, daemon=True)
    t.start()
    time.sleep(3)

    app.run(host="0.0.0.0", port=port, debug=False)
