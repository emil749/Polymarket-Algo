"""
Polymarket Algorithmus — Erweiterter Modus
• Bis zu 500 Märkte via Pagination
• Automatische Übersetzung (Deutsch)
• Kategorien (Krypto, Politik, Sport, Wirtschaft, Tech)
• Verbessertes Modell mit Volumen-Gewichtung
"""

from flask import Flask, jsonify, send_from_directory, request
import requests, numpy as np, os, threading, time, json
from datetime import datetime, timedelta

app = Flask(__name__, static_folder=".")

BANKROLL  = 200.0
MIN_EDGE  = 0.02
KELLY     = 0.25

daten = {
    "empfehlungen":    [],
    "top10_bald":      [],
    "alle_maerkte":    [],
    "letztes_update":  "—",
    "naechstes_update":"—",
    "status":          "Startet...",
    "quelle":          "—",
    "bankroll":        BANKROLL,
    "gesamt_einsatz":  0,
    "gesamt_gewinn":   0,
    "markt_anzahl":    0,
}
lock = threading.Lock()

# Übersetzungs-Cache (damit jede Frage nur einmal übersetzt wird)
uebersetzungs_cache = {}


# ─────────────────────────────────────────────────────────
# ÜBERSETZUNG
# ─────────────────────────────────────────────────────────

def uebersetzen(text):
    """Übersetzt englischen Text auf Deutsch via Google Translate."""
    if not text or len(text) < 5:
        return text
    if text in uebersetzungs_cache:
        return uebersetzungs_cache[text]
    try:
        from deep_translator import GoogleTranslator
        ergebnis = GoogleTranslator(source="auto", target="de").translate(text)
        uebersetzungs_cache[text] = ergebnis or text
        return uebersetzungs_cache[text]
    except Exception:
        uebersetzungs_cache[text] = text
        return text


# ─────────────────────────────────────────────────────────
# KATEGORIE-ERKENNUNG
# ─────────────────────────────────────────────────────────

KATEGORIEN = {
    "₿ Krypto":      ["bitcoin","ethereum","crypto","btc","eth","blockchain",
                       "token","defi","nft","solana","doge","coinbase","binance",
                       "altcoin","stablecoin","usdc","usdt","web3"],
    "🗳️ Politik":    ["trump","biden","election","congress","senate","president",
                       "democrat","republican","vote","white house","ukraine",
                       "russia","nato","war","military","putin","zelensky",
                       "macron","merz","scholz","germany","eu","europe","china",
                       "xi jinping","parliament","government","minister","policy"],
    "⚽ Sport":       ["fifa","world cup","nba","nfl","soccer","football",
                       "basketball","olympics","champion","league","sport",
                       "tennis","golf","formula","f1","boxing","ufc","hockey",
                       "baseball","cricket","rugby","esport","wimbledon"],
    "📈 Wirtschaft":  ["fed","inflation","gdp","stock","s&p","economy","rate",
                       "recession","market","dollar","euro","interest","bank",
                       "treasury","oil","gold","nasdaq","dow","earnings",
                       "ipo","trade","tariff","imf","debt","budget"],
    "🤖 Tech":        ["ai","gpt","openai","apple","tesla","spacex","google",
                       "microsoft","amazon","meta","nvidia","tech","software",
                       "robot","autonomous","chip","semiconductor","iphone",
                       "android","startup","anthropic","gemini","llm"],
}

def kategorie_erkennen(frage):
    f = frage.lower()
    for name, keywords in KATEGORIEN.items():
        if any(k in f for k in keywords):
            return name
    return "🌍 Sonstiges"


# ─────────────────────────────────────────────────────────
# MÄRKTE LADEN (mit Pagination — bis zu 500)
# ─────────────────────────────────────────────────────────

def maerkte_laden():
    alle_maerkte = []
    offset = 0
    limit  = 100
    max_maerkte = 500

    try:
        while len(alle_maerkte) < max_maerkte:
            r = requests.get(
                "https://gamma-api.polymarket.com/markets",
                params={
                    "active":  "true",
                    "closed":  "false",
                    "limit":   limit,
                    "offset":  offset,
                },
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            r.raise_for_status()
            data = r.json()

            if isinstance(data, dict):
                data = data.get("data", data.get("markets", []))
            if not isinstance(data, list) or len(data) == 0:
                break

            alle_maerkte.extend(data)
            if len(data) < limit:
                break   # Keine weiteren Seiten
            offset += limit

        if len(alle_maerkte) > 0:
            print(f"  ✓ {len(alle_maerkte)} Märkte geladen")
            return alle_maerkte, "🟢 Live"

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
        ("Will OpenAI release GPT-5 by June 2026?",   0.67, "will-openai-release-gpt5"),
        ("Will S&P 500 hit 6500 before July 2026?",   0.55, "will-sp500-hit-6500"),
        ("Will Ethereum reach $5000 in 2026?",         0.33, "will-ethereum-reach-5000"),
        ("Will Germany win the 2026 World Cup?",       0.08, "will-germany-win-worldcup"),
        ("Will inflation drop below 2% in the EU?",   0.44, "will-inflation-drop-eu"),
        ("Will NATO expand membership in 2026?",       0.21, "will-nato-expand-2026"),
        ("Will Trump win the 2026 midterms?",          0.48, "will-trump-win-midterms"),
        ("Will Apple release AR glasses in 2026?",    0.35, "will-apple-ar-glasses"),
    ]
    result = []
    for i, (frage, p, slug) in enumerate(themen):
        rng = np.random.RandomState(i * 7)
        result.append({
            "id":            f"demo_{i}",
            "question":      frage,
            "slug":          slug,
            "outcomePrices": json.dumps([str(p), str(round(1-p,2))]),
            "volume":        round(float(rng.uniform(5000, 100000))),
            "liquidity":     round(float(rng.uniform(3000, 50000))),
            "endDate":       (datetime.now() + timedelta(days=int(rng.randint(3, 60)))).isoformat(),
        })
    return result


# ─────────────────────────────────────────────────────────
# MARKT AUSWERTEN
# ─────────────────────────────────────────────────────────

def preis_parsen(roh):
    if roh is None:
        return None
    try:
        if isinstance(roh, list):
            return [float(x) for x in roh]
        if isinstance(roh, str):
            return [float(x) for x in json.loads(roh)]
    except Exception:
        pass
    return None


def polymarket_link(m):
    slug = m.get("slug") or m.get("marketSlug", "")
    if slug:
        return f"https://polymarket.com/event/{slug}"
    mid = m.get("id", "")
    if mid and not str(mid).startswith("demo"):
        return f"https://polymarket.com/market/{mid}"
    return "https://polymarket.com/markets"


def markt_auswerten(m):
    try:
        preise = None
        for feld in ["outcomePrices", "prices", "lastTradePrice"]:
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
            dt_de    = dt.replace(tzinfo=None) + timedelta(hours=1)
            jetzt_de = datetime.utcnow() + timedelta(hours=1)
            tage_raw = (dt_de - jetzt_de).days
            if tage_raw < 0:
                return None   # Bereits abgelaufen
            tage     = tage_raw
            endet_am = dt_de.strftime("%-d.%-m.%Y um %H:%M")
        except Exception:
            tage     = 30
            endet_am = "Unbekannt"

        frage = str(m.get("question") or m.get("title") or "?")

        return {
            "id":        str(m.get("id", "")),
            "frage":     frage,
            "ja_preis":  ja_preis,
            "volumen":   vol,
            "liquidit":  liq,
            "tage":      tage,
            "endet_am":  endet_am,
            "liq_score": min(liq / 10000, 1.0),
            "vol_score": min(vol / 50000, 1.0),   # ← Volumen-Score
            "link":      polymarket_link(m),
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────────────
# VERBESSERTES MODELL (mit Volumen-Gewichtung)
# ─────────────────────────────────────────────────────────

def modell_wahrscheinlichkeit(markt):
    """
    Verbessertes Modell:
    - Voluminöse Märkte (>$50k) haben effizientere Preise → weniger Korrektur
    - Illiquide Märkte (<$5k) haben mehr Rauschen → stärkere Korrektur
    - Kurze Laufzeit (<7 Tage) → Unsicherheit erhöht
    """
    p   = markt["ja_preis"]
    liq = markt["liq_score"]
    vol = markt["vol_score"]

    # Volumen-Vertrauen: je mehr Volumen, desto mehr vertrauen wir dem Marktpreis
    vertrauen = (liq * 0.5 + vol * 0.5)

    # Korrektur — geringer bei hohem Volumen
    korrektur_faktor = 1.0 - vertrauen * 0.6   # bei $100k Volumen: nur 40% Korrektur

    if   p < 0.08: anp = p + (p * 0.35 * korrektur_faktor)          # zu billig
    elif p < 0.18: anp = p + (p * 0.18 * korrektur_faktor)
    elif p < 0.28: anp = p + (p * 0.07 * korrektur_faktor)
    elif p > 0.92: anp = p + (1-p) * 0.15 * korrektur_faktor         # zu teuer
    elif p > 0.82: anp = p + (1-p) * 0.08 * korrektur_faktor
    elif p > 0.72: anp = p + (1-p) * 0.04 * korrektur_faktor
    else:          anp = p

    # Mehr Rauschen bei niedrigem Volumen/Liquidität
    rauschen = np.random.normal(0, 0.025 * (1 - vertrauen))
    return float(np.clip(anp + rauschen, 0.02, 0.98))


def kelly_einsatz(modell_p, markt_p, vol_score):
    edge     = modell_p - markt_p
    richtung = "JA" if modell_p >= markt_p else "NEIN"
    p_wette  = modell_p if richtung == "JA" else (1 - modell_p)

    if abs(edge) >= MIN_EDGE:
        # Klarer Vorteil → voller Kelly
        if richtung == "JA":
            b, p, q = (1 - markt_p) / (markt_p + 1e-9), modell_p, 1 - modell_p
        else:
            b, p, q = markt_p / (1 - markt_p + 1e-9), 1 - modell_p, modell_p
        k       = max(0, (b * p - q) / (b + 1e-9))
        vol_fak = 0.5 + vol_score * 0.5
        einsatz = min(KELLY * k * BANKROLL * vol_fak, 0.06 * BANKROLL)
    else:
        # Kein klarer Vorteil → kleiner Basis-Einsatz nach Gewinnchance
        # Je höher die Gewinnchance, desto mehr (max 3% des Kapitals)
        if   p_wette >= 0.75: einsatz = BANKROLL * 0.030
        elif p_wette >= 0.65: einsatz = BANKROLL * 0.020
        elif p_wette >= 0.55: einsatz = BANKROLL * 0.010
        else:                 einsatz = BANKROLL * 0.005

    return round(max(1.0, einsatz), 2), richtung


def gewinn_chance(modell_p, richtung):
    if richtung == "JA":
        return round(modell_p * 100, 1)
    return round((1 - modell_p) * 100, 1)


# ─────────────────────────────────────────────────────────
# PIPELINE
# ─────────────────────────────────────────────────────────

def pipeline():
    while True:
        print(f"\n[{datetime.utcnow() + timedelta(hours=1):%H:%M:%S}] Update...")
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
            einsatz, richt = kelly_einsatz(modell_p, markt["ja_preis"], markt["vol_score"])
            gewinn         = round(einsatz * abs(edge) / (markt["ja_preis"] + 1e-9), 2) if einsatz > 0 else 0

            if richt is None:
                richt = "JA" if modell_p >= markt["ja_preis"] else "NEIN"

            chance   = gewinn_chance(modell_p, richt)
            kat      = kategorie_erkennen(markt["frage"])

            # Übersetzung (aus Cache oder neu)
            frage_de = uebersetzen(markt["frage"])

            eintrag = {
                "id":            markt["id"],
                "frage":         frage_de,            # ← Deutsch
                "frage_en":      markt["frage"],       # ← Original (Englisch)
                "link":          markt["link"],
                "kategorie":     kat,                  # ← Kategorie
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
                "endet_am":      markt["endet_am"],
                "hat_edge":      abs(edge * 100) >= MIN_EDGE * 100,
            }
            alle.append(eintrag)
            if einsatz > 0:
                empfehlungen.append(eintrag)

        # Top 10 bald endend — aus ALLEN Märkten, beste Gewinnchance
        def top_n(pool, max_tage, n=10):
            return sorted(
                [e for e in pool if e["tage"] <= max_tage],
                key=lambda x: x["gewinn_chance"], reverse=True
            )[:n]

        top10_bald = top_n(alle, 7)
        for grenze in [30, 90, 9999]:
            if len(top10_bald) >= 10:
                break
            ids = {e["id"] for e in top10_bald}
            mehr = top_n([e for e in alle if e["id"] not in ids], grenze)
            top10_bald = (top10_bald + mehr)[:10]

        jetzt_de  = datetime.utcnow() + timedelta(hours=1)
        naechstes = jetzt_de + timedelta(minutes=5)

        print(f"  → {len(alle)} Märkte | {len(empfehlungen)} mit Edge | Top 10 bereit")

        with lock:
            daten["alle_maerkte"]      = alle
            daten["empfehlungen"]      = empfehlungen
            daten["top10_bald"]        = top10_bald
            daten["letztes_update"]    = jetzt_de.strftime("%H:%M Uhr")
            daten["naechstes_update"]  = naechstes.strftime("%H:%M Uhr")
            daten["status"]            = "OK"
            daten["quelle"]            = quelle
            daten["bankroll"]          = BANKROLL
            daten["markt_anzahl"]      = len(alle)
            daten["gesamt_einsatz"]    = round(sum(e["einsatz"] for e in empfehlungen), 2)
            daten["gesamt_gewinn"]     = round(sum(e["erw_gewinn"] for e in empfehlungen), 2)

        time.sleep(300)


# ─────────────────────────────────────────────────────────
# ROUTEN
# ─────────────────────────────────────────────────────────

@app.route("/")
def startseite():
    return send_from_directory(".", "index.html")

@app.route("/api/daten")
def api_daten():
    with lock:
        return jsonify(dict(daten))


# ─────────────────────────────────────────────────────────
# START
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 50)
    print("  POLYMARKET ALGORITHMUS (Erweiterter Modus)")
    print(f"  http://localhost:{port}")
    print(f"  Kapital: ${BANKROLL}")
    print("=" * 50)

    t = threading.Thread(target=pipeline, daemon=True)
    t.start()
    time.sleep(4)
    app.run(host="0.0.0.0", port=port, debug=False)
