"""
Polymarket Empfehlungs-Algorithmus
"""

from flask import Flask, jsonify, send_from_directory
import requests, numpy as np, os, threading, time, json
from datetime import datetime, timedelta

app = Flask(__name__, static_folder=".")

BANKROLL  = 200.0   # Dein Kapital in Dollar
MIN_EDGE  = 0.04    # Mindest-Vorteil (4%)
KELLY     = 0.25    # Konservativer Kelly-Faktor

daten = {
    "empfehlungen":    [],
    "alle_maerkte":    [],
    "letztes_update":  "—",
    "naechstes_update":"—",
    "status":          "Startet...",
    "quelle":          "—",
    "bankroll":        BANKROLL,
    "gesamt_einsatz":  0,
    "gesamt_gewinn":   0,
    "debug":           "",
}
lock = threading.Lock()


def preis_parsen(roh):
    """Parst outcomePrices egal in welchem Format."""
    if roh is None:
        return None
    try:
        # Fall 1: schon eine Liste
        if isinstance(roh, list):
            return [float(x) for x in roh]
        # Fall 2: JSON-String  z.B. '["0.72","0.28"]'
        if isinstance(roh, str):
            parsed = json.loads(roh)
            return [float(x) for x in parsed]
    except Exception:
        pass
    return None


def maerkte_laden():
    """Lädt Märkte von Polymarket Gamma API."""
    urls = [
        "https://gamma-api.polymarket.com/markets",
        "https://strapi-matic.poly.market/markets",
    ]
    for url in urls:
        try:
            r = requests.get(
                url,
                params={"active": "true", "closed": "false", "limit": 100},
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            r.raise_for_status()
            data = r.json()
            # Manchmal kommt ein Dict mit "data" drin
            if isinstance(data, dict):
                data = data.get("data", data.get("markets", []))
            if isinstance(data, list) and len(data) > 0:
                print(f"  ✓ {len(data)} Märkte von {url}")
                return data, "🟢 Live"
        except Exception as e:
            print(f"  ✗ {url} Fehler: {e}")
            continue

    print("  → Nutze Beispieldaten")
    return beispiel_maerkte(), "🟡 Beispieldaten"


def beispiel_maerkte():
    themen = [
        ("Will Bitcoin reach $120k by end of 2026?", 0.38),
        ("Will the Fed cut rates in May 2026?",       0.52),
        ("Will Tesla stock exceed $400 in 2026?",     0.29),
        ("Will there be a US recession in 2026?",     0.41),
        ("Will OpenAI release GPT-5 by June 2026?",  0.67),
        ("Will S&P 500 hit 6500 before July 2026?",  0.55),
        ("Will Ethereum reach $5000 in 2026?",        0.33),
        ("Will Germany win the 2026 World Cup?",      0.08),
        ("Will inflation drop below 2% in the EU?",  0.44),
        ("Will NATO expand membership in 2026?",      0.21),
    ]
    ergebnis = []
    for i, (frage, p) in enumerate(themen):
        ergebnis.append({
            "id":            f"demo_{i}",
            "question":      frage,
            "outcomePrices": json.dumps([str(p), str(round(1-p, 2))]),
            "volume":        round(float(np.random.uniform(5000, 80000))),
            "liquidity":     round(float(np.random.uniform(3000, 40000))),
            "endDate":       (datetime.now() + timedelta(days=int(np.random.randint(20,200)))).isoformat(),
        })
    return ergebnis


def markt_auswerten(m):
    """Wertet einen Markt aus und gibt strukturierte Daten zurück."""
    try:
        # Preis holen — verschiedene Feldnamen probieren
        preise = None
        for feld in ["outcomePrices", "lastTradePrice", "prices"]:
            roh = m.get(feld)
            if roh is not None:
                preise = preis_parsen(roh)
                if preise:
                    break

        # Einzelner Preis-Wert (manche APIs geben nur einen Wert)
        if preise is None:
            einzel = m.get("price") or m.get("lastPrice")
            if einzel is not None:
                p = float(einzel)
                preise = [p, 1 - p]

        if preise is None or len(preise) < 2:
            return None

        ja_preis = float(preise[0])
        if ja_preis < 0.02 or ja_preis > 0.98:
            return None

        # Volumen & Liquidität
        vol = float(m.get("volume", 0) or m.get("volumeNum", 0) or 0)
        liq = float(m.get("liquidity", 0) or m.get("liquidityNum", 0) or 0)

        # Sehr niedrige Schwelle — lieber mehr Märkte anzeigen
        if liq < 100 and vol < 100:
            return None

        # Laufzeit
        try:
            ende = m.get("endDate") or m.get("end_date") or m.get("resolutionTime", "")
            dt   = datetime.fromisoformat(str(ende).replace("Z", "+00:00"))
            tage = max(0, (dt.replace(tzinfo=None) - datetime.now()).days)
        except Exception:
            tage = 30

        frage = m.get("question") or m.get("title") or m.get("name") or "?"

        return {
            "id":        str(m.get("id", "")),
            "frage":     str(frage),
            "ja_preis":  ja_preis,
            "volumen":   vol,
            "liquidit":  liq,
            "tage":      tage,
            "liq_score": min(liq / 10000, 1.0),
        }
    except Exception as e:
        return None


def modell_wahrscheinlichkeit(markt):
    """Schätzt die wahre Wahrscheinlichkeit."""
    p   = markt["ja_preis"]
    liq = markt["liq_score"]

    # Märkte mit extremen Preisen sind oft verzerrt
    if   p < 0.08: anp = p * 0.65
    elif p < 0.18: anp = p * 0.82
    elif p < 0.28: anp = p * 0.93
    elif p > 0.92: anp = p + (1-p) * 0.15
    elif p > 0.82: anp = p + (1-p) * 0.08
    elif p > 0.72: anp = p + (1-p) * 0.04
    else:          anp = p

    rauschen = np.random.normal(0, 0.03 * (1 - liq))
    return float(np.clip(anp + rauschen, 0.02, 0.98))


def kelly_einsatz(modell_p, markt_p):
    edge = modell_p - markt_p
    if abs(edge) < MIN_EDGE:
        return 0.0, None

    if edge > 0:
        b, p, q   = (1 - markt_p) / (markt_p + 1e-9), modell_p, 1 - modell_p
        richtung  = "JA"
    else:
        b, p, q   = markt_p / (1 - markt_p + 1e-9), 1 - modell_p, modell_p
        richtung  = "NEIN"

    k       = max(0, (b * p - q) / (b + 1e-9))
    einsatz = min(KELLY * k * BANKROLL, 0.06 * BANKROLL)
    return round(einsatz, 2), richtung


def pipeline():
    while True:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Update...")
        with lock:
            daten["status"] = "Aktualisiert..."

        roh, quelle = maerkte_laden()
        alle, empfehlungen = [], []
        fehler_count = 0

        for m in roh:
            markt = markt_auswerten(m)
            if not markt:
                fehler_count += 1
                continue

            modell_p       = modell_wahrscheinlichkeit(markt)
            edge           = modell_p - markt["ja_preis"]
            einsatz, richt = kelly_einsatz(modell_p, markt["ja_preis"])
            gewinn         = round(einsatz * abs(edge) / (markt["ja_preis"] + 1e-9), 2) if einsatz > 0 else 0

            eintrag = {
                "id":        markt["id"],
                "frage":     markt["frage"],
                "markt_p":   round(markt["ja_preis"] * 100, 1),
                "modell_p":  round(modell_p * 100, 1),
                "edge":      round(edge * 100, 1),
                "richtung":  richt,
                "einsatz":   einsatz,
                "erw_gewinn":gewinn,
                "volumen":   int(markt["volumen"]),
                "liquidit":  int(markt["liquidit"]),
                "tage":      markt["tage"],
                "hat_edge":  einsatz > 0,
            }
            alle.append(eintrag)
            if einsatz > 0:
                empfehlungen.append(eintrag)

        empfehlungen.sort(key=lambda x: abs(x["edge"]), reverse=True)
        jetzt     = datetime.now()
        naechstes = jetzt + timedelta(minutes=5)

        debug_info = f"{len(roh)} geladen, {len(alle)} gültig, {fehler_count} übersprungen"
        print(f"  → {debug_info}")
        print(f"  → {len(empfehlungen)} Empfehlungen")

        with lock:
            daten["alle_maerkte"]       = alle
            daten["empfehlungen"]       = empfehlungen
            daten["letztes_update"]     = jetzt.strftime("%H:%M:%S")
            daten["naechstes_update"]   = naechstes.strftime("%H:%M:%S")
            daten["status"]             = "OK"
            daten["quelle"]             = quelle
            daten["bankroll"]           = BANKROLL
            daten["gesamt_einsatz"]     = round(sum(e["einsatz"] for e in empfehlungen), 2)
            daten["gesamt_gewinn"]      = round(sum(e["erw_gewinn"] for e in empfehlungen), 2)
            daten["debug"]              = debug_info

        time.sleep(300)


@app.route("/")
def startseite():
    return send_from_directory(".", "index.html")

@app.route("/api/daten")
def api_daten():
    with lock:
        return jsonify(dict(daten))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 50)
    print("  POLYMARKET ALGORITHMUS")
    print(f"  http://localhost:{port}")
    print(f"  Kapital: ${BANKROLL}")
    print("=" * 50)

    t = threading.Thread(target=pipeline, daemon=True)
    t.start()
    time.sleep(4)
    app.run(host="0.0.0.0", port=port, debug=False)
