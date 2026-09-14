from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image


@dataclass
class TexturePack:
    path: Path
    textures: dict[int, Image.Image]


def _scan_dds_textures(data: bytes) -> dict[int, Image.Image]:
    """Recover DDS images from QAR entries that are raw texture bundles."""
    textures = {}
    offset = 0
    while True:
        offset = data.find(b"DDS ", offset)
        if offset < 0:
            break
        try:
            with Image.open(BytesIO(data[offset:])) as decoded:
                image = decoded.convert("RGBA").copy()
            # Raw bundles have no TXP texture hash. Use a stable synthetic key
            # derived from the DDS location so the UI can still identify it.
            key = 0xDD000000 | (offset & 0x00FFFFFF)
            while key in textures:
                key = (key + 1) & 0xFFFFFFFF
            textures[key] = image
        except (OSError, ValueError):
            # Some Master Collection cache entries keep a DDS header inside a
            # detached raw DXT payload. Rejoin the header with the payload,
            # whose start can be derived from the declared dimensions/codec.
            try:
                if offset + 128 > len(data):
                    raise ValueError("truncated DDS header")
                header = data[offset:offset + 128]
                height, width = struct.unpack_from("<2I", header, 12)
                fourcc = header[84:88]
                if not (0 < width <= 16384 and 0 < height <= 16384):
                    raise ValueError("invalid detached DDS dimensions")
                if fourcc == b"DXT1":
                    payload_size = max(8, ((width + 3) // 4) * ((height + 3) // 4) * 8)
                elif fourcc in (b"DXT3", b"DXT5"):
                    payload_size = max(16, ((width + 3) // 4) * ((height + 3) // 4) * 16)
                else:
                    raise ValueError("unsupported detached DDS codec")
                payload_offset = len(data) - payload_size
                if payload_offset < 0 or offset < payload_offset:
                    raise ValueError("detached DDS payload is incomplete")
                with Image.open(BytesIO(header + data[payload_offset:])) as decoded:
                    image = decoded.convert("RGBA").copy()
                key = 0xDD000000 | (offset & 0x00FFFFFF)
                textures[key] = image
            except (OSError, ValueError, struct.error):
                pass
        offset += 4
    return textures


def _decode_raw_indexed_guesses(data: bytes) -> dict[int, Image.Image]:
    """Create useful previews for small headerless PSP indexed-texture entries.

    A raw QAR entry has lost its dimensions and palette, so several likely
    interpretations are exposed using a neutral grayscale palette.
    """
    if not data or len(data) > 65536:
        return {}
    def decoded_mask(offset: int, width: int, height: int, bpp: int = 4) -> Image.Image:
        packed = width * height // (2 if bpp == 4 else 1)
        indices = _unswizzle(data[offset:offset + packed], width, height, bpp)
        levels = 15 if bpp == 4 else 255
        rgba = bytearray(width * height * 4)
        for pixel, value in enumerate(indices):
            alpha = round(value * 255 / levels)
            preview = 56 + round(alpha * 199 / 255)
            q = pixel * 4
            # With no TXP table we cannot know whether an index is color,
            # opacity, or which MDP hash owns this image. Keep the diagnostic
            # preview opaque so a wrong inferred assignment cannot erase a mesh.
            rgba[q:q + 4] = bytes((preview, preview, preview, 255))
        image = Image.frombytes("RGBA", (width, height), bytes(rgba))
        image.info["raw_indexed_preview"] = True
        image.info["raw_offset"] = offset
        return image

    # Common multi-image cache payload used by weapon/effect assets. The 48
    # final bytes are alignment data; the preceding four images are contiguous.
    if len(data) == 9776:
        layout = ((0, 128, 64), (4096, 128, 64), (8192, 64, 32), (9216, 32, 32))
        return {
            0xF1000000 | index: decoded_mask(offset, width, height)
            for index, (offset, width, height) in enumerate(layout)
        }

    candidates = []
    dimensions = (16, 32, 64, 128, 256, 512)
    for bpp in (4, 5):
        divisor = 2 if bpp == 4 else 1
        for width in dimensions:
            for height in dimensions:
                packed = width * height // divisor
                trailing = len(data) - packed
                if trailing not in (0, 64, 128, 192, 256):
                    continue
                aspect = max(width, height) / min(width, height)
                # These headerless PSP cache textures are normally 4-bit.
                # Prefer that layout, then landscape/square shapes commonly
                # used by item and UI assets.
                candidates.append((bpp != 4, width < height, aspect, trailing, bpp, width, height, packed))
    candidates.sort()
    textures = {}
    seen = set()
    for _, _, _, trailing, bpp, width, height, packed in candidates:
        signature = (bpp, width, height)
        if signature in seen:
            continue
        seen.add(signature)
        try:
            image = decoded_mask(0, width, height, bpp)
        except (ValueError, IndexError):
            continue
        key = 0xF0000000 | ((bpp & 0xF) << 20) | ((width & 0x3FF) << 10) | (height & 0x3FF)
        textures[key] = image
        if len(textures) >= 8:
            break
    return textures


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
    tables_valid = (
        0 < num_images <= 65536
        and 0 < num_info <= 100000
        and image_table >= 32
        and info_table >= 32
        and image_table + num_images * image_stride <= len(data)
        and info_table + num_info * info_stride <= len(data)
    )
    if not tables_valid:
        textures = _scan_dds_textures(data)
        if not textures:
            textures = _decode_raw_indexed_guesses(data)
        if textures:
            return TexturePack(path, textures)
        raise ValueError(
            "This QAR entry is raw texture data without a TXP image table, "
            "and it contains no standalone DDS images that can be previewed."
        )

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
    dds_cache = {}
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
        if bpp == 6:
            # Master Collection PC TXPs store a complete DDS payload at the
            # second resource pointer in each texture-info record. Pillow's
            # DDS decoder handles the DXT/BC format declared by that header.
            dds_offset = clut_offset
            _range(data, dds_offset, 128, "Embedded DDS texture")
            if data[dds_offset:dds_offset + 4] != b"DDS ":
                continue
            image = dds_cache.get(dds_offset)
            if image is None:
                try:
                    with Image.open(BytesIO(data[dds_offset:])) as decoded:
                        image = decoded.convert("RGBA").copy()
                except (OSError, ValueError) as exc:
                    raise ValueError(
                        f"Could not decode embedded DDS texture {texture_hash:08X}"
                    ) from exc
                dds_cache[dds_offset] = image
            textures[texture_hash] = image
            continue
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
        raise ValueError("No supported textures were found in this TXP")
    return TexturePack(path, textures)
