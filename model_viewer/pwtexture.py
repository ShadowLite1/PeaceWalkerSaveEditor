from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass
class TexturePack:
    path: Path
    textures: dict[int, Image.Image]


def _range(data: bytes, offset: int, size: int, label: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError(f"{label} points outside the TXP file")


def _unswizzle(src: bytes, width: int, height: int, bpp: int) -> bytearray:
    out = bytearray(width * height)
    pos = 0
    if bpp == 4:
        for y in range(height):
            yc0, yc1 = y * 16, (y // 8) * (width * 4 - 128)
            for x in range(width // 2):
                xc0, xc1 = (x // 16) * 16, (x // 16) * 128
                q = x - xc0 + xc1 + yc0 + yc1
                if q >= len(src): break
                out[pos], out[pos + 1] = src[q] & 15, src[q] >> 4
                pos += 2
    elif bpp == 5:
        for y in range(height):
            yc0, yc1 = y * 16, (y // 8) * (width * 8 - 128)
            for x in range(width):
                xc0, xc1 = (x // 16) * 16, (x // 16) * 128
                q = x - xc0 + xc1 + yc0 + yc1
                if q < len(src): out[pos] = src[q]
                pos += 1
    else:
        raise ValueError(f"Unsupported indexed TXP format {bpp}")
    return out


def load_txp(path: Path) -> TexturePack:
    data = path.read_bytes()
    if len(data) < 32:
        raise ValueError("TXP file is too small")
    # Master Collection stores the three table offsets as 64-bit values.
    pc = len(data) >= 48 and struct.unpack_from("<Q", data, 24)[0] < len(data)
    _, _, num_images, num_info, num_colours = struct.unpack_from("<5I", data, 0)
    if pc:
        image_table, info_table, _ = struct.unpack_from("<3Q", data, 24)
        image_stride, info_stride = 32, 48
    else:
        image_table, info_table, _ = struct.unpack_from("<3I", data, 20)
        image_stride, info_stride = 20, 40
    if num_images > 65536 or num_info > 100000:
        raise ValueError("Implausible TXP table counts")
    _range(data, image_table, num_images * image_stride, "TXP image table")
    _range(data, info_table, num_info * info_stride, "TXP info table")

    images = []
    for i in range(num_images):
        o = image_table + i * image_stride
        flag, width_raw, height_raw, _ = struct.unpack_from("<4H", data, o)
        if pc:
            pixel_offset, z_offset = struct.unpack_from("<2Q", data, o + 16)
        else:
            pixel_offset, z_offset = struct.unpack_from("<2I", data, o + 12)
        images.append((flag, width_raw & 0xFFF, height_raw & 0xFFF, pixel_offset, z_offset))

    textures = {}
    for i in range(num_info):
        o = info_table + i * info_stride
        _, texture_hash = struct.unpack_from("<2I", data, o)
        if pc:
            image_offset, clut_offset = struct.unpack_from("<2Q", data, o + 8)
            u_scale, v_scale, u_offset, v_offset = struct.unpack_from("<4f", data, o + 24)
            width, height, x_offset, y_offset = struct.unpack_from("<4h", data, o + 40)
        else:
            image_offset, clut_offset = struct.unpack_from("<2I", data, o + 8)
            u_scale, v_scale, u_offset, v_offset = struct.unpack_from("<4f", data, o + 16)
            width, height, x_offset, y_offset = struct.unpack_from("<4h", data, o + 32)
        image_index = (image_offset - image_table) // image_stride
        if image_index < 0 or image_index >= len(images) or width <= 0 or height <= 0:
            continue
        flag, atlas_width, atlas_height, pixel_offset, z_offset = images[image_index]
        bpp, compressed = flag & 15, bool(flag & 0xF0)
        if not pixel_offset or bpp not in (4, 5):
            continue
        packed_size = atlas_width * atlas_height // (2 if bpp == 4 else 1)
        if compressed:
            _range(data, z_offset, 4, "Compressed TXP pixels")
            compressed_size = struct.unpack_from("<I", data, z_offset)[0]
            raw = zlib.decompress(data[z_offset + 4:z_offset + 4 + compressed_size])
        else:
            _range(data, pixel_offset, packed_size, "TXP pixels")
            raw = data[pixel_offset:pixel_offset + packed_size]
        indices = _unswizzle(raw, atlas_width, atlas_height, bpp)
        colour_count = 16 if bpp == 4 else 256
        _range(data, clut_offset, colour_count * 4, "TXP palette")
        palette = [tuple(data[clut_offset + q:clut_offset + q + 4]) for q in range(0, colour_count * 4, 4)]
        rgba = bytearray(width * height * 4)
        for y in range(height):
            for x in range(width):
                source = x + x_offset + (y + y_offset) * atlas_width
                if source >= len(indices): continue
                r, g, b, a = palette[indices[source] % colour_count]
                q = (x + y * width) * 4
                rgba[q:q + 4] = bytes((r, g, b, min(255, a * 2)))
        textures[texture_hash] = Image.frombytes("RGBA", (width, height), bytes(rgba))
    if not textures:
        raise ValueError("No supported indexed textures were found in this TXP")
    return TexturePack(path, textures)
