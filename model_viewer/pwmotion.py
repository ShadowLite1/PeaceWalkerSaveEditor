from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path


class BitReader:
    def __init__(self, data: bytes):
        self.value = int.from_bytes(data, "little")
        self.position = 0

    def read(self, count: int) -> int:
        value = (self.value >> self.position) & ((1 << count) - 1)
        self.position += count
        return value


@dataclass
class JointMotion:
    bone_hash: int
    rotations: list[tuple[int, tuple[float, float, float, float]]] = field(default_factory=list)


@dataclass
class Animation:
    name: str
    frames: int
    joints: list[JointMotion]


@dataclass
class MotionArchive:
    path: Path
    animations: list[Animation]


def _rotations(data: bytes, bits: int, frames: int) -> list[tuple[int, tuple[float, float, float, float]]]:
    reader, frame, result = BitReader(data), 0, []
    required = 8 + bits * 3 + 3
    while frame < frames and reader.position + required <= len(data) * 8:
        frame += reader.read(8)
        theta = reader.read(bits) * (2.0 ** -bits) * math.pi
        x, y = reader.read(bits) * (2.0 ** -bits), reader.read(bits) * (2.0 ** -bits)
        neg_x, neg_y, neg_z = reader.read(1), reader.read(1), reader.read(1)
        z = max(0.0, 1.0 - x - y)
        x, y, z = (-x if neg_x else x), (-y if neg_y else y), (-z if neg_z else z)
        length = math.sqrt(x*x + y*y + z*z) or 1.0
        s = math.sin(theta / 2.0)
        result.append((frame, (x/length*s, y/length*s, z/length*s, math.cos(theta/2.0))))
        if frame >= frames: break
    return result


def load_mtar(path: Path) -> MotionArchive:
    data = path.read_bytes()
    if len(data) < 32 or data[:4] != b"Mtar":
        raise ValueError("Not a Peace Walker MTAR motion archive")
    max_joint, max_eff, num_bones, num_motion = struct.unpack_from("<4H", data, 4)
    flags, mtcm_base, mtex_base, bone_table_offset, table_offset = struct.unpack_from("<5I", data, 12)
    if num_motion > 10000 or num_bones > 4096:
        raise ValueError("Implausible MTAR counts")
    bone_hashes = list(struct.unpack_from(f"<{num_bones}I", data, bone_table_offset))
    pc_records = mtcm_base - table_offset >= num_motion * 32
    record_stride = 32 if pc_records else 16
    animations = []
    for index in range(num_motion):
        record = table_offset + index * record_stride
        if pc_records:
            mtcm_offset, mtcm_size, _, _ = struct.unpack_from("<4Q", data, record)
        else:
            mtcm_offset, mtcm_size, _, _ = struct.unpack_from("<4I", data, record)
        base = mtcm_base + mtcm_offset
        if base + 64 > len(data) or mtcm_size < 64: continue
        name_hash, _, _, frames, archive_offset, archive_size, joints = struct.unpack_from("<7I", data, base)
        checks = struct.unpack_from("<4I", data, base + 28)
        low_bits, high_bits, indices_offset = struct.unpack_from("<BBH", data, base + 44)
        root_offset = struct.unpack_from("<I", data, base + 48)[0]
        quat_offsets = struct.unpack_from(f"<{joints}I", data, base + 64) if joints else ()
        indices = data[base + indices_offset:base + indices_offset + joints]
        archive = data[base + archive_offset:base + archive_offset + archive_size]
        check_value = sum(value << (32 * q) for q, value in enumerate(checks))
        joint_motions = []
        for joint in range(min(joints, len(indices))):
            bone_index = indices[joint]
            if bone_index >= len(bone_hashes): continue
            start = quat_offsets[joint] * 2
            next_word = quat_offsets[joint + 1] if joint + 1 < joints else root_offset
            if next_word <= quat_offsets[joint]: next_word = root_offset
            end = min(len(archive), next_word * 2)
            bits = high_bits if ((check_value >> joint) & 1) else low_bits
            rotations = _rotations(archive[start:end], bits, frames) if bits and start < end else []
            joint_motions.append(JointMotion(bone_hashes[bone_index], rotations))
        animations.append(Animation(f"{name_hash:08x}", frames, joint_motions))
    if not animations:
        raise ValueError("No motion clips were found in this MTAR")
    return MotionArchive(path, animations)


def quaternion_at(keys, frame):
    if not keys: return (0.0, 0.0, 0.0, 1.0)
    previous = keys[0][1]
    for key_frame, quat in keys:
        if key_frame > frame: break
        previous = quat
    return previous


def rotate_vector(point, quat):
    x, y, z = point; qx, qy, qz, qw = quat
    tx, ty, tz = 2*(qy*z-qz*y), 2*(qz*x-qx*z), 2*(qx*y-qy*x)
    return (x + qw*tx + qy*tz - qz*ty,
            y + qw*ty + qz*tx - qx*tz,
            z + qw*tz + qx*ty - qy*tx)
