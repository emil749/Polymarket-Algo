# 🎯 Polymarket Live Dashboard

Vollautomatisches Prediction-Dashboard mit Live-Daten von Polymarket.

---

## 📁 Dateien

| Datei | Beschreibung |
|---|---|
| `server.py` | Flask-Backend + Prediction-Pipeline |
| `dashboard.html` | Live-Dashboard (öffnet sich im Browser) |
| `requirements.txt` | Python-Abhängigkeiten |
| `start.sh` | Startskript für Mac/Linux |
| `start.bat` | Startskript für Windows |

---

## 🚀 Schnellstart

### Mac / Linux
```bash
chmod +x start.sh
./start.sh
```

### Windows
Doppelklick auf `start.bat`

### Manuell
```bash
pip install flask requests numpy pandas scikit-learn xgboost
python server.py
```

Dann Browser öffnen: **http://localhost:5000**

---

## ⚙️ Wie es funktioniert

```
Browser (dashboard.html)
      ↕ alle 5 Minuten
Flask Server (server.py :5000)
      ↕ alle 5 Minuten
Polymarket Gamma API
  → Falls API nicht erreichbar: Demo-Daten
```

1. **Server startet** → Background-Thread läuft sofort
2. **Alle 5 Minuten** holt der Server neue Märkte von Polymarket
3. **Pipeline berechnet** Features, Modell-Wahrscheinlichkeit, Kelly-Bets
4. **Dashboard zeigt** Live-Ergebnisse mit Countdown-Bar

---

## 🎛️ Dashboard-Funktionen

| Feature | Beschreibung |
|---|---|
| **Countdown-Bar** | Zeigt wann nächstes Update kommt |
| **Bankroll-Slider** | Ändert Einsatzgröße live |
| **Min-Edge-Slider** | Ab welcher Abweichung gehandelt wird |
| **Kelly %-Slider** | Konservativität des Modells (25% = sicher) |
| **Tab: Top Trades** | Nur Märkte mit positivem Edge |
| **Tab: Alle Märkte** | Komplette Marktübersicht |
| **Kelly-Rechner** | Berechne Einsatz für beliebige Wahrscheinlichkeiten |

---

## 🔧 Konfiguration anpassen

In `server.py` oben im `CONFIG`-Dict:

```python
CONFIG = {
    "update_interval": 5 * 60,   # ← Hier Sekunden ändern (z.B. 60 = 1 Minute)
    "bankroll":        1000.0,   # ← Startkapital
    "min_edge":        0.05,     # ← 5% Mindest-Edge
    "kelly_fraction":  0.25,     # ← 25% Fractional Kelly
    "max_bet_pct":     0.05,     # ← Max 5% pro Trade
    "max_markets":     50,       # ← Wie viele Märkte laden
}
```

---

## 📈 Eigenes Modell einbauen

In `server.py` die Funktion `predict_probability()` ersetzen:

```python
# Aktuell: Heuristik
def predict_probability(market):
    ...

# Ersetzen mit trainiertem XGBoost:
import joblib
model = joblib.load('mein_modell.pkl')

def predict_probability(market):
    features = [[
        market['yes_price'],
        market['liquidity_score'],
        market['volume_score'],
        market['days_left'],
        market['entropy'],
    ]]
    return float(model.predict_proba(features)[0][1])
```

---

## ⚠️ Wichtige Hinweise

- **Kein Finanzberatung** — starte immer mit Paper-Trading
- **Demo-Modus** wenn Polymarket API nicht erreichbar
- **Das Modell ist eine Heuristik** — für echten Edge brauchst du historische Daten
- **Kelly Criterion** kann bei falschem Modell zu Verlusten führen
- Starte mit kleinem Bankroll und erhöhe erst wenn Brier Score < 0.18

---

## 🔗 Ressourcen

- [Polymarket API Docs](https://docs.polymarket.com)
- [The Graph — Historische Daten](https://thegraph.com)
- [Kelly Criterion Erklärung](https://en.wikipedia.org/wiki/Kelly_criterion)
