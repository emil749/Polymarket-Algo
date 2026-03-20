#!/bin/bash
# ═══════════════════════════════════════════════════
#   Polymarket Live Dashboard — Start Script
#   Für Mac / Linux
# ═══════════════════════════════════════════════════

echo ""
echo "  🎯 Polymarket Live Dashboard"
echo "  ─────────────────────────────"

# Prüfen ob Python vorhanden
if ! command -v python3 &> /dev/null; then
    echo "  ✗ Python3 nicht gefunden. Bitte installieren:"
    echo "    https://www.python.org/downloads/"
    exit 1
fi

# Abhängigkeiten installieren
echo "  📦 Installiere Abhängigkeiten..."
pip3 install flask requests numpy pandas scikit-learn xgboost --quiet

echo "  ✓ Alles bereit!"
echo ""
echo "  🌐 Dashboard: http://localhost:5000"
echo "  ⏹  Stoppen:   Ctrl+C"
echo ""

# Server starten
python3 server.py
