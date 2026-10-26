#!/bin/bash
# Avvio con doppio clic su macOS (la prima volta: tasto destro > Apri).
# Crea l'ambiente virtuale, installa le dipendenze e apre la finestra.
cd "$(dirname "$0")" || exit 1
exec bash ./avvia.sh
