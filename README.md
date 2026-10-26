# Audio to Text

Programma **gratuito e offline** che converte registrazioni audio (e video) di qualsiasi genere in testo.
Per ogni file crea un **file di testo `.txt`** (apribile con Blocco note, TextEdit, ecc.) con l'intera trascrizione.

- Motore: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (Whisper di OpenAI riscritto in CTranslate2). Nessun servizio a pagamento, nessuna chiave API, nessun dato inviato online dopo il primo download del modello.
- Interfaccia grafica semplice (Tkinter): scegli i file, premi "Avvia trascrizione".
- Riconosce automaticamente la lingua (italiano, inglese, spagnolo, francese, tedesco e circa 100 altre) oppure la puoi fissare tu.
- Accetta qualsiasi formato audio (mp3, wav, m4a, ogg, flac, opus, wma, aac, ...) e video (mp4, mov, mkv, avi, webm, ...): l'audio viene estratto in automatico con ffmpeg.
- Opzioni: scelta del modello (velocita'/precisione), timestamp `[hh:mm:ss]` a inizio frase, salto dei silenzi, cartella di destinazione.
- Funziona su macOS (Intel e Apple Silicon), Windows e Linux, anche senza scheda video dedicata.

## Windows: versione pronta, senza installare nulla

Per chi non ha Python: nella sezione **[Releases](https://github.com/Z0CC0/audio-converter/releases/latest)** c'e' `AudioToText-windows.zip`.

1. Scarica lo zip ed **estrai tutta la cartella** (tasto destro > Estrai tutto).
2. Doppio clic su `AudioToText.exe`.
   Se compare "PC protetto da Windows": **Ulteriori informazioni > Esegui comunque** (il programma non e' firmato digitalmente, e' open source).
3. Aggiungi i file e premi **Avvia trascrizione**.

Il pacchetto include gia' il modello `small` nella cartella `models`, quindi funziona **senza internet**. Gli altri modelli vengono scaricati al primo uso nella stessa cartella. Non servono Python ne' ffmpeg (i formati comuni sono decodificati internamente; per quelli rari basta copiare `ffmpeg.exe` accanto all'eseguibile).

L'eseguibile viene compilato automaticamente da GitHub Actions (`.github/workflows/build-windows.yml`) a ogni aggiornamento del codice, con un auto-test che carica il modello e trascrive un audio di prova prima della pubblicazione.

## Da sorgente (macOS, Linux, Windows con Python)

### Requisiti

| Componente | Note |
|---|---|
| Python 3.9 - 3.13 | Da https://www.python.org/downloads/ (su Windows spunta "Add Python to PATH"). |
| ffmpeg | Serve per i file video e per i formati audio meno comuni. macOS: `brew install ffmpeg`. Windows: https://www.gyan.dev/ffmpeg/builds/ (aggiungi `bin` al PATH). Linux: `sudo apt install ffmpeg`. |
| Tkinter | Incluso nel Python di python.org e di Windows. Homebrew: `brew install python-tk`. Debian/Ubuntu: `sudo apt install python3-tk`. |
| Connessione internet | Solo al primo avvio, per scaricare il modello scelto (vedi tabella sotto). Poi funziona offline. |

### Installazione e avvio rapido

1. Scarica il progetto: pulsante verde **Code > Download ZIP** su GitHub, poi estrai la cartella (oppure `git clone https://github.com/Z0CC0/audio-converter.git`).
2. Avvia:
   - **macOS**: doppio clic su `avvia.command` (la prima volta: tasto destro > Apri). In alternativa, dal Terminale: `bash avvia.sh`.
   - **Windows**: doppio clic su `avvia.bat`.
   - **Linux**: `bash avvia.sh`.

   Lo script crea un ambiente virtuale `.venv`, installa le dipendenze (solo la prima volta) e apre la finestra.

3. Nella finestra:
   1. **Aggiungi file...** o **Aggiungi cartella...** (cerca anche nelle sottocartelle).
   2. Scegli il **modello** e la **lingua** (`auto` = rilevamento automatico).
   3. Facoltativo: spunta **Includi timestamp**, scegli la cartella di destinazione.
   4. **Avvia trascrizione**. Al termine, **Apri cartella risultati**.

Per ogni file `registrazione.mp3` viene creato `registrazione.txt` accanto all'originale (o nella cartella scelta). Se esiste gia', il nuovo file prende un suffisso numerico: nulla viene sovrascritto.

#### Installazione manuale (senza script)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## Scelta del modello

| Modello | Download | Velocita' su CPU | Precisione |
|---|---|---|---|
| tiny | ~75 MB | velocissimo | bassa |
| base | ~140 MB | veloce | discreta |
| **small** (predefinito) | ~460 MB | buona | buona per it/en |
| medium | ~1.5 GB | lenta (2-3x small) | alta |
| large-v3 | ~3 GB | molto lenta senza GPU | massima |
| large-v3-turbo | ~1.6 GB | media | quasi come large-v3 |

Indicazione pratica: `small` per appunti vocali e riunioni in italiano/inglese; `medium` o `large-v3-turbo` per audio rumorosi, accenti forti o lingue meno comuni.
I modelli scaricati finiscono nella cartella `models/` accanto al programma e vengono riutilizzati. Un modello copiato a mano in `models/<nome>/` (con il suo `model.bin`) viene usato senza alcun download.

Su schede NVIDIA con CUDA installato il programma usa la GPU in automatico. Su Mac Apple Silicon e su CPU usa la quantizzazione int8 (veloce e leggera).

## Uso da riga di comando (facoltativo)

```bash
python transcriber.py registrazione.mp3
python transcriber.py cartella_audio/ --model medium --timestamps
python transcriber.py video.mp4 --language it --output trascrizioni/
python transcriber.py --help
```

## Formato del file di testo

```
Trascrizione di: riunione.m4a
Lingua rilevata: it (probabilita' 99%)
Durata: 00:42:10
Modello: small
------------------------------------------------------------

Buongiorno a tutti, iniziamo con il primo punto all'ordine del giorno. ...
```

Con l'opzione timestamp ogni frase e' preceduta da `[hh:mm:ss]`.

## Struttura del progetto

| File | Ruolo |
|---|---|
| `app.py` | Interfaccia grafica (Tkinter). |
| `transcriber.py` | Motore: estrazione audio con ffmpeg, trascrizione con faster-whisper, scrittura del `.txt`. Usabile anche da riga di comando. |
| `requirements.txt` | Dipendenze Python. |
| `avvia.command`, `avvia.sh`, `avvia.bat` | Script di avvio per macOS, Linux, Windows. |
| `.github/workflows/build-windows.yml` | Compila `AudioToText.exe` su GitHub Actions e pubblica lo zip nelle Releases. |

## Problemi comuni

- **"Tkinter non e' disponibile"**: vedi tabella requisiti (su Mac con Homebrew: `brew install python-tk`).
- **"ffmpeg non trovato"**: i formati comuni (mp3, wav, m4a, flac, mp4, mov...) funzionano lo stesso grazie al decoder interno; per quelli rari installa ffmpeg o copia `ffmpeg.exe` accanto al programma.
- **Primo avvio lento**: sta scaricando il modello. I successivi partono in pochi secondi.
- **Audio molto rumoroso o trascrizione incompleta**: prova un modello piu' grande, oppure disattiva "Salta i silenzi" se il parlato e' molto sommesso.
- **Errore CUDA/cuDNN su Windows con GPU NVIDIA**: il programma ricade automaticamente sulla CPU; per usare la GPU installa le librerie indicate nella documentazione di faster-whisper.

## Privacy

L'audio non lascia mai il computer. L'unico traffico di rete e' il download di un modello da Hugging Face al primo utilizzo (nessuno, se usi il pacchetto Windows con il modello incluso).

## Licenza

MIT. Whisper e faster-whisper sono distribuiti con licenza MIT dai rispettivi autori.
