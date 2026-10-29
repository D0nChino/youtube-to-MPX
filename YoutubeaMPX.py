#!/usr/bin/env python3
"""
Descargador con interfaz gráfica (tkinter + yt-dlp).

Instalación:
    python -m pip install -U "yt-dlp[default]"
    ffmpeg (necesario para MP3 y para unir video + audio en HD)
    En Windows:  winget install Gyan.FFmpeg   (luego reinicia VS Code)
    Deno (runtime de JavaScript que YouTube exige para extraer los formatos)
    En Windows:  winget install DenoLand.Deno   (luego reinicia VS Code)

Úsalo solo con contenido propio, con licencia que lo permita o de dominio público.
"""
import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

MODOS = {
    "Video + audio (MP4)": "va",
    "Solo audio (MP3)": "a",
    "Solo video (sin audio)": "v",
}
CALIDADES = {
    "Mejor disponible": None,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}


def construir_opciones(modo, altura, carpeta, hay_ffmpeg, hook, pp_hook, logger):
    filtro = f"[height<=?{altura}]" if altura else ""
    opciones = {
        "outtmpl": str(Path(carpeta) / "%(title).150s.%(ext)s"),
        "noplaylist": True,  # evita bajar una lista de reproducción entera
        "quiet": True,
        "noprogress": True,
        "color": "no_color",
        # Se usa el primer runtime de JavaScript que esté instalado.
        "js_runtimes": {"deno": {}, "node": {}, "bun": {}, "quickjs": {}},
        "logger": logger,
        "progress_hooks": [hook],
        "postprocessor_hooks": [pp_hook],
    }

    if modo == "a":
        opciones["format"] = "bestaudio/best"
        opciones["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    elif modo == "v":
        opciones["format"] = (f"bestvideo{filtro}[ext=mp4]/"
                              f"bestvideo{filtro}/best{filtro}")
    else:  # video + audio
        if hay_ffmpeg:
            opciones["format"] = (
                f"bestvideo{filtro}[ext=mp4]+bestaudio[ext=m4a]/"
                f"bestvideo{filtro}+bestaudio/best{filtro}")
            opciones["merge_output_format"] = "mp4"
        else:
            # Sin ffmpeg no se pueden unir pistas: se usa un archivo único.
            opciones["format"] = f"best{filtro}"
    return opciones


def trabajador(url, modo, altura, carpeta, cola):
    """Corre en un hilo aparte para no congelar la ventana."""

    class Registro:
        def debug(self, msg):
            if not msg.startswith("[debug]"):
                cola.put(("log", msg))

        def info(self, msg):
            cola.put(("log", msg))

        def warning(self, msg):
            cola.put(("log", f"Aviso: {msg}"))

        def error(self, msg):
            cola.put(("log", f"Error: {msg}"))

    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                pct = d["downloaded_bytes"] * 100 / total
                vel = d.get("speed")
                vel_txt = f"{vel / 1_000_000:.1f} MB/s" if vel else "..."
                eta = d.get("eta")
                eta_txt = f"{eta}s" if eta is not None else "..."
                cola.put(("progreso", pct,
                          f"Descargando {pct:.1f}%  |  {vel_txt}  |  "
                          f"faltan {eta_txt}"))
        elif d["status"] == "finished":
            cola.put(("progreso", 100, "Descarga terminada, procesando..."))

    def pp_hook(d):
        if d["status"] == "started":
            cola.put(("estado", f"Procesando con ffmpeg ({d['postprocessor']})..."))

    opciones = construir_opciones(modo, altura, carpeta,
                                  shutil.which("ffmpeg") is not None,
                                  hook, pp_hook, Registro())
    try:
        with YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(url, download=True)
        cola.put(("fin", True, f"Listo: {info.get('title', 'archivo')}"))
    except DownloadError as e:
        texto = str(e)
        if "Requested format is not available" in texto:
            texto += ("\nPista: en YouTube suele faltar un runtime de JavaScript "
                      "o yt-dlp está desactualizado. Instala Deno "
                      "(winget install DenoLand.Deno), reinicia VS Code y "
                      "ejecuta: python -m pip install -U \"yt-dlp[default]\"")
        cola.put(("fin", False, texto))
    except Exception as e:  # cualquier otro fallo inesperado
        cola.put(("fin", False, f"{type(e).__name__}: {e}"))


class App:
    def __init__(self, root):
        self.root = root
        root.title("Descargador de medios")
        root.geometry("640x470")
        root.minsize(560, 420)
        self.cola = queue.Queue()
        self.hay_ffmpeg = shutil.which("ffmpeg") is not None

        carpeta_defecto = Path.home() / "Downloads"
        if not carpeta_defecto.exists():
            carpeta_defecto = Path.home()

        self.var_url = tk.StringVar()
        self.var_modo = tk.StringVar(value="Video + audio (MP4)")
        self.var_calidad = tk.StringVar(value="Mejor disponible")
        self.var_carpeta = tk.StringVar(value=str(carpeta_defecto))

        marco = ttk.Frame(root, padding=14)
        marco.pack(fill="both", expand=True)
        marco.columnconfigure(1, weight=1)

        ttk.Label(marco, text="Enlace:").grid(row=0, column=0, sticky="w")
        entrada = ttk.Entry(marco, textvariable=self.var_url)
        entrada.grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)
        entrada.focus()

        ttk.Label(marco, text="Formato:").grid(row=1, column=0, sticky="w")
        modos = ttk.Frame(marco)
        modos.grid(row=1, column=1, columnspan=2, sticky="w", pady=4)
        for nombre in MODOS:
            ttk.Radiobutton(modos, text=nombre, value=nombre,
                            variable=self.var_modo,
                            command=self.actualizar_calidad).pack(
                side="left", padx=(0, 12))

        ttk.Label(marco, text="Calidad:").grid(row=2, column=0, sticky="w")
        self.combo = ttk.Combobox(marco, textvariable=self.var_calidad,
                                  values=list(CALIDADES), state="readonly",
                                  width=18)
        self.combo.grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(marco, text="Guardar en:").grid(row=3, column=0, sticky="w")
        ttk.Entry(marco, textvariable=self.var_carpeta).grid(
            row=3, column=1, sticky="ew", pady=4)
        ttk.Button(marco, text="Cambiar...", command=self.elegir_carpeta).grid(
            row=3, column=2, padx=(6, 0))

        self.boton = ttk.Button(marco, text="Descargar", command=self.iniciar)
        self.boton.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 6))

        self.barra = ttk.Progressbar(marco, maximum=100)
        self.barra.grid(row=5, column=0, columnspan=3, sticky="ew")

        self.var_estado = tk.StringVar(value="Pega un enlace y elige un formato.")
        ttk.Label(marco, textvariable=self.var_estado).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(4, 6))

        self.log = tk.Text(marco, height=9, state="disabled", wrap="word")
        self.log.grid(row=7, column=0, columnspan=3, sticky="nsew")
        marco.rowconfigure(7, weight=1)

        if not self.hay_ffmpeg:
            self.escribir_log(
                "ffmpeg no encontrado: sin él no se puede convertir a MP3 ni "
                "unir video y audio (YouTube los entrega por separado). "
                "Instálalo con:  winget install Gyan.FFmpeg  y reinicia "
                "VS Code. Solo funcionará 'Solo video (sin audio)'.")

        self.hay_js = any(shutil.which(x) for x in ("deno", "node", "bun", "qjs"))
        if not self.hay_js:
            self.escribir_log(
                "No se encontró un runtime de JavaScript (Deno/Node). YouTube "
                "lo necesita para mostrar los formatos. Instálalo con:  "
                "winget install DenoLand.Deno  y reinicia VS Code.")

        root.after(100, self.revisar_cola)

    def actualizar_calidad(self):
        solo_audio = MODOS[self.var_modo.get()] == "a"
        self.combo.configure(state="disabled" if solo_audio else "readonly")

    def elegir_carpeta(self):
        carpeta = filedialog.askdirectory(initialdir=self.var_carpeta.get())
        if carpeta:
            self.var_carpeta.set(carpeta)

    def escribir_log(self, texto):
        self.log.configure(state="normal")
        self.log.insert("end", texto + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def iniciar(self):
        url = self.var_url.get().strip()
        if not url.startswith(("http://", "https://")):
            self.var_estado.set("Ingresa un enlace válido (http:// o https://).")
            return
        modo = MODOS[self.var_modo.get()]
        if modo in ("va", "a") and not self.hay_ffmpeg:
            self.var_estado.set(
                "Este formato necesita ffmpeg (mira el aviso abajo).")
            return

        self.boton.configure(state="disabled")
        self.barra["value"] = 0
        self.var_estado.set("Analizando enlace...")
        altura = CALIDADES[self.var_calidad.get()]
        threading.Thread(
            target=trabajador,
            args=(url, modo, altura, self.var_carpeta.get(), self.cola),
            daemon=True,
        ).start()

    def revisar_cola(self):
        try:
            while True:
                msg = self.cola.get_nowait()
                if msg[0] == "log":
                    self.escribir_log(msg[1])
                elif msg[0] == "progreso":
                    self.barra["value"] = msg[1]
                    self.var_estado.set(msg[2])
                elif msg[0] == "estado":
                    self.var_estado.set(msg[1])
                elif msg[0] == "fin":
                    self.boton.configure(state="normal")
                    if msg[1]:
                        self.barra["value"] = 100
                        self.var_estado.set(msg[2])
                    else:
                        self.var_estado.set("Falló la descarga (detalle abajo).")
                        self.escribir_log(msg[2])
        except queue.Empty:
            pass
        self.root.after(100, self.revisar_cola)


if __name__ == "__main__":
    ventana = tk.Tk()
    App(ventana)
    ventana.mainloop()