from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import zlib
from pathlib import Path

MASK32 = 0xFFFFFFFF
LCG = 0x02E90EDD
MANIFEST = "pwarchive-manifest.json"
CORE_NAMES = {
    "009645fa.pdt": "STAGEDAT.PDT",
    "002aba34.dat": "SLOT.DAT",
    "002aba34.key": "SLOT.KEY",
    "0001112d.pdt": "BGM.PDT",
    "00b2b2a8.pdt": "VOICEBF.PDT",
    "00b2b4b6.pdt": "VOICERT.PDT",
    "00b2b475.pdt": "VOICEPS.PDT",
    "0076531d.dat": "BRIEFING.DAT",
}

PC_RESOURCE_EXTENSIONS = {
    ".pdt", ".dat", ".key", ".olang", ".txp", ".xpr", ".xmx", ".xsx",
    ".bin", ".cmf", ".fpo", ".vpo", ".xmd",
}

SLOT_EXTENSIONS = {
    0x01: "bin", 0x02: "gcx", 0x03: "tri", 0x04: "mdh", 0x05: "mds",
    0x06: "lt2", 0x07: "cv2", 0x08: "mtar", 0x09: "mtsq", 0x0A: "mtfa",
    0x0B: "mtcm", 0x0C: "geom", 0x0F: "nav", 0x10: "cvd", 0x11: "eft",
    0x12: "zon", 0x13: "mdp", 0x14: "txp", 0x15: "kms", 0x16: "rpd",
    0x17: "fcx", 0x18: "mtst", 0x19: "mdpb", 0x1A: "mdpe", 0x1B: "dcd",
    0x1C: "ypk", 0x1D: "spk", 0x1E: "ohd", 0x1F: "mmd", 0x20: "vrd",
    0x21: "vrdv", 0x22: "vrdt", 0x23: "vcp", 0x24: "vcpg", 0x30: "mgm",
    0x31: "prx", 0x32: "rlc", 0x33: "ptcp", 0x34: "cddl", 0x35: "cap",
    0x36: "pcmp", 0x37: "sep", 0x38: "bgp", 0x5D: "olang", 0x5E: "la3",
    0x5F: "la2", 0x60: "slot", 0x61: "vram", 0x63: "cmf", 0x64: "eqp",
    0x65: "vlm", 0x66: "lst", 0x68: "png", 0x69: "img", 0x6A: "vib",
    0x6B: "rat", 0x6C: "rcm", 0x6D: "ola", 0x6E: "row", 0x6F: "mtra",
    0xF0: "dar", 0xF1: "qar", 0xF2: "cnf", 0xFF: "psq",
}

PC_XOR = 0xB9D3018F
MT_MATRIX = 0x9908B0DF
MT_MASK_7 = 0xFF3A58AD
MT_MASK_15 = 0xFFFFDF8C


def pc_filename_hash(name: str) -> int:
    """Hash the physical PC resource basename exactly as the Windows port does."""
    value = 0
    for byte in Path(name).name.split(".", 1)[0].encode("ascii"):
        value = (value * 0x2356F + byte * 0x1D35) & MASK32
    return value


class PcResourceStream:
    """Master Collection PC resource keystream recovered from the KFS loader."""

    def __init__(self, seed: int):
        state = []
        value = seed & MASK32
        for _ in range(624):
            next_value = (value * 0x10DCD + 1) & MASK32
            state.append(((next_value >> 16) | (value & 0xFFFF0000)) & MASK32)
            value = (next_value * 0x10DCD + 1) & MASK32
        self.state = state
        self.output: list[int] = []
        self.index = 624
        self._refresh()
        self.index = 5  # KFS discards the first 20 stream bytes for each file.

    def _refresh(self) -> None:
        state = self.state
        for index in range(624):
            mixed = (state[index] & 0x80000000) | (state[(index + 1) % 624] & 0x7FFFFFFF)
            state[index] = (
                state[(index + 397) % 624]
                ^ (mixed >> 1)
                ^ (MT_MATRIX if mixed & 1 else 0)
            ) & MASK32
        output = []
        for value in state:
            value ^= value >> 11
            value ^= (value & MT_MASK_7) << 7
            value &= MASK32
            value ^= (value & MT_MASK_15) << 15
            value &= MASK32
            value ^= value >> 18
            output.append(value & MASK32)
        self.output = output
        self.index = 0

    def next_word(self) -> int:
        if self.index >= 624:
            self._refresh()
        value = self.output[self.index]
        self.index += 1
        return value ^ PC_XOR


def crypt_pc_resource(data: bytes, physical_name: str) -> bytes:
    """Decrypt or encrypt one complete Master Collection PC resource."""
    stream = PcResourceStream(pc_filename_hash(physical_name))
    output = bytearray(data)
    offset = 0
    while offset + 4 <= len(output):
        struct.pack_into("<I", output, offset, u32(output, offset) ^ stream.next_word())
        offset += 4
    if offset < len(output):
        word = stream.next_word()
        for shift in range(0, (len(output) - offset) * 8, 8):
            output[offset] ^= (word >> shift) & 0xFF
            offset += 1
    return bytes(output)


def has_pc_outer_layer(path: Path) -> bool:
    stem = path.stem
    return len(stem) == 8 and all(char in "0123456789abcdefABCDEF" for char in stem)


def read_pc_aware(path: Path) -> tuple[bytes, bool]:
    data = path.read_bytes()
    outer = has_pc_outer_layer(path)
    return (crypt_pc_resource(data, path.name), True) if outer else (data, False)


def classify_pc_resource(path: Path) -> tuple[str, str]:
    """Return an extraction format and a friendly description for a PC file."""
    resolved = CORE_NAMES.get(path.name.lower(), "")
    if resolved == "STAGEDAT.PDT":
        return "stage", resolved
    if resolved == "SLOT.DAT":
        return "slot", resolved
    suffix = path.suffix.lower()
    parts = {part.upper() for part in path.parts}
    if suffix == ".xpr":
        return "xpr", "XPR2 font/texture resource"
    if suffix == ".pdt" and not parts.intersection({"DLCTEX", "DLCVOICE", "DLCBGM"}):
        return "pdt", resolved if resolved != path.name else "PDT archive/resource"
    if suffix == ".dar":
        return "dar", "DAR archive"
    if suffix == ".qar":
        return "qar", "QAR archive"
    if suffix in PC_RESOURCE_EXTENSIONS:
        if "DLCTEX" in parts:
            return "pc-resource", "DLC texture package"
        if "DLCVOICE" in parts:
            return "pc-resource", "DLC voice package"
        if "DLCBGM" in parts:
            return "pc-resource", "DLC music package"
        return "pc-resource", "encrypted PC resource"
    return "unknown", "unrecognized file"


def extract_pc_resource(source: Path, output: Path) -> None:
    data, outer = read_pc_aware(source)
    if not outer:
        raise ValueError(f"{source.name} does not have a hashed PC resource name")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"{source.name}.decrypted"
    destination.write_bytes(data)
    write_manifest(output, {"format": "pc-resource", "source": str(source),
                            "file": destination.name, "pc_outer": True})


def parse_xpr2(data: bytes) -> dict:
    """Parse the resource table of an Xbox 360 XPR2 container."""
    if len(data) < 0x10 or data[:4] != b"XPR2":
        raise ValueError("The decoded resource is not an XPR2 container")
    header_size, data_size, count = struct.unpack_from(">III", data, 4)
    if header_size < 0x10 + count * 0x18 or header_size > len(data):
        raise ValueError("Invalid XPR2 header size or resource count")
    if data_size > len(data) - header_size:
        raise ValueError("The XPR2 texture-data region is truncated")
    entries = []
    for index in range(count):
        record_offset = 0x10 + index * 0x18
        tag = data[record_offset:record_offset + 4].decode("ascii", "replace")
        offset, size, unknown_a, reference, unknown_b = struct.unpack_from(
            ">IIIII", data, record_offset + 4
        )
        if offset > header_size or size > header_size - offset:
            raise ValueError(f"Invalid XPR2 {tag!r} resource boundary")
        entries.append({
            "index": index, "tag": tag, "offset": offset, "size": size,
            "unknown_a": unknown_a, "reference": reference,
            "unknown_b": unknown_b,
        })
    return {
        "header_size": header_size, "data_size": data_size,
        "resource_count": count, "entries": entries,
        "trailing_size": len(data) - header_size - data_size,
    }


def write_grayscale_png(path: Path, pixels: bytes, width: int, height: int) -> None:
    """Write an 8-bit grayscale PNG without external image dependencies."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & MASK32)
    scanlines = b"".join(b"\0" + pixels[row * width:(row + 1) * width]
                         for row in range(height))
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(scanlines, 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def extract_xpr2(source: Path, output: Path) -> None:
    """Remove the PC layer and split an XPR2 font into usable components."""
    data, outer = read_pc_aware(source)
    info = parse_xpr2(data)
    output.mkdir(parents=True, exist_ok=True)
    container_name = f"{source.stem}.decrypted.xpr2"
    (output / container_name).write_bytes(data)
    extracted_entries = []
    for entry in info["entries"]:
        tag = "".join(char if char.isalnum() else "_" for char in entry["tag"])
        filename = f"{entry['index']:05d}_{tag}.bin"
        start, end = entry["offset"], entry["offset"] + entry["size"]
        (output / filename).write_bytes(data[start:end])
        extracted_entries.append({**entry, "file": filename})
    surface_name = "FontTexture.a8.bin"
    surface_start = info["header_size"]
    (output / surface_name).write_bytes(data[surface_start:surface_start + info["data_size"]])
    texture_entry = next((entry for entry in info["entries"] if entry["tag"] == "TX2D"), None)
    texture_png = None
    texture_width = texture_height = None
    if texture_entry and texture_entry["size"] >= 4:
        dimensions = struct.unpack_from(">I", data,
                                        texture_entry["offset"] + texture_entry["size"] - 4)[0]
        texture_width = (dimensions & 0x1FFF) + 1
        texture_height = ((dimensions >> 13) & 0x1FFF) + 1
        if texture_width * texture_height == info["data_size"]:
            linear = data[surface_start:surface_start + info["data_size"]]
            texture_png = "FontTexture.png"
            write_grayscale_png(output / texture_png, linear, texture_width, texture_height)
    header_name = "xpr2-header.bin"
    (output / header_name).write_bytes(data[:info["header_size"]])
    trailing_name = None
    if info["trailing_size"]:
        trailing_name = "xpr2-trailing.bin"
        (output / trailing_name).write_bytes(data[surface_start + info["data_size"]:])
    write_manifest(output, {
        "format": "xpr2", "source": str(source), "pc_outer": outer,
        "decrypted_container": container_name, "header_file": header_name,
        "header_size": info["header_size"], "texture_surface": surface_name,
        "texture_data_size": info["data_size"], "trailing_file": trailing_name,
        "texture_png": texture_png, "texture_width": texture_width,
        "texture_height": texture_height, "texture_format": "A8" if texture_png else "unknown",
        "trailing_size": info["trailing_size"], "entries": extracted_entries,
        "note": "FontTexture.png is the PC build's linear 8-bit font atlas; USER contains glyph mappings and metrics.",
    })


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def align(value: int, boundary: int) -> int:
    return (value + boundary - 1) & ~(boundary - 1)


def filename_hash(name: str) -> int:
    value = 0
    for byte in name.split(".", 1)[0].upper().encode("ascii"):
        value = (((value >> 19) | (value << 5)) + byte) & 0xFFFFFF
    return value or 1


def crypt_words(data: bytes, salt_a: int, salt_b: int, salt_c: int, key: int | None = None) -> bytes:
    """Peace Walker's symmetric inner-archive word cipher."""
    if len(data) % 4:
        raise ValueError("Encrypted blocks must be a multiple of four bytes")
    page = (salt_a ^ salt_b) & MASK32
    key_a = (((page ^ 0x6576) << 16) | page) & MASK32 if key is None else key
    key_b = (page * salt_c) & MASK32
    output = bytearray(data)
    for offset in range(0, len(output), 4):
        word = u32(output, offset) ^ key_a
        struct.pack_into("<I", output, offset, word)
        key_a = (key_a * LCG + key_b) & MASK32
    return bytes(output)


def crypt_words_partial(data: bytes, salt_a: int, salt_b: int, salt_c: int,
                        key: int | None = None) -> bytes:
    """Apply the inner cipher to complete words and preserve a short tail."""
    word_size = len(data) & ~3
    return crypt_words(data[:word_size], salt_a, salt_b, salt_c, key) + data[word_size:]


def safe_name(name: str, fallback: str) -> str:
    candidate = Path(name.replace("\\", "/")).name
    if not candidate or candidate in {".", ".."}:
        return fallback
    return candidate


def write_manifest(folder: Path, payload: dict) -> None:
    (folder / MANIFEST).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def extract_dar(source: Path, output: Path) -> None:
    data = source.read_bytes()
    count = u32(data, 0)
    if count > 100000:
        raise ValueError("Implausible DAR entry count; this may still have Master Collection encryption")
    output.mkdir(parents=True, exist_ok=True)
    cursor, entries = 4, []
    for index in range(count):
        end = data.index(0, cursor)
        original_name = data[cursor:end].decode("utf-8", "replace")
        cursor = align(end + 1, 4)
        size = u32(data, cursor)
        cursor = align(cursor + 4, 16)
        payload = data[cursor:cursor + size]
        name = f"{index:05d}_{safe_name(original_name, 'unnamed.bin')}"
        (output / name).write_bytes(payload)
        entries.append({"index": index, "name": original_name, "file": name, "size": size})
        cursor += size + 1
    write_manifest(output, {"format": "dar", "source": str(source), "entries": entries})


def repack_dar(folder: Path, destination: Path) -> None:
    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    entries = manifest["entries"]
    out = bytearray(struct.pack("<I", len(entries)))
    for entry in entries:
        out += entry["name"].encode("utf-8") + b"\0"
        out += b"\0" * (align(len(out), 4) - len(out))
        payload = (folder / entry["file"]).read_bytes()
        out += struct.pack("<I", len(payload))
        out += b"\0" * (align(len(out), 16) - len(out))
        out += payload + b"\0"
    destination.write_bytes(out)


def extract_qar(source: Path, output: Path, alignment: int = 0x80) -> None:
    data = source.read_bytes()
    table_offset = u32(data, len(data) - 4)
    if table_offset >= len(data) - 4:
        raise ValueError("Invalid QAR footer; this may still have Master Collection encryption")
    count = u32(data, table_offset)
    if count > 100000:
        raise ValueError("Implausible QAR entry count")
    cursor = table_offset + 4
    infos = [struct.unpack_from("<II", data, cursor + i * 8) for i in range(count)]
    cursor += count * 8
    names = []
    for _ in range(count):
        end = data.index(0, cursor)
        names.append(data[cursor:end].decode("utf-8", "replace"))
        cursor = end + 1
    output.mkdir(parents=True, exist_ok=True)
    data_cursor, entries = 0, []
    for index, ((file_info, size), original_name) in enumerate(zip(infos, names)):
        payload = data[data_cursor:data_cursor + size]
        name = f"{index:05d}_{safe_name(original_name, 'unnamed.bin')}"
        (output / name).write_bytes(payload)
        entries.append({"index": index, "name": original_name, "file": name,
                        "file_info": file_info, "size": size})
        data_cursor = align(data_cursor + size, alignment)
    write_manifest(output, {"format": "qar", "source": str(source),
                            "alignment": alignment, "entries": entries})


def repack_qar(folder: Path, destination: Path) -> None:
    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    entries, boundary = manifest["entries"], manifest.get("alignment", 0x80)
    out = bytearray()
    payloads = []
    for entry in entries:
        payload = (folder / entry["file"]).read_bytes()
        payloads.append(payload)
        out += payload
        out += b"\0" * (align(len(out), boundary) - len(out))
    table_offset = len(out)
    out += struct.pack("<I", len(entries))
    for entry, payload in zip(entries, payloads):
        out += struct.pack("<II", entry["file_info"], len(payload))
    for entry in entries:
        out += entry["name"].encode("utf-8") + b"\0"
    out += struct.pack("<I", table_offset)
    destination.write_bytes(out)


def read_stage(source: Path):
    pc_outer = has_pc_outer_layer(source)
    data_size = source.stat().st_size
    if data_size < 32:
        raise ValueError("Archive is too small")
    with source.open("rb") as stream:
        raw_header = stream.read(40 if pc_outer else 32)
    header = crypt_pc_resource(raw_header, source.name) if pc_outer else raw_header
    salts = struct.unpack_from("<III", header, 0)
    decoded_header = crypt_words(header[12:32], *salts)
    unknown_a, unknown_b, unknown_c, count, unknown_d, lookup_offset = struct.unpack("<IIIHHI", decoded_header)
    if not 0 < count < 100000:
        raise ValueError("Invalid STAGEDAT header after PC resource decryption")
    table_offset = 40 if pc_outer else 32
    table_size = count * 12
    with source.open("rb") as stream:
        combined_raw = stream.read(table_offset + table_size)
    combined = crypt_pc_resource(combined_raw, source.name) if pc_outer else combined_raw
    combined_dec = combined[:12] + crypt_words(combined[12:], *salts)
    table_dec = combined_dec[table_offset:table_offset + table_size]
    entries = [struct.unpack_from("<III", table_dec, i * 12) for i in range(count)]
    if any(offset >= data_size or size < 4 for size, _, offset in entries):
        raise ValueError("Invalid STAGEDAT page table")
    return data_size, salts, entries, pc_outer


def read_simple_pdt(source: Path):
    """Read the second common PDT variant used by voice, BGM, and loose PC packs."""
    data_size = source.stat().st_size
    if data_size < 40:
        raise ValueError("PDT is too small")
    with source.open("rb") as stream:
        header = bytearray(stream.read(40))
    pc_outer = has_pc_outer_layer(source)
    if pc_outer:
        header = bytearray(crypt_pc_resource(header, source.name))
    xor_key = header[0]
    for offset in range(17, len(header)):
        header[offset] ^= xor_key
    count = u16(header, 24)
    if not 0 < count < 100000:
        raise ValueError("Invalid simple PDT header")
    table_end = 40 + count * 12
    if table_end > data_size:
        raise ValueError("Simple PDT table extends beyond the file")
    with source.open("rb") as stream:
        table_data = bytearray(stream.read(table_end))
    if pc_outer:
        table_data = bytearray(crypt_pc_resource(table_data, source.name))
    for offset in range(17, len(table_data)):
        table_data[offset] ^= xor_key
    entries = [struct.unpack_from("<III", table_data, 40 + i * 12) for i in range(count)]
    for index, (size, _, offset) in enumerate(entries):
        next_offset = entries[index + 1][2] if index + 1 < count else data_size
        if offset < table_end or next_offset <= offset or size > next_offset - offset:
            raise ValueError("Invalid simple PDT entry table")
    return data_size, xor_key, entries, pc_outer


def detect_pdt_variant(source: Path) -> str:
    errors = []
    for variant, reader in (("stage", read_stage), ("simple-pdt", read_simple_pdt)):
        try:
            reader(source)
            return variant
        except (ValueError, struct.error, zlib.error) as exc:
            errors.append(str(exc))
    raise ValueError("The PDT header is not one of the currently recognized PC variants: " + "; ".join(errors))


def find_ogg_stream(payload: bytes) -> tuple[int, int] | None:
    """Locate one complete Ogg stream, including its end-of-stream page."""
    start = payload.find(b"OggS")
    if start < 0:
        return None
    cursor = start
    serial = None
    while cursor + 27 <= len(payload) and payload[cursor:cursor + 4] == b"OggS":
        segment_count = payload[cursor + 26]
        header_end = cursor + 27 + segment_count
        if header_end > len(payload):
            return None
        page_end = header_end + sum(payload[cursor + 27:header_end])
        if page_end > len(payload):
            return None
        page_serial = u32(payload, cursor + 14)
        if serial is None:
            serial = page_serial
        if page_serial == serial and payload[cursor + 5] & 0x04:
            return start, page_end
        cursor = page_end
    return None


def describe_fel(payload: bytes) -> dict | None:
    """Expose the stable index portion of a FEL animation/event resource."""
    if len(payload) < 24 or not payload.startswith(b"FEL"):
        return None
    hash_count = u16(payload, 20)
    id_count = u16(payload, 22)
    hash_offset = align(24 + id_count * 2, 4)
    if hash_count > 10000 or id_count > 10000 or hash_offset + hash_count * 4 > len(payload):
        return None
    ids = [u16(payload, 24 + index * 2) for index in range(id_count)]
    hashes = [u32(payload, hash_offset + index * 4) for index in range(hash_count)]
    return {"magic": payload[:4].hex(), "version": payload[3],
            "value_0c": u32(payload, 12), "value_10": u32(payload, 16),
            "id_count": id_count, "hash_count": hash_count,
            "ids": ids, "hashes": [f"{value:08x}" for value in hashes]}


def extract_simple_pdt(source: Path, output: Path, progress=None) -> None:
    data_size, xor_key, entries, pc_outer = read_simple_pdt(source)
    output.mkdir(parents=True, exist_ok=True)
    manifest_entries = []
    xor_table = bytes.maketrans(bytes(range(256)), bytes(value ^ xor_key for value in range(256)))
    if progress:
        progress(f"Decoded PDT table; {len(entries):,} files found.")
    with source.open("rb") as stream:
        for index, (stored_size, key_hash, offset) in enumerate(entries):
            next_offset = entries[index + 1][2] if index + 1 < len(entries) else data_size
            allocated = next_offset - offset
            stream.seek(offset)
            encoded = stream.read(allocated)
            payload = (crypt_pc_resource(encoded, source.name) if pc_outer else encoded).translate(xor_table)
            content = payload[:stored_size]
            extension = "spk" if content.startswith(b"SP") else "fel" if content.startswith(b"FEL") else "bin"
            name = f"{index:05d}_{key_hash:08x}.{extension}"
            (output / name).write_bytes(content)
            manifest_entry = {"index": index, "key": key_hash, "file": name,
                              "offset": offset, "stored_size": stored_size,
                              "allocated": allocated,
                              "sha256": hashlib.sha256(content).hexdigest()}
            ogg_range = find_ogg_stream(content) if extension == "spk" else None
            if ogg_range:
                ogg_start, ogg_end = ogg_range
                ogg_name = f"{index:05d}_{key_hash:08x}.ogg"
                ogg = content[ogg_start:ogg_end]
                (output / ogg_name).write_bytes(ogg)
                manifest_entry.update({"embedded_file": ogg_name,
                                       "embedded_offset": ogg_start,
                                       "embedded_size": len(ogg),
                                       "embedded_length_offset": 0x50 if len(content) >= 0x54 and u32(content, 0x50) == len(ogg) else None,
                                       "embedded_sha256": hashlib.sha256(ogg).hexdigest()})
            if extension == "fel":
                description = describe_fel(content)
                if description:
                    metadata_name = f"{index:05d}_{key_hash:08x}.fel.json"
                    (output / metadata_name).write_text(json.dumps(description, indent=2), encoding="utf-8")
                    manifest_entry["metadata_file"] = metadata_name
            manifest_entries.append(manifest_entry)
            if progress and (index == 0 or (index + 1) % 10 == 0 or index + 1 == len(entries)):
                progress(f"Extracting PDT file {index + 1:,} of {len(entries):,}…")
    write_manifest(output, {"format": "simple-pdt", "source": str(source),
                            "xor_key": xor_key, "pc_outer": pc_outer,
                            "entries": manifest_entries})


def extract_pdt(source: Path, output: Path, progress=None) -> str:
    variant = detect_pdt_variant(source)
    if variant == "stage":
        extract_stage(source, output, progress)
    else:
        extract_simple_pdt(source, output, progress)
    return variant


def repack_simple_pdt(folder: Path, destination: Path) -> None:
    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    source = Path(manifest["source"])
    raw = source.read_bytes()
    output = bytearray(raw)
    xor_key = manifest["xor_key"]
    pc_outer = bool(manifest.get("pc_outer"))
    xor_table = bytes.maketrans(bytes(range(256)), bytes(value ^ xor_key for value in range(256)))
    for entry in manifest["entries"]:
        content = (folder / entry["file"]).read_bytes()
        embedded_file = entry.get("embedded_file")
        if embedded_file:
            embedded = (folder / embedded_file).read_bytes()
            if entry.get("embedded_sha256") != hashlib.sha256(embedded).hexdigest():
                embedded_size = entry["embedded_size"]
                if len(embedded) > embedded_size:
                    raise ValueError(f"{embedded_file} needs {len(embedded)} bytes but only {embedded_size} are available")
                start = entry["embedded_offset"]
                rebuilt = bytearray(content)
                rebuilt[start:start + embedded_size] = embedded + b"\0" * (embedded_size - len(embedded))
                length_offset = entry.get("embedded_length_offset")
                if length_offset is not None:
                    struct.pack_into("<I", rebuilt, length_offset, len(embedded))
                content = bytes(rebuilt)
        if entry.get("sha256") == hashlib.sha256(content).hexdigest():
            continue
        allocated = entry["allocated"]
        if len(content) > allocated:
            raise ValueError(f"{entry['file']} needs {len(content)} bytes but only {allocated} are allocated")
        decoded = (content + b"\0" * (allocated - len(content))).translate(xor_table)
        encoded = crypt_pc_resource(decoded, source.name) if pc_outer else bytes(decoded)
        start = entry["offset"]
        output[start:start + allocated] = encoded
    destination.write_bytes(output)


def strcode24(value: str) -> int:
    result = 0
    for byte in value.encode("ascii"):
        result = (((result >> 19) | (result << 5)) + byte) & 0xFFFFFF
    return result or 1


def stage_lookup_hash(file_code: int, stage_name: str) -> int:
    folder = strcode24(stage_name)
    folder = ((folder >> 4) ^ (folder << 4)) & MASK32
    folder ^= 0x10EA
    return ((~folder) & MASK32) ^ file_code


def stage_file_code(filename: str) -> int | None:
    if "." not in filename:
        return None
    stem, extension = filename.rsplit(".", 1)
    extension_ids = {name: ident for ident, name in SLOT_EXTENSIONS.items()}
    extension_id = extension_ids.get(extension.lower())
    if extension_id is None:
        return None
    return strcode24(stem) ^ (extension_id << 24)


def read_stage_lookup(source: Path, salts: tuple[int, int, int], count: int,
                      pc_outer: bool) -> dict[int, int]:
    header_size = 40 if pc_outer else 32
    table_end = header_size + count * 12
    stride = 24 if pc_outer else 16
    end = table_end + count * stride
    with source.open("rb") as stream:
        raw = stream.read(end)
    decoded = crypt_pc_resource(raw, source.name) if pc_outer else raw
    decoded = decoded[:12] + crypt_words(decoded[12:], *salts)
    lookup = {}
    for index in range(count):
        offset = table_end + index * stride
        key, file_index = struct.unpack_from("<II", decoded, offset)
        if file_index < count:
            lookup[key] = file_index
    return lookup


def cnf_filenames(payload: bytes) -> list[str]:
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeDecodeError:
        return []
    result = []
    skip_endslot = False
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if skip_endslot:
            skip_endslot = False
            continue
        if line.startswith(".slot "):
            skip_endslot = True
            continue
        if line.startswith(".vram "):
            result.extend(line.split()[1:])
        elif line.startswith("."):
            continue
        elif line[0] in "@?":
            result.append(line[1:])
        else:
            result.append(line)
    return result


def resolve_stage_entry_names(source: Path, output: Path, salts: tuple[int, int, int],
                              pc_outer: bool, entries: list[dict]) -> int:
    lookup = read_stage_lookup(source, salts, len(entries), pc_outer)
    aliases: dict[int, set[tuple[str, str]]] = {}
    cnf_code = stage_file_code("data.cnf")
    for entry in entries:
        path = output / entry["file"]
        if path.stat().st_size > 0x10000:
            continue
        payload = path.read_bytes()
        names = cnf_filenames(payload)
        stage_candidates = [Path(name).stem for name in names if name.lower().endswith(".rlc")]
        for stage_name in stage_candidates:
            if lookup.get(stage_lookup_hash(cnf_code, stage_name)) != entry["index"]:
                continue
            aliases.setdefault(entry["index"], set()).add((stage_name, "data.cnf"))
            for filename in names:
                file_code = stage_file_code(filename)
                if file_code is None:
                    continue
                file_index = lookup.get(stage_lookup_hash(file_code, stage_name))
                if file_index is not None:
                    aliases.setdefault(file_index, set()).add((stage_name, filename))
            break
    resolved = 0
    by_index = {entry["index"]: entry for entry in entries}
    for index, values in aliases.items():
        entry = by_index[index]
        ordered = sorted(values, key=lambda value: (value[1] == "data.cnf", value[1], value[0]))
        preferred = ordered[0][1]
        new_name = f"{index:05d}_{entry['key']:08x}_{safe_name(preferred, 'resource.bin')}"
        old_path = output / entry["file"]
        new_path = output / new_name
        if old_path != new_path:
            old_path.replace(new_path)
        entry["file"] = new_name
        entry["aliases"] = [{"stage": stage, "name": name} for stage, name in ordered]
        resolved += 1
    return resolved


def extract_stage(source: Path, output: Path, progress=None) -> None:
    data_size, salts, entries, pc_outer = read_stage(source)
    output.mkdir(parents=True, exist_ok=True)
    manifest_entries = []
    if progress:
        progress(f"Decoded STAGEDAT table; {len(entries):,} files found.")
    with source.open("rb") as stream:
        for index, (stored_size, key_hash, offset) in enumerate(entries):
            next_offset = entries[index + 1][2] if index + 1 < len(entries) else data_size
            allocated = next_offset - offset
            if allocated < stored_size:
                raise ValueError(f"Invalid STAGEDAT allocation at entry {index}")
            stream.seek(offset)
            encrypted = stream.read(allocated)
            outer_decoded = crypt_pc_resource(encrypted, source.name) if pc_outer else encrypted
            decoded = crypt_words_partial(outer_decoded[:stored_size], *salts)
            unpacked_size = u32(decoded, 0)
            payload = zlib.decompress(decoded[4:stored_size])
            if len(payload) != unpacked_size:
                raise ValueError(f"Stage entry {index} size mismatch")
            name = f"{index:05d}_{key_hash:08x}.bin"
            (output / name).write_bytes(payload)
            manifest_entries.append({"index": index, "key": key_hash, "file": name,
                                     "offset": offset, "stored_size": stored_size,
                                     "allocated": allocated, "size": unpacked_size,
                                     "sha256": hashlib.sha256(payload).hexdigest()})
            if progress and (index == 0 or (index + 1) % 10 == 0 or index + 1 == len(entries)):
                progress(f"Extracting PDT file {index + 1:,} of {len(entries):,}…")
    resolved = resolve_stage_entry_names(source, output, salts, pc_outer, manifest_entries)
    if progress:
        progress(f"Recovered real names for {resolved:,} of {len(entries):,} stage resources.")
    write_manifest(output, {"format": "stage", "source": str(source),
                            "salts": list(salts), "pc_outer": pc_outer,
                            "entries": manifest_entries})


def repack_fixed_pages(folder: Path, destination: Path) -> None:
    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    source = Path(manifest["source"])
    raw = source.read_bytes()
    pc_outer = bool(manifest.get("pc_outer"))
    output = bytearray(raw)
    salts = tuple(manifest["salts"])
    for entry in manifest["entries"]:
        payload = (folder / entry["file"]).read_bytes()
        if entry.get("sha256") == hashlib.sha256(payload).hexdigest():
            continue
        compressed = zlib.compress(payload, 9)
        plain = struct.pack("<I", len(payload)) + compressed
        allocated = entry["allocated"]
        stored_size = entry.get("stored_size", allocated)
        if len(plain) > stored_size:
            raise ValueError(f"{entry['file']} needs {len(plain)} bytes but only {stored_size} are available")
        plain += b"\0" * (stored_size - len(plain))
        start = entry["offset"]
        if "stored_size" in entry:
            original = raw[start:start + allocated]
            inner_layer = crypt_pc_resource(original, source.name) if pc_outer else original
            rebuilt_inner = crypt_words_partial(plain, *salts) + inner_layer[stored_size:]
            encrypted = crypt_pc_resource(rebuilt_inner, source.name) if pc_outer else rebuilt_inner
        else:
            plain += b"\0" * (allocated - len(plain))
            if len(plain) % 4:
                raise ValueError(f"Original allocation for {entry['file']} is not word aligned")
            encrypted = crypt_words(plain, *salts)
            if pc_outer:
                encrypted = crypt_pc_resource(encrypted, source.name)
        output[start:start + allocated] = encrypted
    destination.write_bytes(output)


def parse_slot_contents(payload: bytes) -> list[dict]:
    """Parse the HD/PC CNF table stored inside one decompressed SLOT page."""
    if len(payload) < 8:
        raise ValueError("SLOT page is too small for its internal file table")
    count = u32(payload, 0)
    table_end = 8 + count * 16
    if count < 2 or count > 100000 or table_end > len(payload):
        raise ValueError("Invalid internal SLOT file table")
    tags = [(u32(payload, 8 + i * 16), u32(payload, 16 + i * 16)) for i in range(count)]
    data_base = table_end
    region = 0
    files = []
    for index in range(count - 1):
        ident, offset = tags[index]
        next_offset = tags[index + 1][1]
        extension_id = ident >> 24
        if extension_id == 0x7F:
            region = ident & 0xFFFFFF
            if region:
                data_base = align(data_base, 0x1000)
            continue
        if extension_id in (0x00, 0x7D, 0x7E) or next_offset < offset:
            continue
        absolute = data_base + offset
        size = next_offset - offset
        if absolute < table_end or absolute + size > len(payload):
            raise ValueError(f"Internal SLOT file {index} is outside the page")
        extension = SLOT_EXTENSIONS.get(extension_id, f"ext{extension_id:02x}")
        files.append({
            "tag_index": index, "id": ident, "hash": ident & 0xFFFFFF,
            "extension_id": extension_id, "extension": extension,
            "region": region, "offset": absolute, "allocated": size,
        })
    return files


def extract_slot_contents(payload: bytes, page_folder: Path) -> list[dict]:
    page_folder.mkdir(parents=True, exist_ok=True)
    entries = parse_slot_contents(payload)
    for entry in entries:
        name = f"{entry['tag_index']:04d}_{entry['hash']:06x}.{entry['extension']}"
        content = payload[entry["offset"]:entry["offset"] + entry["allocated"]]
        (page_folder / name).write_bytes(content)
        entry["file"] = name
        entry["size"] = len(content)
        entry["sha256"] = hashlib.sha256(content).hexdigest()
    write_manifest(page_folder, {"format": "slot-page", "entries": entries})
    return entries


def apply_slot_content_edits(payload: bytes, page_folder: Path) -> bytes:
    manifest_path = page_folder / MANIFEST
    if not manifest_path.exists():
        return payload
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output = bytearray(payload)
    for entry in manifest.get("entries", []):
        path = page_folder / entry["file"]
        content = path.read_bytes()
        allocated = entry["allocated"]
        if len(content) > allocated:
            raise ValueError(
                f"{page_folder.name}/{entry['file']} is {len(content)} bytes; "
                f"its fixed SLOT allocation is {allocated} bytes"
            )
        start = entry["offset"]
        output[start:start + allocated] = content + b"\0" * (allocated - len(content))
    return bytes(output)


def extract_slot(source: Path, key_file: Path, output: Path, sector: int = 0x800,
                 progress=None) -> None:
    data_size = source.stat().st_size
    data_outer = has_pc_outer_layer(source)
    key_data, key_outer = read_pc_aware(key_file)
    stride = 20 if key_outer else 12
    if len(key_data) < 12 + stride or (len(key_data) - 12) % stride:
        raise ValueError("Invalid SLOT.KEY table after PC resource decryption")
    salts = struct.unpack_from("<III", key_data, 0)
    count = (len(key_data) - 12) // stride
    if progress:
        progress(f"Decoded {key_file.name}; {count:,} archive pages found.")
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    with source.open("rb") as data_file:
        for index in range(count):
            first, last, key_hash = struct.unpack_from("<III", key_data, 12 + index * stride)
            start, end = (first & 0xFFFFF) * sector, (last & 0xFFFFF) * sector
            if end <= start or end > data_size:
                raise ValueError(f"Invalid SLOT page boundary at index {index}")
            data_file.seek(start)
            page = data_file.read(end - start)
            if data_outer:
                page = crypt_pc_resource(page, source.name)
            decoded = crypt_words(page, *salts)
            compressed_size, unpacked_size = u32(decoded, 8), u32(decoded, 12)
            payload = zlib.decompress(decoded[16:16 + compressed_size])
            if len(payload) != unpacked_size:
                raise ValueError(f"SLOT page {index} size mismatch")
            name = f"{index:05d}_{key_hash:08x}.slot"
            (output / name).write_bytes(payload)
            contents_folder = f"{Path(name).stem}_files"
            inner_entries = extract_slot_contents(payload, output / contents_folder)
            entries.append({"index": index, "key": key_hash, "file": name,
                            "contents_folder": contents_folder,
                            "content_count": len(inner_entries),
                            "offset": start, "allocated": end - start,
                            "size": unpacked_size, "header_prefix": decoded[:8].hex(),
                            "sha256": hashlib.sha256(payload).hexdigest()})
            if progress and (index == 0 or (index + 1) % 10 == 0 or index + 1 == count):
                progress(f"Extracting page {index + 1:,} of {count:,}…")
    write_manifest(output, {"format": "slot", "source": str(source),
                            "key_file": str(key_file), "sector": sector,
                            "salts": list(salts), "pc_outer": data_outer,
                            "key_pc_outer": key_outer, "entries": entries})


def repack_slot(folder: Path, destination: Path) -> None:
    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    source = Path(manifest["source"])
    raw = source.read_bytes()
    pc_outer = bool(manifest.get("pc_outer"))
    output = bytearray(raw)
    salts = tuple(manifest["salts"])
    for entry in manifest["entries"]:
        payload = (folder / entry["file"]).read_bytes()
        contents_folder = entry.get("contents_folder")
        if contents_folder:
            payload = apply_slot_content_edits(payload, folder / contents_folder)
        if entry.get("sha256") == hashlib.sha256(payload).hexdigest():
            continue
        compressed = zlib.compress(payload, 9)
        plain = bytes.fromhex(entry["header_prefix"]) + struct.pack("<II", len(compressed), len(payload)) + compressed
        allocated = entry["allocated"]
        if len(plain) > allocated:
            raise ValueError(f"{entry['file']} needs {len(plain)} bytes but only {allocated} are allocated")
        plain += b"\0" * (allocated - len(plain))
        encrypted = crypt_words(plain, *salts)
        if pc_outer:
            encrypted = crypt_pc_resource(encrypted, source.name)
        start = entry["offset"]
        output[start:start + allocated] = encrypted
    destination.write_bytes(output)


def inspect_file(path: Path) -> None:
    resolved = CORE_NAMES.get(path.name.lower(), path.name)
    print(f"File: {path}")
    print(f"Recognized name: {resolved}")
    print(f"Size: {path.stat().st_size:,} bytes")
    print(f"Name hash: {filename_hash(resolved):06X}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Peace Walker archive extractor/repacker")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect_p = sub.add_parser("inspect"); inspect_p.add_argument("archive", type=Path)
    extract_p = sub.add_parser("extract")
    extract_p.add_argument("format", choices=("dar", "qar", "pdt", "stage", "slot", "xpr", "pc-resource"))
    extract_p.add_argument("archive", type=Path); extract_p.add_argument("output", type=Path)
    extract_p.add_argument("--key", type=Path)
    repack_p = sub.add_parser("repack")
    repack_p.add_argument("folder", type=Path); repack_p.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "inspect": inspect_file(args.archive); return
    if args.command == "extract":
        if args.format == "dar": extract_dar(args.archive, args.output)
        elif args.format == "qar": extract_qar(args.archive, args.output, 0x80)
        elif args.format == "pdt": extract_pdt(args.archive, args.output)
        elif args.format == "stage": extract_stage(args.archive, args.output)
        elif args.format == "slot":
            if not args.key: parser.error("SLOT extraction requires --key SLOT.KEY")
            extract_slot(args.archive, args.key, args.output, 0x1000)
        elif args.format == "pc-resource": extract_pc_resource(args.archive, args.output)
        elif args.format == "xpr": extract_xpr2(args.archive, args.output)
        return
    manifest = json.loads((args.folder / MANIFEST).read_text(encoding="utf-8"))
    fmt = manifest["format"]
    if fmt == "dar": repack_dar(args.folder, args.output)
    elif fmt == "qar": repack_qar(args.folder, args.output)
    elif fmt == "stage": repack_fixed_pages(args.folder, args.output)
    elif fmt == "simple-pdt": repack_simple_pdt(args.folder, args.output)
    elif fmt == "slot": repack_slot(args.folder, args.output)
    else: raise ValueError(f"Unsupported manifest format: {fmt}")


if __name__ == "__main__":
    main()
