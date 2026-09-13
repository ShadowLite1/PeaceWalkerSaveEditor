from __future__ import annotations

import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

from pwmodel import Model, export_obj, load_mdp
from pwmotion import MotionArchive, load_mtar, quaternion_at, rotate_vector
from pwtexture import TexturePack, load_txp


class ModelViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MO_MODEL_VIEWER — Peace Walker")
        self.geometry("1200x760")
        self.minsize(800, 520)
        self.model: Model | None = None
        self.texture_pack: TexturePack | None = None
        self.motion: MotionArchive | None = None
        self.anim_frame = 0
        self.playing = False
        self.render_image = None
        self.texture_arrays = {}
        self.yaw, self.pitch, self.zoom = -0.6, -0.25, 1.0
        self.last_mouse = None
        self.wireframe = tk.BooleanVar(value=False)
        self.skeleton = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Open an extracted Peace Walker .mdp model.")
        self._build()

    def _build(self):
        bar = ttk.Frame(self, padding=6); bar.pack(fill="x")
        ttk.Button(bar, text="OPEN MDP", command=self.open_model).pack(side="left")
        ttk.Button(bar, text="OPEN TXP", command=self.open_texture).pack(side="left", padx=(5, 0))
        ttk.Button(bar, text="OPEN MTAR", command=self.open_motion).pack(side="left", padx=(5, 0))
        ttk.Button(bar, text="EXPORT OBJ", command=self.export).pack(side="left", padx=5)
        ttk.Button(bar, text="RESET VIEW", command=self.reset_view).pack(side="left")
        ttk.Checkbutton(bar, text="Wireframe", variable=self.wireframe, command=self.draw).pack(side="left", padx=(18, 4))
        ttk.Checkbutton(bar, text="Skeleton", variable=self.skeleton, command=self.draw).pack(side="left")
        self.anim_choice = ttk.Combobox(bar, width=12, state="readonly")
        self.anim_choice.pack(side="right", padx=5)
        self.anim_choice.bind("<<ComboboxSelected>>", self.change_animation)
        self.play_button = ttk.Button(bar, text="PLAY", command=self.toggle_play)
        self.play_button.pack(side="right")
        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True)
        side = ttk.Frame(body, padding=7); body.add(side, weight=0)
        ttk.Label(side, text="MESHES", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.meshes = tk.Listbox(side, width=28, selectmode="multiple", exportselection=False)
        self.meshes.pack(fill="both", expand=True, pady=5)
        self.meshes.bind("<<ListboxSelect>>", self._mesh_selection)
        self.info = ttk.Label(side, text="", justify="left"); self.info.pack(anchor="w")
        self.canvas = tk.Canvas(body, bg="#17191c", highlightthickness=0); body.add(self.canvas, weight=1)
        self.canvas.bind("<Configure>", lambda event: self.draw())
        self.canvas.bind("<ButtonPress-1>", lambda event: setattr(self, "last_mouse", (event.x, event.y)))
        self.canvas.bind("<B1-Motion>", self.rotate)
        self.canvas.bind("<MouseWheel>", self.wheel)
        ttk.Label(self, textvariable=self.status, padding=5).pack(fill="x")

    def open_model(self):
        name = filedialog.askopenfilename(filetypes=[("Peace Walker model", "*.mdp;*.MDP"), ("All files", "*.*")])
        if not name: return
        try:
            self.model = load_mdp(Path(name))
        except Exception as exc:
            messagebox.showerror("MO_MODEL_VIEWER", str(exc)); return
        self.meshes.delete(0, "end")
        for mesh in self.model.meshes: self.meshes.insert("end", mesh.name)
        self.meshes.selection_set(0, "end")
        self.info.configure(text=f"Bones: {len(self.model.bones)}\nMeshes: {len(self.model.meshes)}\nTriangles: {self.model.triangle_count:,}\nTextures: {len(self.model.texture_hashes)}")
        self.status.set(f"Loaded {Path(name).name}")
        self.texture_pack = None
        sibling = Path(name).with_suffix(".txp")
        if not sibling.exists(): sibling = Path(name).with_suffix(".TXP")
        if sibling.exists():
            try:
                self.texture_pack = load_txp(sibling)
                self.texture_arrays.clear()
                self.status.set(f"Loaded {Path(name).name} with {len(self.texture_pack.textures)} textures")
            except Exception:
                self.texture_pack = None
        self.reset_view()

    def open_texture(self):
        name = filedialog.askopenfilename(filetypes=[("Peace Walker textures", "*.txp;*.TXP"), ("All files", "*.*")])
        if not name: return
        try:
            self.texture_pack = load_txp(Path(name))
        except Exception as exc:
            messagebox.showerror("MO_MODEL_VIEWER", str(exc)); return
        self.status.set(f"Loaded {len(self.texture_pack.textures)} textures from {Path(name).name}")
        self.texture_arrays.clear()
        self.draw()

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
        self.anim_frame = 0
        self.draw()

    def toggle_play(self):
        if not self.current_animation(): return
        self.playing = not self.playing
        self.play_button.configure(text="PAUSE" if self.playing else "PLAY")
        if self.playing: self._tick()

    def _tick(self):
        if not self.playing: return
        animation = self.current_animation()
        if not animation:
            self.playing = False; return
        self.anim_frame = (self.anim_frame + 1) % max(1, animation.frames)
        self.status.set(f"Animation {animation.name} — frame {self.anim_frame + 1}/{animation.frames}")
        self.draw()
        self.after(33, self._tick)

    def _mesh_selection(self, event=None):
        selected = set(self.meshes.curselection())
        if self.model:
            for index, mesh in enumerate(self.model.meshes): mesh.visible = index in selected
        self.draw()

    def reset_view(self):
        self.yaw, self.pitch, self.zoom = -0.6, -0.25, 1.0
        self.draw()

    def rotate(self, event):
        if self.last_mouse:
            self.yaw += (event.x - self.last_mouse[0]) * 0.01
            self.pitch = max(-1.5, min(1.5, self.pitch + (event.y - self.last_mouse[1]) * 0.01))
        self.last_mouse = (event.x, event.y); self.draw()

    def wheel(self, event):
        self.zoom *= 1.12 if event.delta > 0 else 1 / 1.12
        self.zoom = max(.08, min(20, self.zoom)); self.draw()

    def _transform(self, point, center):
        x, y, z = (point[i] - center[i] for i in range(3))
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        x, z = x * cy + z * sy, -x * sy + z * cy
        y, z = y * cp - z * sp, y * sp + z * cp
        return x, -y, z

    def draw(self):
        self.canvas.delete("all")
        if not self.model: return
        visible = [m for m in self.model.meshes if m.visible]
        points = [v for m in visible for v in m.vertices]
        if not points: return
        mins = [min(p[i] for p in points) for i in range(3)]; maxs = [max(p[i] for p in points) for i in range(3)]
        center = [(mins[i] + maxs[i]) / 2 for i in range(3)]
        extent = max(maxs[i] - mins[i] for i in range(3)) or 1
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
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
                faces.append((depth, screen, [p[2] for p in tri], color, texture, uvs))
        if self.wireframe.get():
            faces.sort(key=lambda item: item[0])
            for _, screen, _, _, _, _ in faces:
                coords = [value for point in screen for value in point]
                self.canvas.create_polygon(coords, fill="", outline="#d5dde5", width=1)
        else:
            self.render_image = ImageTk.PhotoImage(self._rasterize(faces, width, height))
            self.canvas.create_image(0, 0, image=self.render_image, anchor="nw")
        if self.skeleton.get():
            posed = self._posed_bones()
            transformed = [self._transform(p, center) for p in posed]
            for index, bone in enumerate(self.model.bones):
                if bone.parent < 0 or bone.parent >= len(transformed): continue
                a, b = transformed[index], transformed[bone.parent]
                self.canvas.create_line(width/2+a[0]*scale, height/2+a[1]*scale,
                                        width/2+b[0]*scale, height/2+b[1]*scale,
                                        fill="#ff5b43", width=2)

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
                    tex = np.asarray(texture.convert("RGB")); self.texture_arrays[key] = tex
                u = (wa*uvs[0][0] + wb*uvs[1][0] + wc*uvs[2][0]) % 1.0
                v = (wa*uvs[0][1] + wb*uvs[1][1] + wc*uvs[2][1]) % 1.0
                tx = np.minimum(tex.shape[1]-1, (u*(tex.shape[1]-1)).astype(np.int32))
                ty = np.minimum(tex.shape[0]-1, (v*(tex.shape[0]-1)).astype(np.int32))
                sampled = tex[ty, tx]
                target[mask] = sampled[mask]
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


if __name__ == "__main__":
    ModelViewer().mainloop()
