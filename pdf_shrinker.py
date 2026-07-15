from __future__ import annotations

import io
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None

try:
    import fitz
except ImportError:
    fitz = None

try:
    from PIL import Image
except ImportError:
    Image = None

APP_NAME = "PDF Shrinker"
APP_VERSION = "1.0.1"

BG = "#07111f"
PANEL = "#0d1b2d"
PANEL_2 = "#12243a"
TEXT = "#f4f7fb"
MUTED = "#9fb0c3"
ACCENT = "#9eff3c"
BORDER = "#24415f"

PRESETS = {
    "Auto smallest (may rasterize)": (("lossless", "gs_screen", "raster"), 82, 34),
    "Extreme minimum (rasterized)": (("raster",), 72, 28),
    "Smallest with selectable text": (("gs_screen", "lossless"), 72, 35),
    "Balanced with selectable text": (("gs_ebook", "lossless"), 110, 50),
    "Lossless cleanup only": (("lossless",), 0, 0),
}

DESCRIPTIONS = {
    "Auto smallest (may rasterize)": "Tries available methods and keeps the smallest valid PDF.",
    "Extreme minimum (rasterized)": "Usually smallest. Pages become JPEG images.",
    "Smallest with selectable text": "Ghostscript /screen compression with lossless fallback.",
    "Balanced with selectable text": "Ghostscript /ebook compression with lossless fallback.",
    "Lossless cleanup only": "Recompresses streams and removes unused PDF objects.",
}


def resource_path(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def human_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} GB"


def output_path(source: Path, folder: Path | None) -> Path:
    root = folder or source.parent
    root.mkdir(parents=True, exist_ok=True)
    result = root / f"{source.stem}_compressed.pdf"
    number = 2
    while result.exists():
        result = root / f"{source.stem}_compressed_{number}.pdf"
        number += 1
    return result


def find_ghostscript() -> Path | None:
    for name in ("gswin64c.exe", "gswin32c.exe", "gs"):
        found = shutil.which(name)
        if found:
            return Path(found)

    roots = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "gs",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "gs",
    )
    candidates: list[Path] = []
    for root in roots:
        if root.exists():
            candidates.extend(root.glob("gs*/bin/gswin64c.exe"))
            candidates.extend(root.glob("gs*/bin/gswin32c.exe"))
    return sorted(candidates, reverse=True)[0] if candidates else None


def valid_pdf(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with fitz.open(path) as document:
            return document.page_count > 0
    except Exception:
        return False


def compress_lossless(source: Path, destination: Path, stop: threading.Event) -> None:
    if stop.is_set():
        raise InterruptedError
    with fitz.open(source) as document:
        document.save(
            destination,
            garbage=4,
            clean=True,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
        )


def compress_raster(
    source: Path,
    destination: Path,
    dpi: int,
    quality: int,
    grayscale: bool,
    stop: threading.Event,
    report,
) -> None:
    if Image is None:
        raise RuntimeError("Pillow is not installed.")

    scale = max(36, dpi) / 72.0
    matrix = fitz.Matrix(scale, scale)
    colorspace = fitz.csGRAY if grayscale else fitz.csRGB

    with fitz.open(source) as source_pdf:
        result_pdf = fitz.open()
        try:
            for index, page in enumerate(source_pdf):
                if stop.is_set():
                    raise InterruptedError
                report(f"Rasterizing page {index + 1} of {source_pdf.page_count}")
                pixmap = page.get_pixmap(
                    matrix=matrix,
                    colorspace=colorspace,
                    alpha=False,
                    annots=True,
                )
                mode = "L" if grayscale else "RGB"
                image = Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples)
                data = io.BytesIO()
                image.save(
                    data,
                    format="JPEG",
                    quality=max(10, min(95, quality)),
                    optimize=True,
                    progressive=True,
                )
                new_page = result_pdf.new_page(width=page.rect.width, height=page.rect.height)
                new_page.insert_image(new_page.rect, stream=data.getvalue())

            result_pdf.save(destination, garbage=4, clean=True, deflate=True)
        finally:
            result_pdf.close()


def compress_ghostscript(
    source: Path,
    destination: Path,
    setting: str,
    grayscale: bool,
    stop: threading.Event,
) -> None:
    executable = find_ghostscript()
    if executable is None:
        raise FileNotFoundError("Ghostscript is not installed.")

    command = [
        str(executable),
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.5",
        f"-dPDFSETTINGS=/{setting}",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        "-dSAFER",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        f"-sOutputFile={destination}",
    ]
    if grayscale:
        command.extend(("-sColorConversionStrategy=Gray", "-dProcessColorModel=/DeviceGray"))
    command.append(str(source))

    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    while process.poll() is None:
        if stop.is_set():
            process.terminate()
            raise InterruptedError
        time.sleep(0.1)
    stdout, stderr = process.communicate()
    if process.returncode:
        detail = (stderr or stdout).decode(errors="replace").strip()
        raise RuntimeError(detail or f"Ghostscript exited with code {process.returncode}.")


def compress_one(
    source: Path,
    destination: Path,
    preset_name: str,
    grayscale: bool,
    stop: threading.Event,
    report,
) -> str:
    methods, dpi, quality = PRESETS[preset_name]
    candidates: list[tuple[Path, str]] = []

    with tempfile.TemporaryDirectory(prefix="pdf_shrinker_") as temp_name:
        temp = Path(temp_name)
        for method in methods:
            if stop.is_set():
                raise InterruptedError
            candidate = temp / f"{method}.pdf"
            try:
                if method == "lossless":
                    report("Running lossless cleanup")
                    compress_lossless(source, candidate, stop)
                    label = "Lossless cleanup"
                elif method == "raster":
                    compress_raster(source, candidate, dpi, quality, grayscale, stop, report)
                    label = "Rasterized"
                else:
                    report("Running Ghostscript")
                    setting = "screen" if method == "gs_screen" else "ebook"
                    compress_ghostscript(source, candidate, setting, grayscale, stop)
                    label = f"Ghostscript /{setting}"

                if valid_pdf(candidate):
                    candidates.append((candidate, label))
            except FileNotFoundError:
                report("Ghostscript unavailable - skipped")
            except InterruptedError:
                raise
            except Exception as exc:
                report(f"{method} skipped: {exc}")

        if not candidates:
            raise RuntimeError("No compression method produced a valid PDF.")

        best, label = min(candidates, key=lambda item: item[0].stat().st_size)
        if best.stat().st_size >= source.stat().st_size:
            shutil.copy2(source, destination)
            label = "Already optimal - original copied"
        else:
            shutil.copy2(best, destination)

    if not valid_pdf(destination):
        destination.unlink(missing_ok=True)
        raise RuntimeError("Output validation failed.")
    return label


class PdfShrinkerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("960x700")
        self.root.minsize(820, 600)
        self.root.configure(bg=BG)

        icon = resource_path("pdf_shrinker.ico")
        if icon.exists() and os.name == "nt":
            try:
                self.root.iconbitmap(default=str(icon))
            except tk.TclError:
                pass

        self.files: list[Path] = []
        self.rows: dict[Path, str] = {}
        self.events: queue.Queue[tuple] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None

        self.preset = tk.StringVar(value=next(iter(PRESETS)))
        self.description = tk.StringVar(value=DESCRIPTIONS[self.preset.get()])
        self.same_folder = tk.BooleanVar(value=True)
        self.output_folder = tk.StringVar()
        self.grayscale = tk.BooleanVar(value=False)
        self.open_folder = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Drop PDFs below or click Add PDFs.")

        self._styles()
        self._ui()
        self._enable_drop()
        self.root.after(100, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Accent.TButton", background=ACCENT, foreground=BG, padding=(18, 11), font=("Segoe UI Semibold", 11))
        style.map("Accent.TButton", background=[("active", "#b8ff7a"), ("disabled", "#44632a")])
        style.configure("Secondary.TButton", background=PANEL_2, foreground=TEXT, padding=(11, 8))
        style.configure("Danger.TButton", background="#3b1b28", foreground="#ff9aaa", padding=(11, 8))
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=30)
        style.configure("Treeview.Heading", background=PANEL_2, foreground=TEXT, padding=7)
        style.map("Treeview", background=[("selected", "#1f466d")])
        style.configure("Horizontal.TProgressbar", troughcolor=PANEL_2, background=ACCENT)
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)

    def _ui(self) -> None:
        outer = ttk.Frame(self.root, padding=22)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="PDF Shrinker", font=("Segoe UI Semibold", 24)).pack(side="left")
        ttk.Label(header, text="Drag, drop, compress.", style="Muted.TLabel").pack(side="left", padx=14, pady=(8, 0))

        border = tk.Frame(outer, bg=BORDER, padx=1, pady=1)
        border.pack(fill="x", pady=(18, 10))
        self.drop_zone = tk.Frame(border, bg=PANEL, height=112, cursor="hand2")
        self.drop_zone.pack(fill="x")
        self.drop_zone.pack_propagate(False)
        title = tk.Label(self.drop_zone, text="DROP PDF FILES HERE", bg=PANEL, fg=ACCENT, font=("Segoe UI Semibold", 16))
        title.pack(pady=(23, 4))
        subtitle = tk.Label(self.drop_zone, text="Multiple files supported - originals are never overwritten", bg=PANEL, fg=MUTED)
        subtitle.pack()
        for widget in (self.drop_zone, title, subtitle):
            widget.bind("<Button-1>", lambda _event: self.add_dialog())

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(0, 12))
        ttk.Button(controls, text="Add PDFs", style="Secondary.TButton", command=self.add_dialog).pack(side="left")
        ttk.Button(controls, text="Remove Selected", style="Secondary.TButton", command=self.remove_selected).pack(side="left", padx=8)
        ttk.Button(controls, text="Clear", style="Danger.TButton", command=self.clear).pack(side="left")
        self.top_run = ttk.Button(controls, text="RUN COMPRESSION", style="Accent.TButton", command=self.start)
        self.top_run.pack(side="right")

        frame = ttk.Frame(outer, style="Panel.TFrame")
        frame.pack(fill="both", expand=True)
        columns = ("file", "original", "status", "result", "saved")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        for column, title, width, anchor in (
            ("file", "PDF", 360, "w"),
            ("original", "Original", 95, "e"),
            ("status", "Status", 210, "w"),
            ("result", "Result", 95, "e"),
            ("saved", "Saved", 80, "e"),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor=anchor)
        scrollbar = ttk.Scrollbar(frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        settings = ttk.Frame(outer, style="Panel.TFrame", padding=14)
        settings.pack(fill="x", pady=(14, 0))
        row = ttk.Frame(settings, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Compression", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        combo = ttk.Combobox(row, textvariable=self.preset, values=list(PRESETS), state="readonly", width=36)
        combo.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        combo.bind("<<ComboboxSelected>>", lambda _event: self.description.set(DESCRIPTIONS[self.preset.get()]))

        ttk.Label(row, text="Custom output folder", style="Panel.TLabel").grid(row=0, column=1, sticky="w", padx=(18, 0))
        output_row = ttk.Frame(row, style="Panel.TFrame")
        output_row.grid(row=1, column=1, sticky="ew", padx=(18, 0), pady=(5, 0))
        self.output_entry = tk.Entry(output_row, textvariable=self.output_folder, bg=PANEL_2, fg=TEXT, insertbackground=TEXT, relief="flat")
        self.output_entry.pack(side="left", fill="x", expand=True, ipady=7)
        self.output_button = ttk.Button(output_row, text="Browse", style="Secondary.TButton", command=self.choose_output)
        self.output_button.pack(side="left", padx=(7, 0))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)

        ttk.Label(settings, textvariable=self.description, style="PanelMuted.TLabel").pack(anchor="w", pady=(8, 8))
        options = ttk.Frame(settings, style="Panel.TFrame")
        options.pack(fill="x")
        ttk.Checkbutton(options, text="Save beside each original", variable=self.same_folder, command=self._toggle_output).pack(side="left")
        ttk.Checkbutton(options, text="Grayscale raster output", variable=self.grayscale).pack(side="left", padx=18)
        ttk.Checkbutton(options, text="Open output folder when finished", variable=self.open_folder).pack(side="left")
        self._toggle_output()

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(14, 0))
        status_frame = ttk.Frame(bottom)
        status_frame.pack(side="left", fill="x", expand=True, padx=(0, 14))
        ttk.Label(status_frame, textvariable=self.status, style="Muted.TLabel").pack(anchor="w")
        self.progress = ttk.Progressbar(status_frame, maximum=100)
        self.progress.pack(fill="x", pady=(7, 0))
        self.stop_button = ttk.Button(bottom, text="Stop", style="Danger.TButton", command=self.stop, state="disabled")
        self.stop_button.pack(side="right", padx=(0, 8))
        self.run_button = ttk.Button(bottom, text="RUN COMPRESSION", style="Accent.TButton", command=self.start)
        self.run_button.pack(side="right")

    def _enable_drop(self) -> None:
        if DND_FILES is None:
            return
        try:
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind("<<Drop>>", self._drop)
        except tk.TclError:
            pass

    def _drop(self, event) -> None:
        self.add_paths(self.root.tk.splitlist(event.data))

    def add_dialog(self) -> None:
        paths = filedialog.askopenfilenames(title="Choose PDF files", filetypes=[("PDF files", "*.pdf")])
        self.add_paths(paths)

    def add_paths(self, paths) -> None:
        for raw in paths:
            path = Path(str(raw).strip().strip("{}")).expanduser().resolve()
            if path.suffix.lower() != ".pdf" or not path.is_file() or path in self.rows:
                continue
            row = self.tree.insert("", "end", values=(path.name, human_size(path.stat().st_size), "Queued", "-", "-"))
            self.files.append(path)
            self.rows[path] = row
        self.status.set(f"{len(self.files)} PDF(s) ready.")

    def remove_selected(self) -> None:
        selected = set(self.tree.selection())
        for path, row in list(self.rows.items()):
            if row in selected:
                self.tree.delete(row)
                self.files.remove(path)
                del self.rows[path]
        self.status.set(f"{len(self.files)} PDF(s) ready.")

    def clear(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.files.clear()
        self.rows.clear()
        self.progress["value"] = 0
        self.status.set("Drop PDFs below or click Add PDFs.")

    def choose_output(self) -> None:
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.output_folder.set(folder)

    def _toggle_output(self) -> None:
        state = "disabled" if self.same_folder.get() else "normal"
        self.output_entry.configure(state=state)
        self.output_button.configure(state=state)

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if fitz is None:
            messagebox.showerror(APP_NAME, "PyMuPDF is not installed. Run pip install -r requirements.txt.")
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "Add at least one PDF first.")
            return

        custom_folder = None
        if not self.same_folder.get():
            if not self.output_folder.get().strip():
                messagebox.showinfo(APP_NAME, "Choose an output folder.")
                return
            custom_folder = Path(self.output_folder.get()).expanduser().resolve()
            custom_folder.mkdir(parents=True, exist_ok=True)

        self.stop_event.clear()
        self.top_run.configure(state="disabled")
        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress["value"] = 0
        self.worker = threading.Thread(
            target=self._work,
            args=(list(self.files), custom_folder, self.preset.get(), self.grayscale.get(), self.open_folder.get()),
            daemon=True,
        )
        self.worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.status.set("Stopping...")

    def _work(self, files: list[Path], folder: Path | None, preset: str, grayscale: bool, open_when_done: bool) -> None:
        completed = 0
        folders: set[Path] = set()
        for index, source in enumerate(files):
            if self.stop_event.is_set():
                break
            row = self.rows[source]
            destination = output_path(source, folder)
            folders.add(destination.parent)

            def report(text: str) -> None:
                self.events.put(("status", row, text))
                self.events.put(("progress", ((index + 0.4) / len(files)) * 100, f"{source.name}: {text}"))

            try:
                label = compress_one(source, destination, preset, grayscale, self.stop_event, report)
                old_size = source.stat().st_size
                new_size = destination.stat().st_size
                saved = max(0, old_size - new_size)
                percent = saved / old_size * 100 if old_size else 0
                state = "Done" if new_size < old_size else "Already optimal"
                self.events.put(("done", row, state, human_size(new_size), f"{percent:.1f}%", label))
                completed += 1
            except InterruptedError:
                self.events.put(("status", row, "Cancelled"))
                break
            except Exception as exc:
                destination.unlink(missing_ok=True)
                self.events.put(("status", row, f"Error: {exc}"))

            self.events.put(("progress", ((index + 1) / len(files)) * 100, f"Processed {index + 1} of {len(files)}"))

        self.events.put(("finished", completed, len(files), self.stop_event.is_set(), sorted(folders), open_when_done))

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "status":
                    _, row, status = event
                    values = list(self.tree.item(row, "values"))
                    values[2] = status[:100]
                    self.tree.item(row, values=values)
                elif event[0] == "done":
                    _, row, status, result, saved, _label = event
                    values = list(self.tree.item(row, "values"))
                    values[2:] = (status, result, saved)
                    self.tree.item(row, values=values)
                elif event[0] == "progress":
                    _, value, text = event
                    self.progress["value"] = value
                    self.status.set(text)
                elif event[0] == "finished":
                    _, completed, total, cancelled, folders, open_when_done = event
                    self.top_run.configure(state="normal")
                    self.run_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status.set(f"Cancelled after {completed} of {total}." if cancelled else f"Finished {completed} of {total} PDF(s).")
                    if not cancelled:
                        self.progress["value"] = 100
                    if open_when_done and folders:
                        self._open_folder(folders[0])
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._drain_events)

    @staticmethod
    def _open_folder(folder: Path) -> None:
        try:
            if os.name == "nt":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception:
            pass

    def _close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "Compression is running. Stop and close?"):
                return
            self.stop_event.set()
        self.root.destroy()


def main() -> None:
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    PdfShrinkerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
