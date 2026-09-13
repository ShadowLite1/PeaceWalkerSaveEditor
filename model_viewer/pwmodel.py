from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


@dataclass
class Bone:
    name: str
    parent: int
    position: tuple[float, float, float]


@dataclass
class Mesh:
    name: str
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    uvs: list[tuple[float, float]] = field(default_factory=list)
    triangles: list[tuple[int, int, int]] = field(default_factory=list)
    materials: list[int] = field(default_factory=list)
    visible: bool = True


@dataclass
class Model:
    path: Path
    bones: list[Bone]
    meshes: list[Mesh]
    texture_hashes: set[int]

    @property
    def triangle_count(self) -> int:
        return sum(len(mesh.triangles) for mesh in self.meshes)


VERTEX_LAYOUTS = {
    0x01: (18, 2, 6, 12, 2),
    0x02: (20, 4, 8, 14, 4),
    0x03: (24, 8, 12, 18, 8),
    0x04: (20, 0, 8, 14, 0),
    0x09: (16, 2, 6, 10, 2),
    0x0A: (18, 4, 8, 12, 4),
    0x0B: (22, 8, 12, 16, 8),
    0x0C: (18, 2, 8, 12, 2),
    0x0D: (20, 4, 10, 14, 4),
    0x0E: (24, 8, 14, 18, 8),
}


def _check_range(data: bytes, offset: int, size: int, label: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError(f"{label} points outside the MDP file")


def load_mdp(path: Path) -> Model:
    data = path.read_bytes()
    if len(data) < 80 or data[:4] not in (b"MDP ", b"MDPX"):
        raise ValueError("Not a Peace Walker MDP model")
    pc_layout = data[:4] == b"MDPX"
    if pc_layout:
        num_bones, num_groups, num_meshes = struct.unpack_from("<3I", data, 4)
        model_hash = u32(data, 16)
        bone_offset, group_offset, mesh_offset = struct.unpack_from("<3Q", data, 24)
        mesh_stride, face_stride, header_max_offset = 112, 24, 80
    else:
        (_, num_bones, num_groups, num_meshes, model_hash, bone_offset,
         group_offset, mesh_offset, unknown, internal, pad1, pad2) = struct.unpack_from("<12I", data, 0)
        mesh_stride, face_stride, header_max_offset = 80, 12, 48
    if num_bones > 4096 or num_meshes > 65536:
        raise ValueError("Implausible MDP counts")
    _check_range(data, bone_offset, num_bones * 80, "Bone table")
    _check_range(data, mesh_offset, num_meshes * mesh_stride, "Mesh table")

    bones = []
    for index in range(num_bones):
        offset = bone_offset + index * 80
        name_hash, _, parent, _ = struct.unpack_from("<IIiI", data, offset)
        world = struct.unpack_from("<4f", data, offset + 32)
        bones.append(Bone(f"{name_hash:08x}", parent, world[:3]))

    header_max_x = struct.unpack_from("<f", data, header_max_offset)[0]
    scale = 38000.0 / header_max_x + 1.0 if abs(header_max_x) > 1e-8 else 1.0
    texture_hashes: set[int] = set()
    meshes = []
    for mesh_index in range(num_meshes):
        offset = mesh_offset + mesh_index * mesh_stride
        if pc_layout:
            name_hash, flags, face_count = struct.unpack_from("<3I", data, offset)
            face_offset, vertex_offset, skin_offset = struct.unpack_from("<3Q", data, offset + 16)
            vertex_count = u32(data, offset + 40)
        else:
            (name_hash, flags, face_count, face_offset, vertex_offset, skin_offset,
             vertex_count, _) = struct.unpack_from("<8I", data, offset)
        vertex_type = flags & 0x0F
        if not vertex_offset:
            continue
        layout = VERTEX_LAYOUTS.get(vertex_type)
        if layout is None:
            raise ValueError(f"Mesh {mesh_index} uses unsupported vertex type 0x{vertex_type:X}")
        stride, uv_offset, normal_offset, position_offset, weight_count = layout
        _check_range(data, vertex_offset, vertex_count * stride, f"Mesh {mesh_index} vertex buffer")

        skin_bones = []
        if weight_count and skin_offset:
            _check_range(data, skin_offset, 4, f"Mesh {mesh_index} skin")
            skin_count = struct.unpack_from("<H", data, skin_offset + 2)[0]
            _check_range(data, skin_offset + 4, skin_count, f"Mesh {mesh_index} skin bone list")
            skin_bones = list(data[skin_offset + 4:skin_offset + 4 + skin_count])

        vertices, uvs = [], []
        for vertex_index in range(vertex_count):
            base = vertex_offset + vertex_index * stride
            u, v = struct.unpack_from("<HH", data, base + uv_offset)
            x, y, z = struct.unpack_from("<hhh", data, base + position_offset)
            position = [x / scale, y / scale, z / scale]
            if weight_count and skin_bones:
                weights = data[base:base + weight_count]
                total = sum(weights) or 128
                translation = [0.0, 0.0, 0.0]
                for weight_index, weight in enumerate(weights):
                    if weight_index >= len(skin_bones) or skin_bones[weight_index] >= len(bones):
                        continue
                    bone_position = bones[skin_bones[weight_index]].position
                    factor = weight / total
                    for axis in range(3):
                        translation[axis] += bone_position[axis] * factor
                position = [position[axis] + translation[axis] for axis in range(3)]
            vertices.append(tuple(position))
            uvs.append((u / 4096.0, 1.0 - v / 4096.0))

        triangles, materials = [], []
        _check_range(data, face_offset, face_count * face_stride, f"Mesh {mesh_index} face table")
        cursor = 0
        for face_index in range(face_count):
            face = face_offset + face_index * face_stride
            if pc_layout:
                _, strip_size, _, face_buffer_offset, material_offset = struct.unpack_from("<HHIQQ", data, face)
                if face_buffer_offset >= vertex_offset:
                    cursor = (face_buffer_offset - vertex_offset) // stride
            else:
                _, strip_size, face_buffer_offset, material_offset = struct.unpack_from("<HHII", data, face)
            if material_offset and material_offset + 24 <= len(data):
                texture_hash = u32(data, material_offset)
                texture_hashes.add(texture_hash)
            else:
                texture_hash = 0
            for strip_index in range(max(0, strip_size - 2)):
                a, b, c = cursor + strip_index, cursor + strip_index + 1, cursor + strip_index + 2
                if strip_index & 1:
                    b, c = c, b
                if c < len(vertices):
                    triangles.append((a, b, c))
                    materials.append(texture_hash)
            cursor += strip_size
        meshes.append(Mesh(f"{name_hash:08x}", vertices, uvs, triangles, materials))
    if not meshes:
        if pc_layout:
            raise ValueError(
                "This is a metadata-only MDPX copy with no vertex buffers. "
                "Open another extracted copy of the same model hash."
            )
        raise ValueError("The MDP has no conventional vertex buffers to display")
    return Model(path, bones, meshes, texture_hashes)


def export_obj(model: Model, destination: Path) -> None:
    lines = [f"# Exported from {model.path.name} by MO_MODEL_VIEWER"]
    vertex_base = 1
    for mesh in model.meshes:
        if not mesh.visible:
            continue
        lines.append(f"o {mesh.name}")
        lines.extend(f"v {x:.7g} {y:.7g} {z:.7g}" for x, y, z in mesh.vertices)
        lines.extend(f"vt {u:.7g} {v:.7g}" for u, v in mesh.uvs)
        for a, b, c in mesh.triangles:
            a += vertex_base; b += vertex_base; c += vertex_base
            lines.append(f"f {a}/{a} {b}/{b} {c}/{c}")
        vertex_base += len(mesh.vertices)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
