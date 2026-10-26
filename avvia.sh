#!/bin/bash
# Avvio su macOS / Linux: crea l'ambiente virtuale (una volta sola),
# installa le dipendenze e apre l'interfaccia grafica.
set -e
cd "$(dirname "$0")"

PY=""
for cand in python3.12 python3.11 python3.13 python3; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
    echo "Python 3 non trovato. Installalo da https://www.python.org/downloads/"; exit 1
fi

if [ ! -d .venv ]; then
    echo "Creo l'ambiente virtuale con $PY..."
    "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
if ! python -c "import faster_whisper" >/dev/null 2>&1; then
    echo "Installo le dipendenze (solo la prima volta)..."
    pip install --upgrade pip >/dev/null
    pip install -r requirements.txt
fi
if ! python -c "import tkinter" >/dev/null 2>&1; then
    echo "Tkinter non disponibile per questo Python."
    echo "  macOS (Homebrew):  brew install python-tk"
    echo "  Debian/Ubuntu:     sudo apt install python3-tk"
    exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/ffmpeg ]; then
    echo "Nota: ffmpeg non trovato (serve per i file video). macOS: brew install ffmpeg - Linux: sudo apt install ffmpeg"
fi
exec python app.py
