#!/usr/bin/env python3
"""
transcriber.py - Motore di trascrizione audio/video -> testo (.txt)

Gratuito e offline: usa faster-whisper (Whisper di OpenAI via CTranslate2).
Il modello viene scaricato una sola volta al primo utilizzo (da Hugging Face),
poi tutto funziona senza connessione.

Uso da riga di comando (facoltativo, la GUI e' in app.py):

    python3 transcriber.py registrazione.mp3
    python3 transcriber.py cartella_audio/ --model medium --timestamps
    python3 transcriber.py video.mp4 --language it --output trascrizioni/

Per ogni file viene creato "<nome file>.txt" con il testo completo.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

MODELS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]
DEFAULT_MODEL = "small"

# Descrizione sintetica mostrata nella GUI / nel README.
MODEL_INFO = {
    "tiny": "~75 MB, velocissimo, precisione bassa",
    "base": "~140 MB, veloce, precisione discreta",
    "small": "~460 MB, buon compromesso (consigliato)",
    "medium": "~1.5 GB, precisione alta, lento su CPU",
    "large-v3": "~3 GB, massima precisione, molto lento senza GPU",
    "large-v3-turbo": "~1.6 GB, quasi come large-v3 ma molto piu' veloce",
}

# Lingue selezionabili ("auto" = rilevamento automatico di Whisper).
LANGUAGES = {
    "auto": None,
    "Italiano": "it",
    "English": "en",
    "Espanol": "es",
    "Francais": "fr",
    "Deutsch": "de",
    "Portugues": "pt",
    "Nederlands": "nl",
    "Polski": "pl",
    "Russkij": "ru",
    "Turkce": "tr",
    "Arabi": "ar",
    "Zhongwen": "zh",
    "Nihongo": "ja",
    "Hangugeo": "ko",
    "Hindi": "hi",
}

# Estensioni accettate: qualsiasi cosa che ffmpeg sappia decodificare.
AUDIO_EXTS = {
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma",
    ".aiff", ".aif", ".amr", ".3ga", ".caf", ".mka", ".ac3", ".ape", ".wv",
}
VIDEO_EXTS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg",
    ".mpeg", ".3gp", ".ts", ".mts", ".m2ts", ".ogv",
}
MEDIA_EXTS = AUDIO_EXTS | VIDEO_EXTS


def app_dir() -> Path:
    """Cartella del programma: quella dell'eseguibile se impacchettato con
    PyInstaller, altrimenti quella di questo file."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def models_dir() -> Path:
    """Cartella 'models' accanto al programma: contiene i modelli inclusi nel
    pacchetto (es. models/small) e quelli scaricati in seguito."""
    return app_dir() / "models"


class TranscriptionCancelled(Exception):
    """Sollevata quando l'utente annulla l'elaborazione."""


@dataclass
class TranscriptionResult:
    source: Path
    output: Path
    language: str
    language_probability: float
    duration: float
    text: str


# ---------------------------------------------------------------------------
# Utilita'
# ---------------------------------------------------------------------------

def find_ffmpeg() -> Optional[str]:
    """Restituisce il percorso di ffmpeg, cercando anche nei punti tipici
    di macOS (Homebrew) e Windows, oppure None se non e' installato."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    exe_name = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    candidates = [
        str(app_dir() / exe_name),
        str(app_dir() / "ffmpeg" / exe_name),
        str(app_dir() / "ffmpeg" / "bin" / exe_name),
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
        str(Path.home() / "ffmpeg" / "bin" / "ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


def is_media_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in MEDIA_EXTS


def collect_media_files(paths: Iterable[os.PathLike | str]) -> list[Path]:
    """Espande file e cartelle in una lista ordinata di file multimediali."""
    result: list[Path] = []
    seen: set[Path] = set()
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            candidates = sorted(q for q in p.rglob("*") if is_media_file(q))
        elif is_media_file(p):
            candidates = [p]
        else:
            continue
        for c in candidates:
            r = c.resolve()
            if r not in seen:
                seen.add(r)
                result.append(c)
    return result


def format_timestamp(seconds: float) -> str:
    """12.5 -> '00:00:12'."""
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def output_path_for(source: Path, output_dir: Optional[Path]) -> Path:
    """Percorso del .txt: accanto al file sorgente, oppure nella cartella
    scelta. Se esiste gia', aggiunge un suffisso numerico senza sovrascrivere."""
    base_dir = output_dir if output_dir else source.parent
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = base_dir / f"{source.stem}.txt"
    i = 2
    while candidate.exists():
        candidate = base_dir / f"{source.stem} ({i}).txt"
        i += 1
    return candidate


def extract_audio(source: Path, ffmpeg: str, cancel: Optional[threading.Event] = None) -> Path:
    """Converte qualsiasi audio/video in WAV mono 16 kHz (formato nativo di
    Whisper) in un file temporaneo. Restituisce il percorso del WAV."""
    tmp = tempfile.NamedTemporaryFile(prefix="a2t_", suffix=".wav", delete=False)
    tmp.close()
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-vn",                 # scarta il video
        "-ac", "1",            # mono
        "-ar", "16000",        # 16 kHz
        "-c:a", "pcm_s16le",
        tmp.name,
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # niente console su Windows
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, creationflags=creationflags)
    while True:
        try:
            _, err = proc.communicate(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.wait()
                Path(tmp.name).unlink(missing_ok=True)
                raise TranscriptionCancelled()
    if proc.returncode != 0:
        Path(tmp.name).unlink(missing_ok=True)
        msg = err.decode(errors="replace").strip() if err else "errore sconosciuto"
        # Solo la prima riga, senza il prefisso "[in#0 @ 0x...]": il resto e' rumore.
        import re
        msg = re.sub(r"^\[[^\]]*\]\s*", "", msg.splitlines()[0]) if msg else "errore sconosciuto"
        raise RuntimeError(f"ffmpeg non riesce a leggere '{source.name}': {msg}")
    return Path(tmp.name)


SAMPLE_RATE = 16000


def read_wav_16k_mono(path: Path):
    """Legge un WAV PCM 16 bit mono a 16 kHz (quello prodotto da extract_audio)
    e restituisce un array float32 normalizzato in [-1, 1]."""
    import wave
    import numpy as np
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getframerate() != SAMPLE_RATE or w.getsampwidth() != 2:
            raise ValueError("WAV non nel formato atteso (mono, 16 kHz, 16 bit)")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0


def decode_with_av(path: Path):
    """Decodifica qualsiasi audio/video con PyAV (incluso nell'eseguibile
    Windows, nessun ffmpeg esterno richiesto) e restituisce float32 mono 16 kHz.
    Usa solo l'API stabile di PyAV, cosi' non dipende dalla versione."""
    import av
    import numpy as np
    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    chunks = []
    with av.open(str(path), mode="r") as container:
        streams = [st for st in container.streams if st.type == "audio"]
        if not streams:
            raise RuntimeError(f"'{path.name}' non contiene una traccia audio")
        stream = streams[0]
        try:
            stream.thread_type = "AUTO"
        except Exception:
            pass
        for frame in container.decode(stream):
            frame.pts = None  # evita errori sui timestamp non monotoni
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):  # svuota il buffer
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype="float32")
    return np.concatenate(chunks).astype("float32") / 32768.0


def load_audio(source: Path, cancel: Optional[threading.Event] = None):
    """Carica un file audio/video come array float32 mono 16 kHz.
    Con ffmpeg disponibile converte tramite ffmpeg (massima compatibilita'),
    altrimenti decodifica con PyAV."""
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        wav = extract_audio(source, ffmpeg, cancel)
        try:
            return read_wav_16k_mono(wav)
        finally:
            wav.unlink(missing_ok=True)
    return decode_with_av(source)


# ---------------------------------------------------------------------------
# Modello
# ---------------------------------------------------------------------------

_model_cache: dict[tuple[str, str, str], object] = {}
_model_lock = threading.Lock()


def load_model(model_size: str = DEFAULT_MODEL, device: str = "auto", compute_type: str = "default"):
    """Carica (e tiene in cache) un WhisperModel di faster-whisper.

    device: "auto" usa la GPU NVIDIA (CUDA) se disponibile, altrimenti CPU.
    compute_type "default": int8 su CPU (veloce e leggero), float16 su GPU.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Manca la libreria 'faster-whisper'. Installa le dipendenze con:\n"
            "    pip install -r requirements.txt"
        ) from e

    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    if compute_type == "default":
        compute_type = "float16" if device == "cuda" else "int8"

    # Modello gia' presente accanto al programma (incluso nel pacchetto
    # Windows o scaricato in precedenza)? Allora niente rete.
    local_dir = models_dir() / model_size
    if (local_dir / "model.bin").is_file():
        source = str(local_dir)
        kwargs = {}
    else:
        source = model_size
        kwargs = {"download_root": str(models_dir() / "_cache")}

    key = (model_size, device, compute_type)
    with _model_lock:
        model = _model_cache.get(key)
        if model is None:
            try:
                model = WhisperModel(source, device=device, compute_type=compute_type, **kwargs)
                if device == "cuda":
                    _warmup(model)
            except Exception as e:
                if device == "cuda":
                    # GPU rilevata ma librerie CUDA (cuBLAS/cuDNN) assenti o incomplete.
                    # L'errore compare solo alla prima inferenza, non nel costruttore:
                    # per questo il warm-up. Ripiega sulla CPU.
                    try:
                        model = WhisperModel(source, device="cpu", compute_type="int8", **kwargs)
                    except Exception as e2:
                        raise RuntimeError(_model_error(model_size, e2)) from e2
                else:
                    raise RuntimeError(_model_error(model_size, e)) from e
            _model_cache[key] = model
    return model


def _warmup(model) -> None:
    """Prima inferenza su un secondo di silenzio. Su GPU e' qui, non nel
    costruttore, che emergono le DLL CUDA mancanti (es. cublas64_12.dll)."""
    import numpy as np
    segments, _ = model.transcribe(np.zeros(SAMPLE_RATE, dtype="float32"), language="en", beam_size=1, vad_filter=False)
    for _ in segments:
        pass


def local_models() -> list[str]:
    """Nomi dei modelli gia' su disco: models/<nome>/model.bin (inclusi nel
    pacchetto o copiati a mano) e quelli scaricati da Hugging Face in models/_cache."""
    found = {d.name for d in models_dir().glob("*") if (d / "model.bin").is_file()}
    for snap in (models_dir() / "_cache").glob("models--Systran--faster-whisper-*/snapshots/*/model.bin"):
        found.add(snap.parents[2].name.replace("models--Systran--faster-whisper-", ""))
    return sorted(found)


def _model_error(model_size: str, e: Exception) -> str:
    msg = str(e)
    net_words = ("Connection", "connection", "Proxy", "proxy", "403", "404", "timed out", "Max retries", "resolve", "huggingface")
    if any(w in msg for w in net_words):
        return (
            f"Impossibile scaricare il modello '{model_size}' da Hugging Face.\n"
            "Al primo utilizzo di ogni modello serve una connessione internet "
            "(poi funziona offline). Controlla la rete, eventuali proxy o firewall e riprova.\n"
            f"Dettaglio: {msg[:300]}"
        )
    return f"Impossibile caricare il modello '{model_size}': {msg[:300]}"


# ---------------------------------------------------------------------------
# Trascrizione
# ---------------------------------------------------------------------------

def transcribe_file(
    source: os.PathLike | str,
    *,
    model_size: str = DEFAULT_MODEL,
    language: Optional[str] = None,
    timestamps: bool = False,
    vad: bool = True,
    output_dir: Optional[os.PathLike | str] = None,
    device: str = "auto",
    progress: Optional[Callable[[float, str], None]] = None,
    cancel: Optional[threading.Event] = None,
    model=None,
) -> TranscriptionResult:
    """Trascrive un singolo file audio/video e scrive il .txt.

    progress(frazione 0..1, messaggio) viene chiamata durante l'elaborazione.
    cancel: threading.Event; se impostato l'elaborazione si interrompe.
    """
    source = Path(source).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"File non trovato: {source}")
    out_dir = Path(output_dir).expanduser() if output_dir else None

    def report(frac: float, msg: str) -> None:
        if progress:
            progress(max(0.0, min(1.0, frac)), msg)

    def check_cancel() -> None:
        if cancel is not None and cancel.is_set():
            raise TranscriptionCancelled()

    try:
        # 1) Decodifica audio in un array mono 16 kHz (via ffmpeg se presente,
        #    altrimenti PyAV). Passando l'array a faster-whisper evitiamo il suo
        #    decoder interno, che cambia con le versioni di PyAV.
        report(0.02, f"Estrazione audio da {source.name}...")
        audio_input = load_audio(source, cancel)
        if audio_input.size == 0:
            raise RuntimeError(f"'{source.name}' non contiene audio")
        check_cancel()

        # 2) Caricamento modello (al primo avvio lo scarica).
        if model is None:
            report(0.05, f"Caricamento modello '{model_size}' (al primo avvio viene scaricato)...")
            model = load_model(model_size, device=device)
        check_cancel()

        # 3) Trascrizione: faster-whisper restituisce un generatore di
        #    segmenti; l'avanzamento si calcola dal tempo di fine segmento.
        report(0.08, f"Trascrizione di {source.name}...")
        try:
            segments, info = model.transcribe(
                audio_input,
                language=language,
                beam_size=5,
                vad_filter=vad,
                vad_parameters={"min_silence_duration_ms": 500} if vad else None,
                condition_on_previous_text=True,
            )
        except ValueError as e:  # es. codice lingua non valido ("xx", "Italiano")
            raise RuntimeError(f"Parametri non validi per '{source.name}': {str(e)[:200]}") from e
        duration = float(getattr(info, "duration", 0) or 0.0) or len(audio_input) / SAMPLE_RATE
        lines: list[str] = []
        plain: list[str] = []
        for seg in segments:
            check_cancel()
            text = seg.text.strip()
            if not text:
                continue
            plain.append(text)
            if timestamps:
                lines.append(f"[{format_timestamp(seg.start)}] {text}")
            else:
                lines.append(text)
            if duration > 0:
                report(0.08 + 0.90 * (seg.end / duration), f"Trascrizione di {source.name}... {format_timestamp(seg.end)} / {format_timestamp(duration)}")

        # 4) Scrittura del file di testo.
        if timestamps:
            body = "\n".join(lines)
        else:
            # Paragrafi: uniamo le frasi, andando a capo ogni ~600 caratteri
            # per rendere il blocco note leggibile.
            body = _paragraphs(plain)

        header = (
            f"Trascrizione di: {source.name}\n"
            f"Lingua rilevata: {info.language} (probabilita' {info.language_probability:.0%})\n"
            f"Durata: {format_timestamp(duration)}\n"
            f"Modello: {model_size}\n"
            + "-" * 60 + "\n\n"
        )
        if not plain:
            # Silenzio, solo musica o parlato troppo sommesso: meglio dirlo nel
            # file che lasciare un .txt vuoto senza spiegazione.
            body = "(nessun parlato rilevato: file silenzioso o solo musica; prova a disattivare 'Salta i silenzi')"
        out_path = output_path_for(source, out_dir)
        out_path.write_text(header + body + "\n", encoding="utf-8")
        report(1.0, f"Completato: {out_path.name}")
        return TranscriptionResult(
            source=source,
            output=out_path,
            language=info.language,
            language_probability=float(info.language_probability),
            duration=duration,
            text=body if plain else "",
        )
    finally:
        pass


def _paragraphs(sentences: list[str], max_chars: int = 600) -> str:
    paragraphs: list[str] = []
    current = ""
    for s in sentences:
        if current and len(current) + 1 + len(s) > max_chars and current.rstrip().endswith((".", "!", "?")):
            paragraphs.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    if current:
        paragraphs.append(current)
    return "\n\n".join(paragraphs)


def transcribe_many(
    sources: Iterable[os.PathLike | str],
    *,
    progress: Optional[Callable[[int, int, float, str], None]] = None,
    cancel: Optional[threading.Event] = None,
    model_size: str = DEFAULT_MODEL,
    device: str = "auto",
    **kwargs,
) -> list[TranscriptionResult]:
    """Trascrive piu' file/cartelle. progress(indice, totale, frazione, msg)."""
    files = collect_media_files(sources)
    results: list[TranscriptionResult] = []
    if not files:
        return results
    model = load_model(model_size, device=device)
    total = len(files)
    for i, f in enumerate(files):
        def per_file(frac: float, msg: str, _i=i) -> None:
            if progress:
                progress(_i, total, frac, msg)
        results.append(
            transcribe_file(f, model_size=model_size, device=device, progress=per_file, cancel=cancel, model=model, **kwargs)
        )
    return results


# ---------------------------------------------------------------------------
# Auto-test (usato dalla build automatica dell'eseguibile)
# ---------------------------------------------------------------------------

def selftest(model_size: str = DEFAULT_MODEL, log_path: Optional[Path] = None) -> int:
    """Importa le librerie, carica il modello e trascrive 2 secondi di audio
    sintetico. Scrive l'esito in selftest.log (l'eseguibile Windows non ha
    console). Ritorna 0 se tutto funziona, 1 altrimenti."""
    import datetime
    import wave
    log_path = log_path or (app_dir() / "selftest.log")
    lines = [f"Audio to Text selftest - {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"]
    code = 0
    wav: Optional[Path] = None
    try:
        import faster_whisper, ctranslate2, onnxruntime, av, numpy  # noqa: F401
        lines.append(f"faster-whisper {faster_whisper.__version__}, ctranslate2 {ctranslate2.__version__}, "
                     f"onnxruntime {onnxruntime.__version__}, av {av.__version__}, numpy {numpy.__version__}")
        lines.append(f"ffmpeg: {find_ffmpeg() or 'non trovato (uso il decoder interno)'}")
        lines.append(f"cartella modelli: {models_dir()} (incluso: {(models_dir() / model_size / 'model.bin').is_file()})")
        # 2 s di tono a 440 Hz, 16 kHz mono
        tmp = tempfile.NamedTemporaryFile(prefix="a2t_selftest_", suffix=".wav", delete=False)
        tmp.close()
        wav = Path(tmp.name)
        t = numpy.arange(0, 2 * 16000) / 16000.0
        samples = (0.2 * numpy.sin(2 * numpy.pi * 440 * t) * 32767).astype("<i2")
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(samples.tobytes())
        model = load_model(model_size)
        res = transcribe_file(wav, model=model, model_size=model_size, vad=False, output_dir=wav.parent)
        lines.append(f"modello '{model_size}' caricato e trascrizione eseguita (lingua {res.language}, durata {res.duration:.1f}s)")
        res.output.unlink(missing_ok=True)
        lines.append("ESITO: OK")
    except Exception as e:
        lines.append(f"ESITO: ERRORE - {type(e).__name__}: {e}")
        code = 1
    finally:
        if wav is not None:
            wav.unlink(missing_ok=True)
    text = "\n".join(lines) + "\n"
    try:
        log_path.write_text(text, encoding="utf-8")
    except OSError:
        pass
    try:
        print(text, end="")
    except Exception:
        pass
    return code


# ---------------------------------------------------------------------------
# Riga di comando
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Converte registrazioni audio/video in file di testo (.txt), gratis e offline.",
    )
    parser.add_argument("inputs", nargs="+", help="file audio/video o cartelle")
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=MODELS, help=f"modello Whisper (default: {DEFAULT_MODEL})")
    parser.add_argument("--language", default=None, help="codice lingua (it, en, ...); default: rilevamento automatico")
    parser.add_argument("--timestamps", action="store_true", help="aggiunge [hh:mm:ss] all'inizio di ogni frase")
    parser.add_argument("--no-vad", action="store_true", help="disattiva il filtro che salta i silenzi")
    parser.add_argument("--output", default=None, help="cartella di destinazione dei .txt (default: accanto al file)")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"], help="dispositivo di calcolo")
    args = parser.parse_args(argv)

    files = collect_media_files(args.inputs)
    if not files:
        print("Nessun file audio/video trovato.", file=sys.stderr)
        return 1
    if not find_ffmpeg():
        print("Attenzione: ffmpeg non trovato. I file video e alcuni formati audio potrebbero non funzionare.", file=sys.stderr)

    cancel = threading.Event()

    def progress(i: int, total: int, frac: float, msg: str) -> None:
        print(f"\r[{i + 1}/{total}] {int(frac * 100):3d}%  {msg:<70}", end="", flush=True)

    try:
        results = transcribe_many(
            files,
            model_size=args.model,
            language=args.language,
            timestamps=args.timestamps,
            vad=not args.no_vad,
            output_dir=args.output,
            device=args.device,
            progress=progress,
            cancel=cancel,
        )
    except KeyboardInterrupt:
        cancel.set()
        print("\nInterrotto.")
        return 130
    except RuntimeError as e:  # modello non caricabile, file illeggibile, lingua non valida
        print(f"\nERRORE: {e}", file=sys.stderr)
        return 1
    print()
    for r in results:
        print(f"{r.source.name}  ->  {r.output}  ({r.language}, {format_timestamp(r.duration)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
