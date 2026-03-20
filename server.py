"""
========================================================
  Polymarket Live Server
  Starten mit: python server.py
  Dashboard:   http://localhost:5000
========================================================
"""

from flask import Flask, jsonify, send_from_directory
import requests
import numpy as np
import threading
import time
import os
from datetime import datetime, timedelta

app = Flask(__name__, static_folder=".")

# ─────────────────────────────────────────────────────────
# KONFIGURATION
# ─────────────────────────────────────────────────────────
CONFIG = {
    "update_interval": 5 * 60,   # 5 Minuten in Sekunden
    "bankroll":        1000.0,
    "min_edge":        0.05,
    "kelly_fraction":  0.25,
    "max_bet_pct":     0.05,
    "max_markets":     50,
    "min_liquidity":   500,
}

GAMMA_API = "https://gamma-api.polymarket.com"

# ─────────────────────────────────────────────────────────
# GLOBALER STATE (wird vom Background-Thread befüllt)
# ─────────────────────────────────────────────────────────
state = {
    "markets":       [],
    "recommendations": [],
    "last_update":   None,
    "next_update":   None,
    "status":        "Initialisierung...",
    "total_risk":    0.0,
    "total_profit":  0.0,
    "source":        "demo",   # "live" oder "demo"
}
state_lock = threading.Lock()


# ─────────────────────────────────────────────────────────
# DATENABRUF
# ─────────────────────────────────────────────────────────

def fetch_markets():
    """Versucht echte Polymarket-Daten zu laden, fällt auf Demo zurück."""
    try:
        r = requests.get(
            f"{GAMMA_API}/markets",
            params={"active": True, "closed": False, "limit": CONFIG["max_markets"]},
            timeout=8
        )
        r.raise_for_status()
        data = r.json()
        print(f"  ✓ {len(data)} Märkte von Polymarket API geladen")
        return data, "live"
    except Exception as e:
        print(f"  ✗ API nicht erreichbar ({type(e).__name__}), nutze Demo-Daten")
        return generate_demo_markets(), "demo"


def generate_demo_markets():
    np.random.seed(int(time.time()) % 1000)
    topics = [
        "Will the Fed cut rates in Q2 2026?",
        "Will Bitcoin reach $100k by June 2026?",
        "Will Germany form a stable coalition by July?",
        "Will AI surpass human performance in new coding benchmark?",
        "Will Elon Musk sell Tesla shares this quarter?",
        "Will inflation drop below 2% in the EU?",
        "Will the next iPhone include a foldable display?",
        "Will there be a major bank failure in 2026?",
        "Will autonomous vehicles launch in 10 cities by 2026?",
        "Will the S&P500 hit 7000 by December 2026?",
        "Will NATO expand membership in 2026?",
        "Will OpenAI release GPT-5 before June 2026?",
        "Will there be a US recession in 2026?",
        "Will oil prices exceed $100/barrel in 2026?",
        "Will China's GDP growth exceed 5% in 2026?",
    ]
    markets = []
    for i, q in enumerate(topics):
        rng = np.random.RandomState(i * 17 + int(time.time()) % 100)
        p = round(float(rng.uniform(0.12, 0.88)), 2)
        markets.append({
            "id": f"demo_{i}",
            "question": q,
            "outcomePrices": f"[{p}, {round(1-p, 2)}]",
            "volume":    round(float(rng.uniform(500, 60000))),
            "liquidity": round(float(rng.uniform(1000, 25000))),
            "endDate":   (datetime.now() + timedelta(days=int(rng.randint(7, 180)))).isoformat(),
        })
    return markets


# ─────────────────────────────────────────────────────────
# FEATURE ENGINEERING + MODELL
# ─────────────────────────────────────────────────────────

def parse_market(m):
    try:
        prices_raw = m.get("outcomePrices", "[0.5,0.5]")
        if isinstance(prices_raw, str):
            prices = [float(x.strip()) for x in prices_raw.strip("[]").split(",")]
        else:
            prices = list(prices_raw)
        p = float(prices[0])
        if p < 0.02 or p > 0.98:
            return None
        vol = float(m.get("volume", 0) or 0)
        liq = float(m.get("liquidity", 0) or 0)
        if liq < CONFIG["min_liquidity"] and vol < CONFIG["min_liquidity"]:
            return None
        end = m.get("endDate", "")
        try:
            dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            days = max(0, (dt.replace(tzinfo=None) - datetime.now()).days)
        except:
            days = 30
        return {
            "id":       m.get("id", ""),
            "question": m.get("question", "Unknown"),
            "yes_price": p,
            "volume":   vol,
            "liquidity": liq,
            "days_left": days,
            "liquidity_score": min(liq / 10000, 1.0),
            "volume_score":    min(vol / 50000, 1.0),
            "entropy": -(p * np.log(p + 1e-9) + (1-p) * np.log(1-p + 1e-9)),
        }
    except:
        return None


def predict_probability(market):
    """Heuristisches Modell — ersetze dies mit deinem trainierten XGBoost."""
    p   = market["yes_price"]
    liq = market["liquidity_score"]

    if   p < 0.15: adj = p * 0.76
    elif p < 0.25: adj = p * 0.88
    elif p > 0.85: adj = p + (1 - p) * 0.10
    elif p > 0.75: adj = p + (1 - p) * 0.05
    else:          adj = p

    noise = np.random.normal(0, 0.05 * (1 - liq))
    return float(np.clip(adj + noise, 0.02, 0.98))


def kelly_bet(model_p, market_p, bankroll):
    edge = model_p - market_p
    if abs(edge) < CONFIG["min_edge"]:
        return 0.0, None
    if edge > 0:
        b = (1 - market_p) / (market_p + 1e-9)
        p, q = model_p, 1 - model_p
        direction = "YES"
    else:
        b = market_p / (1 - market_p + 1e-9)
        p, q = 1 - model_p, model_p
        direction = "NO"
    k_full = (b * p - q) / (b + 1e-9)
    bet = min(CONFIG["kelly_fraction"] * k_full * bankroll, CONFIG["max_bet_pct"] * bankroll)
    return round(max(0.0, bet), 2), direction


# ─────────────────────────────────────────────────────────
# HAUPT-UPDATE-FUNKTION
# ─────────────────────────────────────────────────────────

def run_pipeline():
    """Läuft im Hintergrund, aktualisiert state alle 5 Minuten."""
    while True:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Pipeline-Update startet...")

        with state_lock:
            state["status"] = "Aktualisierung läuft..."

        raw, source = fetch_markets()
        markets_out  = []
        recs_out     = []
        bankroll     = CONFIG["bankroll"]

        for m in raw:
            parsed = parse_market(m)
            if not parsed:
                continue
            model_p = predict_probability(parsed)
            edge    = model_p - parsed["yes_price"]
            bet, direction = kelly_bet(model_p, parsed["yes_price"], bankroll)
            exp_profit = bet * abs(edge) / (parsed["yes_price"] + 1e-9) if bet > 0 else 0

            entry = {
                "id":          parsed["id"],
                "question":    parsed["question"],
                "market_p":    round(parsed["yes_price"], 3),
                "model_p":     round(model_p, 3),
                "edge":        round(edge, 3),
                "volume":      parsed["volume"],
                "liquidity":   parsed["liquidity"],
                "days_left":   parsed["days_left"],
                "bet":         bet,
                "direction":   direction,
                "exp_profit":  round(exp_profit, 2),
                "has_edge":    bet > 0,
            }
            markets_out.append(entry)
            if bet > 0:
                recs_out.append(entry)

        recs_out.sort(key=lambda x: abs(x["edge"]), reverse=True)
        total_risk   = round(sum(r["bet"] for r in recs_out), 2)
        total_profit = round(sum(r["exp_profit"] for r in recs_out), 2)
        now          = datetime.now()
        next_up      = now + timedelta(seconds=CONFIG["update_interval"])

        with state_lock:
            state["markets"]         = markets_out
            state["recommendations"] = recs_out
            state["last_update"]     = now.strftime("%H:%M:%S")
            state["next_update"]     = next_up.strftime("%H:%M:%S")
            state["status"]          = "OK"
            state["total_risk"]      = total_risk
            state["total_profit"]    = total_profit
            state["source"]          = source

        print(f"  ✓ {len(markets_out)} Märkte | {len(recs_out)} Trades | Risiko: ${total_risk}")
        print(f"  ⏳ Nächstes Update: {next_up.strftime('%H:%M:%S')}")
        time.sleep(CONFIG["update_interval"])


# ─────────────────────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")

@app.route("/api/state")
def api_state():
    with state_lock:
        return jsonify(dict(state))

@app.route("/api/config")
def api_config():
    return jsonify(CONFIG)


# ─────────────────────────────────────────────────────────
# START
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  POLYMARKET LIVE SERVER")
    print(f"  Dashboard: http://localhost:5000")
    print(f"  Update-Intervall: alle 5 Minuten")
    print("=" * 55)

    # Background-Thread für Pipeline
    t = threading.Thread(target=run_pipeline, daemon=True)
    t.start()

    # Kurz warten damit erster Update durch ist
    time.sleep(2)

    port = int(os.environ.get("PORT", 5000))
app.run(host="0.0.0.0", port=port, debug=False)
