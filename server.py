"""
Polymarket Empfehlungs-Algorithmus
"""

from flask import Flask, jsonify, send_from_directory
import requests, numpy as np, os, threading, time, json
from datetime import datetime, timedelta

app = Flask(__name__, static_folder=".")

BANKROLL  = 200.0   # Dein Kapital in Dollar
MIN_EDGE  = 0.02    # Mindest-Vorteil (2%) — niedrig damit mehr Wetten angezeigt werden
KELLY     = 0.25    # Konservativer Kelly-Faktor

daten = {
    "empfehlungen":    [],
    "top10":           [],
    "top10_bald":      [],   # ← Bald endende Wetten
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
    if roh is None:
        return None
    try:
        if isinstance(roh, list):
            return [float(x) for x in roh]
        if isinstance(roh, str):
            parsed = json.loads(roh)
            return [float(x) for x in parsed]
    except Exception:
        pass
    return None


def polymarket_link(m):
    """Baut den direkten Polymarket-Link für einen Markt."""
    # Versuche slug direkt aus API
    slug = m.get("slug") or m.get("marketSlug") or m.get("conditionId", "")
    if slug:
        return f"https://polymarket.com/event/{slug}"
    # Fallback: Markt-ID
    mid = m.get("id", "")
    if mid and not str(mid).startswith("demo"):
        return f"https://polymarket.com/market/{mid}"
    return "https://polymarket.com/markets"


def maerkte_laden():
    try:
        r = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"active": "true", "closed": "false", "limit": 100},
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            data = data.get("data", data.get("markets", []))
        if isinstance(data, list) and len(data) > 0:
            print(f"  ✓ {len(data)} Märkte geladen")
            return data, "🟢 Live"
    except Exception as e:
        print(f"  ✗ API Fehler: {e}")

    print("  → Nutze Beispieldaten")
    return beispiel_maerkte(), "🟡 Beispieldaten"


def beispiel_maerkte():
    themen = [
        ("Will Bitcoin reach $120k by end of 2026?",  0.38, "will-bitcoin-reach-120k-2026"),
        ("Will the Fed cut rates in May 2026?",        0.52, "will-fed-cut-rates-may-2026"),
        ("Will Tesla stock exceed $400 in 2026?",      0.29, "will-tesla-exceed-400-2026"),
        ("Will there be a US recession in 2026?",      0.41, "will-us-recession-2026"),
        ("Will OpenAI release GPT-5 by June 2026?",   0.67, "will-openai-release-gpt5-june-2026"),
        ("Will S&P 500 hit 6500 before July 2026?",   0.55, "will-sp500-hit-6500-july-2026"),
        ("Will Ethereum reach $5000 in 2026?",         0.33, "will-ethereum-reach-5000-2026"),
        ("Will Germany win the 2026 World Cup?",       0.08, "will-germany-win-world-cup-2026"),
        ("Will inflation drop below 2% in the EU?",   0.44, "will-inflation-drop-2pct-eu"),
        ("Will NATO expand membership in 2026?",       0.21, "will-nato-expand-2026"),
    ]
    ergebnis = []
    for i, (frage, p, slug) in enumerate(themen):
        ergebnis.append({
            "id":            f"demo_{i}",
            "question":      frage,
            "slug":          slug,
            "outcomePrices": json.dumps([str(p), str(round(1-p, 2))]),
            "volume":        round(float(np.random.uniform(5000, 80000))),
            "liquidity":     round(float(np.random.uniform(3000, 40000))),
            "endDate":       (datetime.now() + timedelta(days=int(np.random.randint(20,200)))).isoformat(),
        })
    return ergebnis


def markt_auswerten(m):
    try:
        preise = None
        for feld in ["outcomePrices", "lastTradePrice", "prices"]:
            roh = m.get(feld)
            if roh is not None:
                preise = preis_parsen(roh)
                if preise:
                    break

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

        vol = float(m.get("volume", 0) or 0)
        liq = float(m.get("liquidity", 0) or 0)
        if liq < 100 and vol < 100:
            return None

        try:
            ende     = m.get("endDate") or m.get("end_date") or ""
            dt       = datetime.fromisoformat(str(ende).replace("Z", "+00:00"))
            dt_de    = dt.replace(tzinfo=None) + timedelta(hours=1)   # deutsche Zeit (UTC+1)
            jetzt_de = datetime.utcnow() + timedelta(hours=1)
            tage_raw = (dt_de - jetzt_de).days
            # Abgelaufene Märkte komplett ignorieren
            if tage_raw < 0:
                return None
            tage     = tage_raw
            endet_am = dt_de.strftime("%-d.%-m.%Y um %H:%M")
        except Exception:
            tage     = 30
            endet_am = "Unbekannt"

        frage = m.get("question") or m.get("title") or "?"

        return {
            "id":        str(m.get("id", "")),
            "frage":     str(frage),
            "ja_preis":  ja_preis,
            "volumen":   vol,
            "liquidit":  liq,
            "tage":      tage,
            "endet_am":  endet_am,             # ← Ablaufdatum deutsche Zeit
            "liq_score": min(liq / 10000, 1.0),
            "link":      polymarket_link(m),
        }
    except Exception:
        return None


def modell_wahrscheinlichkeit(markt):
    p   = markt["ja_preis"]
    liq = markt["liq_score"]

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
        b, p, q  = (1 - markt_p) / (markt_p + 1e-9), modell_p, 1 - modell_p
        richtung = "JA"
    else:
        b, p, q  = markt_p / (1 - markt_p + 1e-9), 1 - modell_p, modell_p
        richtung = "NEIN"

    k       = max(0, (b * p - q) / (b + 1e-9))
    einsatz = min(KELLY * k * BANKROLL, 0.06 * BANKROLL)
    return round(einsatz, 2), richtung


def gewinn_chance(modell_p, richtung, markt_p):
    """Berechnet die geschätzte Gewinnchance in %."""
    if richtung == "JA":
        return round(modell_p * 100, 1)
    else:
        return round((1 - modell_p) * 100, 1)


def pipeline():
    while True:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Update...")
        with lock:
            daten["status"] = "Aktualisiert..."

        roh, quelle = maerkte_laden()
        alle, empfehlungen = [], []

        for m in roh:
            markt = markt_auswerten(m)
            if not markt:
                continue

            modell_p       = modell_wahrscheinlichkeit(markt)
            edge           = modell_p - markt["ja_preis"]
            einsatz, richt = kelly_einsatz(modell_p, markt["ja_preis"])
            gewinn         = round(einsatz * abs(edge) / (markt["ja_preis"] + 1e-9), 2) if einsatz > 0 else 0
            chance         = gewinn_chance(modell_p, richt, markt["ja_preis"]) if richt else 0

            eintrag = {
                "id":            markt["id"],
                "frage":         markt["frage"],
                "link":          markt["link"],
                "markt_p":       round(markt["ja_preis"] * 100, 1),
                "modell_p":      round(modell_p * 100, 1),
                "edge":          round(edge * 100, 1),
                "richtung":      richt,
                "einsatz":       einsatz,
                "erw_gewinn":    gewinn,
                "gewinn_chance": chance,
                "volumen":       int(markt["volumen"]),
                "liquidit":      int(markt["liquidit"]),
                "tage":          markt["tage"],
                "endet_am":      markt["endet_am"],  # ← Ablaufdatum deutsche Zeit
                "hat_edge":      einsatz > 0,
            }
            alle.append(eintrag)
            if einsatz > 0:
                empfehlungen.append(eintrag)

        # Bald endend: sortiert nach bester Gewinnchance, enden innerhalb 30 Tage
        # Stufe 1: 0–7 Tage
        top10_bald = sorted(
            [e for e in empfehlungen if e["tage"] <= 7],
            key=lambda x: x["gewinn_chance"], reverse=True
        )[:10]
        # Stufe 2: auffüllen mit 8–30 Tagen
        if len(top10_bald) < 10:
            ids = {e["id"] for e in top10_bald}
            mehr = sorted(
                [e for e in empfehlungen if 7 < e["tage"] <= 30 and e["id"] not in ids],
                key=lambda x: x["gewinn_chance"], reverse=True
            )
            top10_bald = (top10_bald + mehr)[:10]
        # Stufe 3: auffüllen mit 31–90 Tagen falls immer noch zu wenig
        if len(top10_bald) < 10:
            ids = {e["id"] for e in top10_bald}
            mehr = sorted(
                [e for e in empfehlungen if 30 < e["tage"] <= 90 and e["id"] not in ids],
                key=lambda x: x["gewinn_chance"], reverse=True
            )
            top10_bald = (top10_bald + mehr)[:10]

        top10 = top10_bald   # Top 10 Tab = gleiche Liste

        # Deutsche Zeit = UTC+1
        jetzt_de  = datetime.utcnow() + timedelta(hours=1)
        naechstes = jetzt_de + timedelta(minutes=5)

        print(f"  → {len(empfehlungen)} Empfehlungen, Top 10 bereit")

        with lock:
            daten["alle_maerkte"]      = alle
            daten["empfehlungen"]      = empfehlungen
            daten["top10"]             = top10
            daten["top10_bald"]        = top10_bald
            daten["letztes_update"]    = jetzt_de.strftime("%H:%M Uhr")
            daten["naechstes_update"]  = naechstes.strftime("%H:%M Uhr")
            daten["status"]            = "OK"
            daten["quelle"]            = quelle
            daten["bankroll"]          = BANKROLL
            daten["gesamt_einsatz"]    = round(sum(e["einsatz"] for e in empfehlungen), 2)
            daten["gesamt_gewinn"]     = round(sum(e["erw_gewinn"] for e in empfehlungen), 2)

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
