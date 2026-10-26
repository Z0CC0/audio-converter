@echo off
REM Avvio su Windows: crea l'ambiente virtuale (una volta sola),
REM installa le dipendenze e apre l'interfaccia grafica.
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py -3) || (set PY=python)

if not exist .venv (
    echo Creo l'ambiente virtuale...
    %PY% -m venv .venv || (echo Python 3 non trovato. Installalo da https://www.python.org/downloads/ ^(spunta "Add to PATH"^) & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -c "import faster_whisper" >nul 2>nul || (
    echo Installo le dipendenze ^(solo la prima volta^)...
    python -m pip install --upgrade pip >nul
    python -m pip install -r requirements.txt || (pause & exit /b 1)
)
where ffmpeg >nul 2>nul || echo Nota: ffmpeg non trovato ^(serve per i file video^). Scaricalo da https://www.gyan.dev/ffmpeg/builds/ e aggiungi la cartella bin al PATH.
python app.py
if errorlevel 1 pause
