from __future__ import annotations

import argparse
import struct
from pathlib import Path


REGION_OFFSET = 0x40
REGION_SIZE = 0x387F0
BLOCK2_HEADER_OFFSET = 0x38830
BLOCK2_REGION_OFFSET = 0x38870
BLOCK2_PC_REGION_SIZE = 0xF0E0
MULTIPLIER = 0x02E90EDD


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def filename_checksum(data: bytes | bytearray) -> int:
    checksum = 0xFFFF
    for offset in range(0, len(data) & ~1, 2):
        checksum ^= struct.unpack_from("<H", data, offset)[0]
    return checksum


def derive_state_at(data: bytes | bytearray, index: int) -> tuple[int, int, int, int, int]:
    return derive_state_at_header(data, 0, index)


def derive_state_at_header(
    data: bytes | bytearray, header_offset: int, index: int
) -> tuple[int, int, int, int, int]:
    base = header_offset + index * 4
    seed_a = u32(data, base + 0x08) ^ 0x1327DE73
    seed_b = u32(data, base + 0x0C) ^ 0x2D71D26C
    seed_c = u32(data, base + 0x1C) ^ 0xBC4DEFA2
    mixed = (seed_a ^ seed_b) & 0xFFFFFFFF
    key = ((((mixed ^ 0x6576) << 16) & 0xFFFFFFFF) | mixed) & 0xFFFFFFFF
    increment = (mixed * seed_c) & 0xFFFFFFFF
    return seed_a, seed_b, seed_c, key, increment


def _preview_score(data: bytes | bytearray, key: int, increment: int) -> int:
    return _preview_score_region(data, REGION_OFFSET, key, increment)


def _preview_score_region(
    data: bytes | bytearray, region_offset: int, key: int, increment: int
) -> int:
    preview = bytearray(data[region_offset:region_offset + 0x100])
    for offset in range(0, len(preview), 4):
        struct.pack_into("<I", preview, offset, u32(preview, offset) ^ key)
        key = (key * MULTIPLIER + increment) & 0xFFFFFFFF
    zeros = preview.count(0)
    printable = sum(byte == 0 or 0x20 <= byte < 0x7F for byte in preview)
    known = 200 if preview[:4] == b"oEbN" else 0
    return zeros + printable + known


def derive_state(data: bytes | bytearray) -> tuple[int, int, int, int, int, int]:
    return derive_state_for_block(data, 0, REGION_OFFSET)


def derive_state_for_block(
    data: bytes | bytearray, header_offset: int, region_offset: int
) -> tuple[int, int, int, int, int, int]:
    candidates = []
    for index in range(12):
        state = derive_state_at_header(data, header_offset, index)
        candidates.append(
            (_preview_score_region(data, region_offset, state[3], state[4]), index, state)
        )
    _, index, state = max(candidates)
    return index, *state


def transform(data: bytearray, index: int | None = None) -> tuple[int, int, int]:
    if len(data) < REGION_OFFSET + REGION_SIZE:
        raise ValueError("Save is too short for the encrypted region")

    if index is None:
        index, _, _, _, key, increment = derive_state(data)
    else:
        _, _, _, key, increment = derive_state_at(data, index)
    initial_key = key
    for offset in range(REGION_OFFSET, REGION_OFFSET + REGION_SIZE, 4):
        value = u32(data, offset) ^ key
        struct.pack_into("<I", data, offset, value)
        key = (key * MULTIPLIER + increment) & 0xFFFFFFFF
    return index, initial_key, increment


def transform_block(
    data: bytearray,
    header_offset: int,
    region_offset: int,
    region_size: int,
    index: int | None = None,
) -> tuple[int, int, int]:
    if len(data) < region_offset + region_size:
        raise ValueError("Save is too short for the requested encrypted block")
    if index is None:
        index, _, _, _, key, increment = derive_state_for_block(
            data, header_offset, region_offset
        )
    else:
        _, _, _, key, increment = derive_state_at_header(data, header_offset, index)
    initial_key = key
    for offset in range(region_offset, region_offset + region_size, 4):
        struct.pack_into("<I", data, offset, u32(data, offset) ^ key)
        key = (key * MULTIPLIER + increment) & 0xFFFFFFFF
    return index, initial_key, increment


def main() -> None:
    parser = argparse.ArgumentParser(description="Transform an MGS Peace Walker PC save")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--index", type=int, choices=range(12))
    parser.add_argument(
        "--all-blocks",
        action="store_true",
        help="also transform the independent second PC STW block",
    )
    args = parser.parse_args()

    data = bytearray(args.input.read_bytes())
    if args.index is None:
        index, seed_a, seed_b, seed_c, _, _ = derive_state(data)
    else:
        index = args.index
        seed_a, seed_b, seed_c, _, _ = derive_state_at(data, index)
    _, key, increment = transform(data, index)
    block2 = None
    if args.all_blocks:
        block2 = transform_block(
            data,
            BLOCK2_HEADER_OFFSET,
            BLOCK2_REGION_OFFSET,
            BLOCK2_PC_REGION_SIZE,
        )
    args.output.write_bytes(data)
    print(f"header index: {index}")
    print(f"seed inputs: {seed_a:08X} {seed_b:08X} {seed_c:08X}")
    print(f"start key:   {key:08X}")
    print(f"increment:   {increment:08X}")
    if block2 is not None:
        print(f"block 2 index: {block2[0]}")
        print(f"block 2 key:   {block2[1]:08X}")
        print(f"block 2 incr:  {block2[2]:08X}")
    print(f"wrote:       {args.output}")


if __name__ == "__main__":
    main()
