from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pwarchive


APP_TITLE = "Peace Walker Archive Tool"


class ArchiveApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("820x620")
        self.minsize(700, 520)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self._build()
        self.after(100, self._poll_events)

    def _build(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")

        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text=APP_TITLE, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            root,
            text="Extract, inspect, and rebuild Peace Walker Master Collection PC archives.",
        ).pack(anchor="w", pady=(0, 12))

        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill="both", expand=True)
        self.extract_tab = ttk.Frame(self.tabs, padding=12)
        self.repack_tab = ttk.Frame(self.tabs, padding=12)
        self.inspect_tab = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(self.extract_tab, text="Extract")
        self.tabs.add(self.repack_tab, text="Repack")
        self.tabs.add(self.inspect_tab, text="Inspect")
        self._build_extract()
        self._build_repack()
        self._build_inspect()

        log_box = ttk.LabelFrame(root, text="Activity", padding=8)
        log_box.pack(fill="both", expand=False, pady=(12, 0))
        self.log = tk.Text(log_box, height=8, wrap="word", state="disabled", font=("Consolas", 9))
        scroll = ttk.Scrollbar(log_box, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.progress = ttk.Progressbar(root, mode="indeterminate")
        self.progress.pack(fill="x", pady=(8, 0))
        self.status = tk.StringVar(value="Ready")
        ttk.Label(root, textvariable=self.status).pack(anchor="w", pady=(4, 0))

    def _row(self, parent, row: int, label: str, variable: tk.StringVar, command, button="Browse…"):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(parent, text=button, command=command).grid(row=row, column=2, pady=5)
        parent.columnconfigure(1, weight=1)

    def _build_extract(self) -> None:
        self.archive_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.key_var = tk.StringVar()
        self.format_var = tk.StringVar(value="Automatic")
        self._row(self.extract_tab, 0, "Archive", self.archive_var, self._choose_archive)
        self._row(self.extract_tab, 1, "Output folder", self.output_var, self._choose_output)
        self._row(self.extract_tab, 2, "SLOT.KEY", self.key_var, self._choose_key, "Optional…")
        options = ttk.Frame(self.extract_tab)
        options.grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(options, text="Format").pack(side="left")
        ttk.Combobox(options, textvariable=self.format_var, state="readonly", width=18,
                     values=("Automatic", "PDT", "STAGEDAT", "SLOT", "DAR", "QAR", "XPR", "PC resource")).pack(side="left", padx=(8, 24))
        ttk.Label(
            self.extract_tab,
            text="Extraction creates a manifest beside the extracted files. Keep it for repacking.",
            wraplength=680,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=8)
        self.extract_button = ttk.Button(self.extract_tab, text="EXTRACT ARCHIVE", command=self._extract)
        self.extract_button.grid(row=5, column=0, columnspan=3, sticky="ew", pady=8)

    def _build_repack(self) -> None:
        self.folder_var = tk.StringVar()
        self.repack_output_var = tk.StringVar()
        self._row(self.repack_tab, 0, "Extracted folder", self.folder_var, self._choose_repack_folder)
        self._row(self.repack_tab, 1, "New archive", self.repack_output_var, self._choose_repack_output)
        ttk.Label(
            self.repack_tab,
            text=("The original archive is never overwritten automatically. SLOT and STAGEDAT replacements "
                  "must compress to fit their original allocation."),
            wraplength=680,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=10)
        self.repack_button = ttk.Button(self.repack_tab, text="BUILD NEW ARCHIVE", command=self._repack)
        self.repack_button.grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)

    def _build_inspect(self) -> None:
        self.inspect_var = tk.StringVar()
        self._row(self.inspect_tab, 0, "Archive", self.inspect_var, self._choose_inspect)
        self.info = tk.Text(self.inspect_tab, height=12, wrap="word", state="disabled", font=("Consolas", 10))
        self.info.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=10)
        self.inspect_tab.rowconfigure(1, weight=1)
        ttk.Button(self.inspect_tab, text="INSPECT FILE", command=self._inspect).grid(
            row=2, column=0, columnspan=3, sticky="ew"
        )

    def _choose_archive(self) -> None:
        path = filedialog.askopenfilename(title="Choose a Peace Walker archive", filetypes=(
            ("Peace Walker archives", "*.PDT *.DAT *.dar *.qar *.xpr"), ("All files", "*.*")))
        if path:
            self.archive_var.set(path)
            source = Path(path)
            self.output_var.set(str(source.with_name(source.stem + "_extracted")))
            if source.name.lower() == "002aba34.dat":
                candidate = source.with_suffix(".KEY")
                if candidate.exists(): self.key_var.set(str(candidate))

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(title="Choose extraction folder")
        if path: self.output_var.set(path)

    def _choose_key(self) -> None:
        path = filedialog.askopenfilename(title="Choose SLOT.KEY", filetypes=(("KEY files", "*.KEY"), ("All files", "*.*")))
        if path: self.key_var.set(path)

    def _choose_repack_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose an extracted archive folder")
        if path:
            self.folder_var.set(path)
            try:
                manifest = json.loads((Path(path) / pwarchive.MANIFEST).read_text(encoding="utf-8"))
                source = Path(manifest.get("source", "archive.bin"))
                self.repack_output_var.set(str(source.with_name(source.stem + "_mod" + source.suffix)))
            except Exception:
                pass

    def _choose_repack_output(self) -> None:
        path = filedialog.asksaveasfilename(title="Save rebuilt archive as", filetypes=(("All files", "*.*"),))
        if path: self.repack_output_var.set(path)

    def _choose_inspect(self) -> None:
        path = filedialog.askopenfilename(title="Choose a file", filetypes=(("All files", "*.*"),))
        if path: self.inspect_var.set(path)

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _detect_format(self, source: Path) -> str:
        selected = self.format_var.get()
        if selected != "Automatic":
            return selected.lower().replace("stagedat", "stage").replace(" ", "-")
        fmt, _ = pwarchive.classify_pc_resource(source)
        if fmt != "unknown": return fmt
        raise ValueError("This file is not a recognized Peace Walker PC resource.")

    def _run(self, label: str, task) -> None:
        if self.busy: return
        self.busy = True
        self.status.set(label)
        self.progress.start(12)
        self._append_log(label)
        def worker():
            try: self.events.put(("done", task()))
            except Exception as exc: self.events.put(("error", exc))
        threading.Thread(target=worker, daemon=True).start()

    def _poll_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    text = str(value)
                    self.status.set(text)
                    self._append_log(text)
                    continue
                self.busy = False
                self.progress.stop()
                if kind == "error":
                    self.status.set("Operation failed")
                    self._append_log(f"ERROR: {value}")
                    messagebox.showerror(APP_TITLE, str(value))
                else:
                    text = str(value or "Operation completed successfully.")
                    self.status.set(text)
                    self._append_log(text)
                    messagebox.showinfo(APP_TITLE, text)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _extract(self) -> None:
        source, output = Path(self.archive_var.get()), Path(self.output_var.get())
        if not source.is_file(): messagebox.showerror(APP_TITLE, "Choose an archive file first."); return
        if not str(output): messagebox.showerror(APP_TITLE, "Choose an output folder."); return
        try: fmt = self._detect_format(source)
        except ValueError as exc: messagebox.showerror(APP_TITLE, str(exc)); return
        def task():
            if fmt == "dar": pwarchive.extract_dar(source, output)
            elif fmt == "qar": pwarchive.extract_qar(source, output, 0x80)
            elif fmt == "pdt":
                pwarchive.extract_pdt(
                    source, output,
                    progress=lambda text: self.events.put(("progress", text)),
                )
            elif fmt == "stage":
                pwarchive.extract_stage(
                    source, output,
                    progress=lambda text: self.events.put(("progress", text)),
                )
            elif fmt == "slot":
                key = Path(self.key_var.get())
                if not key.is_file(): raise ValueError("SLOT extraction requires the matching SLOT.KEY file.")
                pwarchive.extract_slot(
                    source, key, output, 0x1000,
                    progress=lambda text: self.events.put(("progress", text)),
                )
            elif fmt == "pc-resource": pwarchive.extract_pc_resource(source, output)
            elif fmt == "xpr": pwarchive.extract_xpr2(source, output)
            return f"Extracted {source.name} to {output}"
        self._run(f"Extracting {source.name}…", task)

    def _repack(self) -> None:
        folder, output = Path(self.folder_var.get()), Path(self.repack_output_var.get())
        manifest_path = folder / pwarchive.MANIFEST
        if not manifest_path.is_file(): messagebox.showerror(APP_TITLE, f"The folder does not contain {pwarchive.MANIFEST}."); return
        if not str(output): messagebox.showerror(APP_TITLE, "Choose a new archive filename."); return
        def task():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            fmt = manifest["format"]
            if fmt == "dar": pwarchive.repack_dar(folder, output)
            elif fmt == "qar": pwarchive.repack_qar(folder, output)
            elif fmt == "stage": pwarchive.repack_fixed_pages(folder, output)
            elif fmt == "simple-pdt": pwarchive.repack_simple_pdt(folder, output)
            elif fmt == "slot": pwarchive.repack_slot(folder, output)
            else: raise ValueError(f"Unsupported manifest format: {fmt}")
            return f"Built {output.name} successfully."
        self._run("Building new archive…", task)

    def _inspect(self) -> None:
        path = Path(self.inspect_var.get())
        if not path.is_file(): messagebox.showerror(APP_TITLE, "Choose a file first."); return
        resolved = pwarchive.CORE_NAMES.get(path.name.lower(), path.name)
        _, description = pwarchive.classify_pc_resource(path)
        lines = [f"File: {path}", f"Recognized name: {resolved}",
                 f"Resource type: {description}", f"Size: {path.stat().st_size:,} bytes",
                 f"Name hash: {pwarchive.filename_hash(resolved):06X}"]
        if path.name.lower() in pwarchive.CORE_NAMES:
            lines.append("\nMaster Collection resource detected.")
            lines.append("The installed copy may still have the port's outer encryption layer.")
        self._set_text(self.info, "\n".join(lines))


if __name__ == "__main__":
    ArchiveApp().mainloop()
