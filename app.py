#!/usr/bin/env python3
"""
app.py - Interfaccia grafica (Tkinter) di Audio to Text.

Avvio:  python3 app.py

Scegli uno o piu' file audio/video (o una cartella), seleziona il modello e
la lingua, premi "Avvia trascrizione": per ogni file viene creato un .txt con
il testo completo. Tutto gira in locale, senza servizi a pagamento.
"""

from __future__ import annotations

import queue
import sys
import threading
import webbrowser
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover
    print(
        "Tkinter non e' disponibile in questo Python.\n"
        "- macOS (Homebrew): brew install python-tk\n"
        "- Debian/Ubuntu:    sudo apt install python3-tk\n"
        "- Windows/python.org: reinstalla Python spuntando 'tcl/tk and IDLE'.",
        file=sys.stderr,
    )
    sys.exit(1)

import transcriber as tr

APP_TITLE = "Audio to Text - trascrizione gratuita offline"
FILETYPES = [
    ("Audio e video", " ".join(f"*{e}" for e in sorted(tr.MEDIA_EXTS))),
    ("Audio", " ".join(f"*{e}" for e in sorted(tr.AUDIO_EXTS))),
    ("Video", " ".join(f"*{e}" for e in sorted(tr.VIDEO_EXTS))),
    ("Tutti i file", "*.*"),
]


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("880x700")
        self.minsize(760, 600)
        self.files: list[Path] = []
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.results: list[tr.TranscriptionResult] = []

        self._build_ui()
        self._check_ffmpeg()
        self.after(100, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        # --- Pulsanti (ancorati in basso, mai nascosti dal resto) -------
        actions = ttk.Frame(root)
        actions.pack(side="bottom", fill="x", **pad)
        self.start_btn = ttk.Button(actions, text="Avvia trascrizione", command=self._start)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(actions, text="Annulla", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=4)
        self.open_btn = ttk.Button(actions, text="Apri cartella risultati", command=self._open_results, state="disabled")
        self.open_btn.pack(side="right")

        # --- Lista file -------------------------------------------------
        files_box = ttk.LabelFrame(root, text="1. File da trascrivere (audio o video)")
        files_box.pack(fill="both", expand=True, **pad)

        list_frame = ttk.Frame(files_box)
        list_frame.pack(fill="both", expand=True, padx=6, pady=(6, 2))
        self.listbox = tk.Listbox(list_frame, selectmode="extended", height=6)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btns = ttk.Frame(files_box)
        btns.pack(fill="x", padx=6, pady=(2, 6))
        ttk.Button(btns, text="Aggiungi file...", command=self._add_files).pack(side="left")
        ttk.Button(btns, text="Aggiungi cartella...", command=self._add_folder).pack(side="left", padx=4)
        ttk.Button(btns, text="Rimuovi selezionati", command=self._remove_selected).pack(side="left")
        ttk.Button(btns, text="Svuota", command=self._clear).pack(side="left", padx=4)
        self.count_var = tk.StringVar(value="0 file")
        ttk.Label(btns, textvariable=self.count_var).pack(side="right")

        # --- Opzioni ----------------------------------------------------
        opts = ttk.LabelFrame(root, text="2. Opzioni")
        opts.pack(fill="x", **pad)
        for c in range(4):
            opts.columnconfigure(c, weight=1 if c in (1, 3) else 0)

        ttk.Label(opts, text="Modello:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.model_var = tk.StringVar(value=tr.DEFAULT_MODEL)
        model_cb = ttk.Combobox(opts, textvariable=self.model_var, values=tr.MODELS, state="readonly", width=16)
        model_cb.grid(row=0, column=1, sticky="w", padx=6)
        self.model_info = tk.StringVar(value=tr.MODEL_INFO[tr.DEFAULT_MODEL])
        ttk.Label(opts, textvariable=self.model_info, foreground="#555").grid(row=0, column=2, columnspan=2, sticky="w", padx=6)
        model_cb.bind("<<ComboboxSelected>>", lambda _e: self.model_info.set(tr.MODEL_INFO.get(self.model_var.get(), "")))

        ttk.Label(opts, text="Lingua:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.lang_var = tk.StringVar(value="auto")
        ttk.Combobox(opts, textvariable=self.lang_var, values=list(tr.LANGUAGES.keys()), state="readonly", width=16).grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(opts, text="'auto' = rilevamento automatico", foreground="#555").grid(row=1, column=2, columnspan=2, sticky="w", padx=6)

        self.ts_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Includi timestamp [hh:mm:ss] a inizio frase", variable=self.ts_var).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=2)
        self.vad_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Salta i silenzi (consigliato)", variable=self.vad_var).grid(row=2, column=2, columnspan=2, sticky="w", padx=6, pady=2)

        ttk.Label(opts, text="Salva i .txt in:").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        self.out_var = tk.StringVar(value="")
        out_entry = ttk.Entry(opts, textvariable=self.out_var)
        out_entry.grid(row=3, column=1, columnspan=2, sticky="ew", padx=6)
        ttk.Button(opts, text="Scegli...", command=self._choose_output).grid(row=3, column=3, sticky="w", padx=6)
        ttk.Label(opts, text="(vuoto = accanto a ogni file originale)", foreground="#555").grid(row=4, column=1, columnspan=3, sticky="w", padx=6)

        # --- Avanzamento ------------------------------------------------
        prog = ttk.LabelFrame(root, text="3. Avanzamento")
        prog.pack(fill="both", expand=True, **pad)
        self.progress = ttk.Progressbar(prog, mode="determinate", maximum=1000)
        self.progress.pack(fill="x", padx=6, pady=(6, 2))
        self.status_var = tk.StringVar(value="Pronto.")
        ttk.Label(prog, textvariable=self.status_var).pack(anchor="w", padx=6)
        self.log = tk.Text(prog, height=7, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=6, pady=(2, 6))


    # ------------------------------------------------------------- helpers
    def _log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _check_ffmpeg(self) -> None:
        inclusi = tr.local_models()
        if inclusi:
            self._log(f"Modelli gia' disponibili offline: {', '.join(inclusi)}. Gli altri vengono scaricati al primo uso.")
        if tr.find_ffmpeg():
            self._log("ffmpeg trovato: tutti i formati audio/video sono supportati.")
        else:
            self._log(
                "ffmpeg non trovato: uso il decoder interno (va bene per mp3, wav, m4a, mp4, mov e la maggior parte dei formati).\n"
                "Per i formati piu' rari installa ffmpeg: macOS 'brew install ffmpeg' - Windows https://ffmpeg.org/download.html - Linux 'sudo apt install ffmpeg'."
            )

    def _refresh_list(self) -> None:
        self.listbox.delete(0, "end")
        for f in self.files:
            self.listbox.insert("end", str(f))
        self.count_var.set(f"{len(self.files)} file")

    def _add_paths(self, paths) -> None:
        new = tr.collect_media_files(paths)
        existing = {f.resolve() for f in self.files}
        added = 0
        for f in new:
            if f.resolve() not in existing:
                self.files.append(f)
                existing.add(f.resolve())
                added += 1
        self._refresh_list()
        if not new:
            messagebox.showinfo(APP_TITLE, "Nessun file audio/video riconosciuto nella selezione.")
        elif added == 0:
            self._log("I file selezionati erano gia' in lista.")

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(title="Scegli file audio o video", filetypes=FILETYPES)
        if paths:
            self._add_paths(paths)

    def _add_folder(self) -> None:
        d = filedialog.askdirectory(title="Scegli una cartella (ricerca anche nelle sottocartelle)")
        if d:
            self._add_paths([d])

    def _remove_selected(self) -> None:
        for idx in sorted(self.listbox.curselection(), reverse=True):
            del self.files[idx]
        self._refresh_list()

    def _clear(self) -> None:
        self.files.clear()
        self._refresh_list()

    def _choose_output(self) -> None:
        d = filedialog.askdirectory(title="Cartella dove salvare i file .txt")
        if d:
            self.out_var.set(d)

    def _set_running(self, running: bool) -> None:
        self.start_btn.configure(state="disabled" if running else "normal")
        self.cancel_btn.configure(state="normal" if running else "disabled")

    # ---------------------------------------------------------------- run
    def _start(self) -> None:
        if not self.files:
            messagebox.showwarning(APP_TITLE, "Aggiungi almeno un file audio o video.")
            return
        if self.worker and self.worker.is_alive():
            return
        self.cancel.clear()
        self.results = []
        self.progress["value"] = 0
        self._set_running(True)
        self.open_btn.configure(state="disabled")
        self._log(f"--- Avvio: {len(self.files)} file, modello '{self.model_var.get()}', lingua '{self.lang_var.get()}' ---")

        files = list(self.files)
        params = dict(
            model_size=self.model_var.get(),
            language=tr.LANGUAGES.get(self.lang_var.get()),
            timestamps=self.ts_var.get(),
            vad=self.vad_var.get(),
            output_dir=self.out_var.get().strip() or None,
        )
        self.worker = threading.Thread(target=self._run, args=(files, params), daemon=True)
        self.worker.start()

    def _run(self, files: list[Path], params: dict) -> None:
        """Thread di lavoro: non tocca mai i widget, manda eventi in coda."""
        try:
            self.events.put(("status", 0.0, "Caricamento modello (al primo avvio viene scaricato, puo' richiedere qualche minuto)..."))
            model = tr.load_model(params["model_size"])
            total = len(files)
            for i, f in enumerate(files):
                if self.cancel.is_set():
                    raise tr.TranscriptionCancelled()

                def progress(frac: float, msg: str, _i=i) -> None:
                    self.events.put(("status", (_i + frac) / total, f"[{_i + 1}/{total}] {msg}"))

                try:
                    res = tr.transcribe_file(f, progress=progress, cancel=self.cancel, model=model, **params)
                except tr.TranscriptionCancelled:
                    raise
                except Exception as e:  # errore su un singolo file: continua con gli altri
                    self.events.put(("log", f"ERRORE su {f.name}: {e}"))
                    continue
                self.results.append(res)
                if not res.text:
                    self.events.put(("log", f"ATTENZIONE  {f.name}: nessun parlato rilevato (silenzio o solo musica). Prova senza 'Salta i silenzi'."))
                self.events.put(("log", f"OK  {f.name}  ->  {res.output}  (lingua: {res.language}, {tr.format_timestamp(res.duration)})"))
            self.events.put(("done", None))
        except tr.TranscriptionCancelled:
            self.events.put(("cancelled", None))
        except Exception as e:
            self.events.put(("error", str(e)))

    def _poll_events(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "status":
                    self.progress["value"] = int(ev[1] * 1000)
                    self.status_var.set(ev[2])
                elif kind == "log":
                    self._log(ev[1])
                elif kind == "done":
                    self.progress["value"] = 1000
                    n = len(self.results)
                    self.status_var.set(f"Completato: {n} file trascritti.")
                    self._log(f"--- Fine: {n} file di testo creati. ---")
                    self._set_running(False)
                    if n:
                        self.open_btn.configure(state="normal")
                        messagebox.showinfo(APP_TITLE, f"Trascrizione completata.\n{n} file .txt creati.")
                elif kind == "cancelled":
                    self.status_var.set("Annullato.")
                    self._log("--- Annullato dall'utente. ---")
                    self._set_running(False)
                    if self.results:
                        self.open_btn.configure(state="normal")
                elif kind == "error":
                    self.status_var.set("Errore.")
                    self._log(f"ERRORE: {ev[1]}")
                    self._set_running(False)
                    messagebox.showerror(APP_TITLE, ev[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _cancel(self) -> None:
        self.cancel.set()
        self.status_var.set("Annullamento in corso...")

    def _open_results(self) -> None:
        if not self.results:
            return
        folder = self.results[-1].output.parent
        webbrowser.open(folder.as_uri())

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_TITLE, "Una trascrizione e' in corso. Vuoi davvero uscire?"):
                return
            self.cancel.set()
        self.destroy()


def main() -> None:
    if "--selftest" in sys.argv[1:]:
        # Usato dalla build automatica: nessuna finestra, esito in selftest.log.
        sys.exit(tr.selftest())
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
