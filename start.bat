@echo off
echo.
echo   Polymarket Live Dashboard
echo   ─────────────────────────────
echo.
echo   Installiere Abhaengigkeiten...
pip install flask requests numpy pandas scikit-learn xgboost --quiet
echo.
echo   Dashboard: http://localhost:5000
echo   Stoppen:   Strg+C
echo.
python server.py
pause
