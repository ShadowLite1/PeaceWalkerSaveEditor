from __future__ import annotations

import math
import re
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageChops, ImageTk

from pwmodel import Model, export_obj, load_mdp, save_mdp
from pwmotion import MotionArchive, load_mtar, quaternion_at, rotate_vector
from pwtexture import TexturePack, load_txp

try:
    from pwvulkan import VulkanRenderer
except Exception:
    VulkanRenderer = None


class ModelViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MO_MODEL_VIEWER — Peace Walker Model Editor")
        self.geometry("1200x760")
        self.minsize(800, 520)
        self.model: Model | None = None
        self.texture_pack: TexturePack | None = None
        self.motion: MotionArchive | None = None
        self.anim_frame = 0.0
        self.last_anim_tick = None
        self.playing = False
        self.render_image = None
        self.render_item = None
        self.texture_keys = []
        self.texture_arrays = {}
        self.tinted_textures = {}
        self.texture_preview_cache = {}
        self.texture_links = {}
        self.gpu_renderer = None
        self.gpu_failed = False
        self.undo_stack = []
        self.redo_stack = []
        self.yaw, self.pitch, self.zoom = -0.6, -0.25, 1.0
        self.last_mouse = None
        self.interacting = False
        self.draw_pending = False
        self.last_draw_started = 0.0
        self.wireframe = tk.BooleanVar(value=False)
        self.skeleton = tk.BooleanVar(value=False)
        self.join_horizontal_wrap = tk.BooleanVar(value=False)
        self.joined_texture_hashes = set()
        self.status = tk.StringVar(value="Open an extracted Peace Walker .mdp model.")
        self._build()

    def _build(self):
        bar = ttk.Frame(self, padding=6); bar.pack(fill="x")
        ttk.Button(bar, text="OPEN MDP", command=self.open_model).pack(side="left")
        ttk.Button(bar, text="OPEN TXP", command=self.open_texture).pack(side="left", padx=(5, 0))
        ttk.Button(bar, text="EXTRACT TEXTURE", command=self.extract_selected_texture).pack(side="left", padx=(5, 0))
        ttk.Button(bar, text="EXTRACT ALL", command=self.extract_all_textures).pack(side="left", padx=(5, 0))
        ttk.Button(bar, text="OPEN MTAR", command=self.open_motion).pack(side="left", padx=(5, 0))
        ttk.Button(bar, text="TEXTURES USED", command=self.show_texture_usage).pack(side="left", padx=(5, 0))
        ttk.Button(bar, text="EXPORT OBJ", command=self.export).pack(side="left", padx=5)
        ttk.Button(bar, text="SAVE MDP COPY", command=self.save_model).pack(side="left", padx=(0, 5))
        ttk.Button(bar, text="UNDO", command=self.undo).pack(side="left")
        ttk.Button(bar, text="REDO", command=self.redo).pack(side="left", padx=(5, 0))
        ttk.Button(bar, text="RESET VIEW", command=self.reset_view).pack(side="left")
        ttk.Checkbutton(bar, text="Wireframe", variable=self.wireframe, command=self.draw).pack(side="left", padx=(18, 4))
        ttk.Checkbutton(bar, text="Skeleton", variable=self.skeleton, command=self.draw).pack(side="left")
        ttk.Checkbutton(
            bar, text="Join selected texture", variable=self.join_horizontal_wrap,
            command=self._toggle_horizontal_wrap,
        ).pack(side="left", padx=(8, 0))
        self.anim_choice = ttk.Combobox(bar, width=12, state="readonly")
        self.anim_choice.pack(side="right", padx=5)
        self.anim_choice.bind("<<ComboboxSelected>>", self.change_animation)
        self.play_button = ttk.Button(bar, text="PLAY", command=self.toggle_play)
        self.play_button.pack(side="right")
        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True)
        side = ttk.Frame(body, padding=7); body.add(side, weight=0)
        ttk.Label(side, text="MESHES", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.meshes = tk.Listbox(side, width=28, selectmode="browse", exportselection=False)
        self.meshes.pack(fill="both", expand=True, pady=5)
        self.meshes.bind("<<ListboxSelect>>", self._mesh_selection)
        editor = ttk.LabelFrame(side, text="MESH TRANSFORM", padding=7)
        editor.pack(fill="x", pady=(0, 7))
        self.transform_vars = {
            key: tk.StringVar(value="1" if key == "scale" else "0")
            for key in ("x", "y", "z", "rx", "ry", "rz", "scale")
        }
        for row, (label, key) in enumerate((
            ("Move X", "x"), ("Move Y", "y"), ("Move Z", "z"),
            ("Rotate X°", "rx"), ("Rotate Y°", "ry"), ("Rotate Z°", "rz"),
            ("Scale", "scale"),
        )):
            ttk.Label(editor, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(editor, textvariable=self.transform_vars[key], width=12).grid(
                row=row, column=1, sticky="ew", padx=(6, 0), pady=2
            )
        ttk.Button(editor, text="APPLY TO SELECTED", command=self.apply_transform).grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(7, 0)
        )
        editor.columnconfigure(1, weight=1)
        self.info = ttk.Label(side, text="", justify="left"); self.info.pack(anchor="w")
        self.canvas = tk.Canvas(body, bg="#17191c", highlightthickness=0); body.add(self.canvas, weight=1)
        self.canvas.bind("<Configure>", lambda event: self.draw())
        self.canvas.bind("<ButtonPress-1>", self._start_rotate)
        self.canvas.bind("<B1-Motion>", self.rotate)
        self.canvas.bind("<ButtonRelease-1>", self._finish_rotate)
        self.canvas.bind("<MouseWheel>", self.wheel)
        ttk.Label(self, textvariable=self.status, padding=5).pack(fill="x")
        self.bind_all("<Control-z>", lambda _event: self.undo())
        self.bind_all("<Control-y>", lambda _event: self.redo())

    def open_model(self):
        name = filedialog.askopenfilename(filetypes=[("Peace Walker model", "*.mdp;*.MDP"), ("All files", "*.*")])
        if not name: return
        self.joined_texture_hashes.clear()
        self.join_horizontal_wrap.set(False)
        try:
            self.model = load_mdp(Path(name))
        except Exception as exc:
            self.model = None
            self.texture_pack = None
            self.meshes.delete(0, "end")
            self.info.configure(text="")
            self.canvas.delete("all")
            self.render_image = None
            self.render_item = None
            self.status.set(f"Could not display {Path(name).name}")
            messagebox.showerror("MO_MODEL_VIEWER", str(exc)); return
        self.meshes.delete(0, "end")
        self.undo_stack.clear(); self.redo_stack.clear()
        for mesh in self.model.meshes: self.meshes.insert("end", mesh.name)
        if self.model.meshes:
            self.meshes.selection_set(0)
            self.meshes.activate(0)
            self.model.meshes[0].visible = True
            for mesh in self.model.meshes[1:]:
                mesh.visible = False
        self.info.configure(text=f"Bones: {len(self.model.bones)}\nMeshes: {len(self.model.meshes)}\nTriangles: {self.model.triangle_count:,}\nTextures: {len(self.model.texture_hashes)}")
        self.status.set(f"Loaded {Path(name).name}")
        self._link_model_textures(Path(name))
        self.reset_view()

    def _link_model_textures(self, model_path: Path) -> None:
        self.texture_pack = None
        self.texture_links.clear()
        self.texture_arrays.clear()
        self.texture_preview_cache.clear()
        wanted = set(self.model.texture_hashes) if self.model else set()
        if not wanted:
            return
        def logical_stem(path: Path) -> str:
            return re.sub(r"^\d+_", "", path.stem.lower())

        candidates = [path for path in model_path.parent.iterdir()
                      if path.is_file() and path.suffix.lower() == ".txp"]
        # Archive extraction places corresponding MDP and TXP assets in
        # separate numbered sibling folders. Search that surrounding tree by
        # asset name, then validate candidates using the texture hashes below.
        search_root = model_path.parent.parent
        if search_root.is_dir():
            target_stem = logical_stem(model_path)
            for path in search_root.rglob("*"):
                if (path.is_file() and path.suffix.lower() == ".txp"
                        and logical_stem(path) == target_stem and path not in candidates):
                    candidates.append(path)
        candidates.sort(key=lambda path: (path.stem.lower() != model_path.stem.lower(), path.name.lower()))
        linked = {}
        packs_used = 0
        inferred_image = None
        inferred_source = None
        inferred_bundle = None
        inferred_bundle_source = None
        for candidate in candidates:
            try:
                pack = load_txp(candidate)
            except Exception:
                continue
            matches = {key: image for key, image in pack.textures.items() if key in wanted}
            if matches:
                linked.update(matches)
                for key in matches:
                    self.texture_links[key] = ("Exact match", candidate)
                packs_used += 1
            elif inferred_image is None and logical_stem(candidate) == logical_stem(model_path):
                raw_images = [image for key, image in pack.textures.items()
                              if key & 0xF0000000 == 0xF0000000]
                if raw_images:
                    inferred_image = raw_images[0]
                    inferred_source = candidate
                    if len(raw_images) == len(wanted):
                        inferred_bundle = raw_images
                        inferred_bundle_source = candidate
            if wanted.issubset(linked):
                break
        inferred = False
        if not linked and inferred_bundle is not None:
            for key, image in zip(sorted(wanted), inferred_bundle):
                linked[key] = image
                self.texture_links[key] = ("Unverified raw bundle", inferred_bundle_source)
            packs_used = 1
            inferred = True
        elif not linked and len(wanted) == 1 and inferred_image is not None:
            linked[next(iter(wanted))] = inferred_image
            self.texture_links[next(iter(wanted))] = ("Unverified raw guess", inferred_source)
            packs_used = 1
            inferred = True
        if linked:
            self.texture_pack = TexturePack(model_path, linked)
            if inferred:
                source = inferred_bundle_source or inferred_source
                self.status.set(
                    f"Loaded {model_path.name}; linked {len(linked)} inferred raw texture(s) "
                    f"from {source.name} — UNVERIFIED"
                )
            else:
                self.status.set(
                    f"Loaded {model_path.name}; linked {len(linked)}/{len(wanted)} textures from {packs_used} TXP file(s)"
                )
        elif candidates:
            self.status.set(f"Loaded {model_path.name}; no matching texture hashes found in {len(candidates)} nearby TXP file(s)")

    def open_texture(self):
        name = filedialog.askopenfilename(filetypes=[("Peace Walker textures", "*.txp;*.TXP"), ("All files", "*.*")])
        if not name: return
        try:
            opened_pack = load_txp(Path(name))
        except Exception as exc:
            messagebox.showerror("MO_MODEL_VIEWER", str(exc)); return
        if self.model:
            existing = dict(self.texture_pack.textures) if self.texture_pack else {}
            matches = {key: image for key, image in opened_pack.textures.items()
                       if key in self.model.texture_hashes}
            existing.update(matches)
            for key in matches:
                self.texture_links[key] = ("Exact match", Path(name))
            self.texture_pack = TexturePack(Path(name), existing)
            self.status.set(
                f"Linked {len(matches)} matching textures from {Path(name).name} "
                f"({len(existing)}/{len(self.model.texture_hashes)} total)"
            )
            self.texture_arrays.clear()
            self.draw()
            return
        self.texture_pack = opened_pack
        self.joined_texture_hashes.clear()
        self.join_horizontal_wrap.set(False)
        self.status.set(f"Loaded {len(self.texture_pack.textures)} textures from {Path(name).name}")
        self.texture_arrays.clear()
        self.texture_preview_cache.clear()
        if not self.model:
            self.texture_keys = list(self.texture_pack.textures)
            self.meshes.delete(0, "end")
            for index, texture_hash in enumerate(self.texture_keys):
                image = self.texture_pack.textures[texture_hash]
                label = "Raw candidate" if texture_hash & 0xF0000000 == 0xF0000000 else f"Texture {index + 1:03d}"
                self.meshes.insert("end", f"{label}  {texture_hash:08X}  {image.width}x{image.height}")
            if self.texture_keys:
                self.meshes.selection_set(0)
                self.meshes.activate(0)
            self.info.configure(text=f"Textures: {len(self.texture_keys)}\nSelect one to preview")
        self.draw()

    def show_texture_usage(self):
        if not self.model:
            messagebox.showinfo("Textures used", "Open an MDP model first.")
            return
        window = tk.Toplevel(self)
        window.title(f"Textures Used — {self.model.path.name}")
        window.geometry("1040x420")
        window.minsize(720, 260)
        ttk.Label(
            window,
            text="Texture hashes stored in the MDP are authoritative. Raw guesses are not confirmed matches.",
            padding=(10, 10, 10, 6),
        ).pack(fill="x")
        columns = ("mesh", "hash", "color", "status", "source")
        table = ttk.Treeview(window, columns=columns, show="headings", selectmode="browse")
        headings = {
            "mesh": "Mesh", "hash": "Texture hash", "color": "Material RGBA",
            "status": "Link status", "source": "TXP source",
        }
        for column, heading in headings.items():
            table.heading(column, text=heading)
        table.column("mesh", width=130, stretch=False)
        table.column("hash", width=110, stretch=False)
        table.column("color", width=130, stretch=False)
        table.column("status", width=150, stretch=False)
        table.column("source", width=480, stretch=True)
        seen = set()
        for mesh in self.model.meshes:
            for index, texture_hash in enumerate(mesh.materials):
                color = (mesh.material_colors[index] if index < len(mesh.material_colors)
                         else (255, 255, 255, 255))
                signature = (mesh.name, texture_hash, color)
                if signature in seen:
                    continue
                seen.add(signature)
                status, source = self.texture_links.get(texture_hash, ("Missing", None))
                table.insert("", "end", values=(
                    mesh.name, f"{texture_hash:08X}", str(color), status,
                    str(source) if source else "",
                ))
        table.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        ttk.Button(window, text="CLOSE", command=window.destroy).pack(pady=(0, 10))

    def _export_texture_image(self, texture_hash: int) -> Image.Image:
        image = self.texture_pack.textures[texture_hash]
        if texture_hash in self.joined_texture_hashes:
            return ImageChops.offset(image, image.width // 2, 0)
        return image

    def extract_selected_texture(self):
        if not self.texture_pack or not self.texture_keys or self.model:
            messagebox.showinfo("Extract texture", "Open a TXP texture archive first.")
            return
        selected = self.meshes.curselection()
        index = selected[0] if selected else 0
        if index >= len(self.texture_keys):
            return
        texture_hash = self.texture_keys[index]
        name = filedialog.asksaveasfilename(
            title="Extract selected texture",
            defaultextension=".png",
            initialfile=f"{self.texture_pack.path.stem}_{index + 1:03d}_{texture_hash:08X}.png",
            filetypes=[("PNG image", "*.png")],
        )
        if not name:
            return
        try:
            self._export_texture_image(texture_hash).save(name, "PNG")
        except Exception as exc:
            messagebox.showerror("Extract texture", str(exc))
            return
        self.status.set(f"Extracted texture {texture_hash:08X} to {Path(name).name}")

    def extract_all_textures(self):
        if not self.texture_pack or not self.texture_keys or self.model:
            messagebox.showinfo("Extract textures", "Open a TXP texture archive first.")
            return
        folder = filedialog.askdirectory(title="Choose a folder for extracted textures")
        if not folder:
            return
        destination = Path(folder)
        try:
            for index, texture_hash in enumerate(self.texture_keys, 1):
                output = destination / f"{self.texture_pack.path.stem}_{index:03d}_{texture_hash:08X}.png"
                self._export_texture_image(texture_hash).save(output, "PNG")
        except Exception as exc:
            messagebox.showerror("Extract textures", str(exc))
            return
        self.status.set(f"Extracted {len(self.texture_keys)} textures to {destination}")
        messagebox.showinfo(
            "Extract textures",
            f"Extracted {len(self.texture_keys)} PNG textures to:\n{destination}",
        )

    def open_motion(self):
        name = filedialog.askopenfilename(filetypes=[("Peace Walker animations", "*.mtar;*.MTAR"), ("All files", "*.*")])
        if not name: return
        try:
            self.motion = load_mtar(Path(name))
        except Exception as exc:
            messagebox.showerror("MO_MODEL_VIEWER", str(exc)); return
        self.anim_choice["values"] = [a.name for a in self.motion.animations]
        self.anim_choice.current(0)
        self.anim_frame = 0
        self.skeleton.set(True)
        self.status.set(f"Loaded {len(self.motion.animations)} animations from {Path(name).name}")
        self.draw()

    def current_animation(self):
        if not self.motion or not self.motion.animations: return None
        index = max(0, self.anim_choice.current())
        return self.motion.animations[index]

    def change_animation(self, event=None):
        self.anim_frame = 0.0
        self.last_anim_tick = time.perf_counter()
        self.draw()

    def toggle_play(self):
        if not self.current_animation(): return
        self.playing = not self.playing
        self.play_button.configure(text="PAUSE" if self.playing else "PLAY")
        if self.playing:
            self.last_anim_tick = time.perf_counter()
            self._tick()

    def _tick(self):
        if not self.playing: return
        animation = self.current_animation()
        if not animation:
            self.playing = False; return
        now = time.perf_counter()
        elapsed = min(0.1, now - (self.last_anim_tick or now))
        self.last_anim_tick = now
        # Peace Walker motion data is authored at 30 frames per second. Render
        # at 60 Hz while advancing from elapsed time so playback speed stays correct.
        self.anim_frame = (self.anim_frame + elapsed * 30.0) % max(1, animation.frames)
        self.status.set(f"Animation {animation.name} — frame {int(self.anim_frame) + 1}/{animation.frames} — 60 FPS")
        self.draw()
        self.after(16, self._tick)

    def _mesh_selection(self, event=None):
        selected = set(self.meshes.curselection())
        if self.model:
            for index, mesh in enumerate(self.model.meshes): mesh.visible = index in selected
        elif selected and self.texture_keys:
            index = next(iter(selected))
            if index < len(self.texture_keys):
                self.join_horizontal_wrap.set(
                    self.texture_keys[index] in self.joined_texture_hashes
                )
        self.draw()

    def _toggle_horizontal_wrap(self):
        if self.model or not self.texture_keys:
            self.draw()
            return
        selected = self.meshes.curselection()
        index = selected[0] if selected else 0
        if index >= len(self.texture_keys):
            return
        texture_hash = self.texture_keys[index]
        if self.join_horizontal_wrap.get():
            self.joined_texture_hashes.add(texture_hash)
        else:
            self.joined_texture_hashes.discard(texture_hash)
        self.draw()

    def _snapshot_vertices(self):
        if not self.model: return []
        return [[tuple(vertex) for vertex in mesh.vertices] for mesh in self.model.meshes]

    def _restore_vertices(self, snapshot):
        if not self.model or len(snapshot) != len(self.model.meshes): return
        for mesh, vertices in zip(self.model.meshes, snapshot):
            mesh.vertices = [tuple(vertex) for vertex in vertices]
        self.draw()

    def apply_transform(self):
        if not self.model: return
        selected = list(self.meshes.curselection())
        if not selected:
            messagebox.showinfo("MO_MODEL_EDITOR", "Select at least one mesh to transform.")
            return
        try:
            tx, ty, tz = (float(self.transform_vars[key].get()) for key in ("x", "y", "z"))
            rx, ry, rz = (math.radians(float(self.transform_vars[key].get())) for key in ("rx", "ry", "rz"))
            scale = float(self.transform_vars["scale"].get())
            if not math.isfinite(scale) or scale <= 0:
                raise ValueError("Scale must be a positive number")
            if not all(math.isfinite(value) for value in (tx, ty, tz, rx, ry, rz)):
                raise ValueError("Transform values must be finite numbers")
        except ValueError as exc:
            messagebox.showerror("Invalid transform", str(exc)); return
        self.undo_stack.append(self._snapshot_vertices())
        if len(self.undo_stack) > 50: self.undo_stack.pop(0)
        self.redo_stack.clear()
        cxr, sxr = math.cos(rx), math.sin(rx)
        cyr, syr = math.cos(ry), math.sin(ry)
        czr, szr = math.cos(rz), math.sin(rz)
        for index in selected:
            mesh = self.model.meshes[index]
            if not mesh.vertices: continue
            center = tuple(sum(v[axis] for v in mesh.vertices) / len(mesh.vertices) for axis in range(3))
            transformed = []
            for vertex in mesh.vertices:
                x, y, z = ((vertex[axis] - center[axis]) * scale for axis in range(3))
                y, z = y * cxr - z * sxr, y * sxr + z * cxr
                x, z = x * cyr + z * syr, -x * syr + z * cyr
                x, y = x * czr - y * szr, x * szr + y * czr
                transformed.append((x + center[0] + tx, y + center[1] + ty, z + center[2] + tz))
            mesh.vertices = transformed
        self.status.set(f"Transformed {len(selected)} mesh(es). Save an MDP copy to write the edit.")
        self.draw()

    def undo(self):
        if not self.model or not self.undo_stack: return
        self.redo_stack.append(self._snapshot_vertices())
        self._restore_vertices(self.undo_stack.pop())
        self.status.set("Undid mesh edit")

    def redo(self):
        if not self.model or not self.redo_stack: return
        self.undo_stack.append(self._snapshot_vertices())
        self._restore_vertices(self.redo_stack.pop())
        self.status.set("Redid mesh edit")

    def reset_view(self):
        self.yaw, self.pitch, self.zoom = -0.6, -0.25, 1.0
        self.draw()

    def rotate(self, event):
        if self.last_mouse:
            self.yaw += (event.x - self.last_mouse[0]) * 0.01
            self.pitch = max(-1.5, min(1.5, self.pitch + (event.y - self.last_mouse[1]) * 0.01))
        self.last_mouse = (event.x, event.y)
        self._request_draw()

    def _start_rotate(self, event):
        self.last_mouse = (event.x, event.y)
        self.interacting = True

    def _finish_rotate(self, event):
        self.last_mouse = None
        self.interacting = False
        self.draw_pending = False
        self.draw()

    def _request_draw(self):
        if self.draw_pending:
            return
        elapsed = time.perf_counter() - self.last_draw_started
        delay = max(0, round((1.0 / 60.0 - elapsed) * 1000))
        self.draw_pending = True
        self.after(delay, self._scheduled_draw)

    def _scheduled_draw(self):
        if not self.draw_pending:
            return
        self.draw_pending = False
        self.last_draw_started = time.perf_counter()
        self.draw()

    def wheel(self, event):
        self.zoom *= 1.12 if event.delta > 0 else 1 / 1.12
        self.zoom = max(.08, min(20, self.zoom))
        self._request_draw()

    def _transform(self, point, center):
        x, y, z = (point[i] - center[i] for i in range(3))
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        x, z = x * cy + z * sy, -x * sy + z * cy
        y, z = y * cp - z * sp, y * sp + z * cp
        return x, -y, z

    def draw(self):
        if not self.model or self.wireframe.get():
            self.canvas.delete("all")
            self.render_item = None
        else:
            self.canvas.delete("overlay")
        if not self.model:
            if not self.texture_pack or not self.texture_keys:
                return
            selected = self.meshes.curselection()
            index = selected[0] if selected else 0
            if index >= len(self.texture_keys):
                index = 0
            texture_hash = self.texture_keys[index]
            source = self.texture_pack.textures[texture_hash]
            label = "Raw candidate" if texture_hash & 0xF0000000 == 0xF0000000 else f"Texture {index + 1}/{len(self.texture_keys)}"
            width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
            margin = 48
            scale = min((width - margin * 2) / source.width, (height - margin * 2) / source.height)
            scale = max(0.01, scale)
            preview_size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
            joined = texture_hash in self.joined_texture_hashes
            cache_key = (texture_hash, preview_size, joined)
            preview = self.texture_preview_cache.get(cache_key)
            if preview is None:
                preview = source.resize(preview_size, Image.Resampling.NEAREST)
                if joined:
                    preview = ImageChops.offset(preview, preview.width // 2, 0)
                # Keep the cache bounded when resizing the window repeatedly.
                if len(self.texture_preview_cache) >= 96:
                    self.texture_preview_cache.clear()
                self.texture_preview_cache[cache_key] = preview
            self.render_image = ImageTk.PhotoImage(preview)
            self.canvas.create_image(width / 2, height / 2, image=self.render_image, anchor="center")
            self.canvas.create_text(
                width / 2, 20,
                text=f"{label}   {texture_hash:08X}   {source.width}x{source.height}",
                fill="#d5dde5", font=("Segoe UI", 11), anchor="n"
            )
            return
        visible = [m for m in self.model.meshes if m.visible]
        points = [v for m in visible for v in m.vertices]
        if not points: return
        mins = [min(p[i] for p in points) for i in range(3)]; maxs = [max(p[i] for p in points) for i in range(3)]
        center = [(mins[i] + maxs[i]) / 2 for i in range(3)]
        extent = max(maxs[i] - mins[i] for i in range(3)) or 1
        canvas_width, canvas_height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        reduced_render = (self.interacting or self.playing) and not self.wireframe.get()
        quality = (0.25 if self.interacting else 0.5) if reduced_render else 1.0
        width, height = max(1, round(canvas_width * quality)), max(1, round(canvas_height * quality))
        scale = min(width, height) * .72 / extent * self.zoom
        faces = []
        palette = ("#8199ad", "#9a8472", "#758f7c", "#8c7897", "#9b956e")
        for mesh_index, mesh in enumerate(visible):
            transformed = [self._transform(v, center) for v in mesh.vertices]
            for material_index, triangle in enumerate(mesh.triangles):
                try: tri = [transformed[i] for i in triangle]
                except IndexError: continue
                screen = [(width / 2 + p[0] * scale, height / 2 + p[1] * scale) for p in tri]
                depth = sum(p[2] for p in tri) / 3
                color = palette[mesh_index % len(palette)]
                texture = None
                uvs = [mesh.uvs[i] for i in triangle]
                if self.texture_pack and material_index < len(mesh.materials):
                    texture = self.texture_pack.textures.get(mesh.materials[material_index])
                    if texture is not None and texture.info.get("raw_indexed_mask"):
                        rgba = (mesh.material_colors[material_index]
                                if material_index < len(mesh.material_colors)
                                else (255, 255, 255, 255))
                        tint_key = (id(texture), rgba)
                        tinted = self.tinted_textures.get(tint_key)
                        if tinted is None:
                            alpha = texture.getchannel("A")
                            if rgba[3] != 255:
                                alpha = alpha.point(lambda value: value * rgba[3] // 255)
                            tinted = Image.new("RGBA", texture.size, rgba[:3] + (0,))
                            tinted.putalpha(alpha)
                            self.tinted_textures[tint_key] = tinted
                        texture = tinted
                faces.append((depth, screen, [p[2] for p in tri], color, texture, uvs))
        if self.wireframe.get():
            faces.sort(key=lambda item: item[0])
            for _, screen, _, _, _, _ in faces:
                coords = [value for point in screen for value in point]
                self.canvas.create_polygon(coords, fill="", outline="#d5dde5", width=1)
        else:
            rendered = None
            if not self.gpu_failed and VulkanRenderer is not None:
                try:
                    if self.gpu_renderer is None:
                        self.gpu_renderer = VulkanRenderer()
                        self.status.set(f"{self.status.get()} — Vulkan: {self.gpu_renderer.name}")
                    rendered = self.gpu_renderer.render(faces, width, height)
                except Exception as exc:
                    self.gpu_failed = True
                    self.status.set(f"Vulkan renderer unavailable; using CPU fallback: {exc}")
            if rendered is None:
                rendered = self._rasterize(faces, width, height)
            if reduced_render:
                rendered = rendered.resize((canvas_width, canvas_height), Image.Resampling.NEAREST)
            if (self.render_image is not None and self.render_item is not None
                    and self.render_image.width() == rendered.width
                    and self.render_image.height() == rendered.height):
                self.render_image.paste(rendered)
            else:
                self.render_image = ImageTk.PhotoImage(rendered)
                if self.render_item is None:
                    self.render_item = self.canvas.create_image(
                        0, 0, image=self.render_image, anchor="nw", tags=("model_frame",)
                    )
                else:
                    self.canvas.itemconfigure(self.render_item, image=self.render_image)
        if self.skeleton.get():
            posed = self._posed_bones()
            transformed = [self._transform(p, center) for p in posed]
            for index, bone in enumerate(self.model.bones):
                if bone.parent < 0 or bone.parent >= len(transformed): continue
                a, b = transformed[index], transformed[bone.parent]
                q = 1.0 / quality
                self.canvas.create_line((width/2+a[0]*scale)*q, (height/2+a[1]*scale)*q,
                                        (width/2+b[0]*scale)*q, (height/2+b[1]*scale)*q,
                                        fill="#ff5b43", width=2, tags=("overlay",))

    def _rasterize(self, faces, width, height):
        image = np.empty((height, width, 3), dtype=np.uint8)
        image[:] = (23, 25, 28)
        zbuffer = np.full((height, width), -np.inf, dtype=np.float32)
        for _, screen, depths, color, texture, uvs in faces:
            x0 = max(0, int(math.floor(min(p[0] for p in screen))))
            x1 = min(width - 1, int(math.ceil(max(p[0] for p in screen))))
            y0 = max(0, int(math.floor(min(p[1] for p in screen))))
            y1 = min(height - 1, int(math.ceil(max(p[1] for p in screen))))
            if x1 < x0 or y1 < y0: continue
            ax, ay = screen[0]; bx, by = screen[1]; cx, cy = screen[2]
            denom = (by - cy)*(ax - cx) + (cx - bx)*(ay - cy)
            if abs(denom) < 1e-7: continue
            yy, xx = np.mgrid[y0:y1+1, x0:x1+1]
            wa = ((by-cy)*(xx-cx) + (cx-bx)*(yy-cy)) / denom
            wb = ((cy-ay)*(xx-cx) + (ax-cx)*(yy-cy)) / denom
            wc = 1.0 - wa - wb
            inside = (wa >= -1e-5) & (wb >= -1e-5) & (wc >= -1e-5)
            depth = wa*depths[0] + wb*depths[1] + wc*depths[2]
            target_z = zbuffer[y0:y1+1, x0:x1+1]
            mask = inside & (depth > target_z)
            if not mask.any(): continue
            target = image[y0:y1+1, x0:x1+1]
            if texture:
                key = id(texture)
                tex = self.texture_arrays.get(key)
                if tex is None:
                    tex = np.asarray(texture.convert("RGBA")); self.texture_arrays[key] = tex
                u = (wa*uvs[0][0] + wb*uvs[1][0] + wc*uvs[2][0]) % 1.0
                v = (wa*uvs[0][1] + wb*uvs[1][1] + wc*uvs[2][1]) % 1.0
                tx = np.minimum(tex.shape[1]-1, (u*(tex.shape[1]-1)).astype(np.int32))
                ty = np.minimum(tex.shape[0]-1, (v*(tex.shape[0]-1)).astype(np.int32))
                sampled = tex[ty, tx]
                mask &= sampled[..., 3] > 0
                target[mask] = sampled[..., :3][mask]
            else:
                rgb = tuple(int(color[q:q+2], 16) for q in (1, 3, 5))
                target[mask] = rgb
            target_z[mask] = depth[mask]
        return Image.fromarray(image, "RGB")

    def _posed_bones(self):
        positions = [bone.position for bone in self.model.bones]
        animation = self.current_animation()
        if not animation: return positions
        motions = {joint.bone_hash: joint for joint in animation.joints}
        posed = [None] * len(positions)
        visiting = set()
        def solve(index):
            if posed[index] is not None: return posed[index]
            if index in visiting: return positions[index]
            visiting.add(index)
            bone = self.model.bones[index]
            parent = bone.parent
            if parent < 0 or parent >= len(positions):
                value = positions[index]
            else:
                parent_pos = solve(parent)
                local = tuple(positions[index][q] - positions[parent][q] for q in range(3))
                joint = motions.get(int(bone.name, 16))
                quat = quaternion_at(joint.rotations, self.anim_frame) if joint else (0, 0, 0, 1)
                local = rotate_vector(local, quat)
                value = tuple(parent_pos[q] + local[q] for q in range(3))
            visiting.discard(index); posed[index] = value; return value
        return [solve(i) for i in range(len(positions))]

    def export(self):
        if not self.model: return
        name = filedialog.asksaveasfilename(defaultextension=".obj", filetypes=[("Wavefront OBJ", "*.obj")])
        if name:
            export_obj(self.model, Path(name)); self.status.set(f"Exported {Path(name).name}")

    def save_model(self):
        if not self.model: return
        suffix = self.model.path.suffix or ".mdp"
        name = filedialog.asksaveasfilename(
            title="Save edited Peace Walker model copy",
            initialdir=str(self.model.path.parent),
            initialfile=f"{self.model.path.stem}_edited{suffix}",
            defaultextension=suffix,
            filetypes=[("Peace Walker model", "*.mdp;*.MDP"), ("All files", "*.*")],
        )
        if not name: return
        destination = Path(name)
        if destination.resolve() == self.model.path.resolve():
            messagebox.showerror("MO_MODEL_EDITOR", "Save to a new file so the original model remains intact.")
            return
        try:
            save_mdp(self.model, destination)
        except Exception as exc:
            messagebox.showerror("Cannot save model", str(exc)); return
        self.status.set(f"Saved edited model copy: {destination.name}")


if __name__ == "__main__":
    ModelViewer().mainloop()
