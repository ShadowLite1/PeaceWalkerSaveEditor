from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

from save_cipher import derive_state, filename_checksum, transform


GMP_OFFSET = 0xB570


def _signed_byte_sum(data: bytes | bytearray, start: int, end: int) -> int:
    return sum(value if value < 0x80 else value - 0x100 for value in data[start:end]) & 0xFFFFFFFF


def update_internal_checks(data: bytearray) -> None:
    """Rebuild the checks performed by the game's save-list validator."""
    slot_number = struct.unpack_from("<I", data, 0x178)[0]
    header_a = struct.unpack_from("<I", data, 0x160)[0]
    header_b = struct.unpack_from("<I", data, 0x164)[0]
    check_1 = ((((header_b ^ header_a) & 0xFFFFFFFF) << 32) | slot_number) ^ 0x3F000000E4
    struct.pack_into("<Q", data, 0x168, check_1)

    block_a = _signed_byte_sum(data, 0xBD7C, 0xE2FC)
    block_b = _signed_byte_sum(data, 0xE2FC, 0x1127C)
    short_sum = sum(struct.unpack_from("<7h", data, 0x14104)) & 0xFFFFFFFF
    check_2 = ((short_sum << 32) | ((block_a ^ block_b) & 0xFFFFFFFF)) ^ 0xCD0000007C
    struct.pack_into("<Q", data, 0x170, check_2)

    # These three CRCs cover the first decrypted payload. The fourth CRC belongs
    # to a separate encrypted block which this GMP-only editor does not alter.
    for start, end, stored_at in (
        (0x44, 0x1C1C0, 0x38),
        (0x1C1C0, 0x1F9C0, 0x3C),
        (0x1F9C0, 0x38828, 0x30),
    ):
        struct.pack_into("<I", data, stored_at, zlib.crc32(data[start:end]) & 0xFFFFFFFF)


def main() -> None:
    parser = argparse.ArgumentParser(description="Experimental MGS Peace Walker PC save editor")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--gmp", type=int, required=True)
    parser.add_argument(
        "--preserve-filename-checksum",
        action="store_true",
        help="Keep the input file's XOR16 checksum by adjusting the final padding word",
    )
    args = parser.parse_args()

    if not 0 <= args.gmp <= 0xFFFFFFFF:
        raise ValueError("GMP must fit in an unsigned 32-bit integer")

    data = bytearray(args.input.read_bytes())
    original_checksum = filename_checksum(data)
    index, *_ = derive_state(data)
    transform(data, index)

    previous = struct.unpack_from("<I", data, GMP_OFFSET)[0]
    struct.pack_into("<I", data, GMP_OFFSET, args.gmp)
    update_internal_checks(data)

    transform(data, index)
    if args.preserve_filename_checksum:
        # The final word is outside the encrypted save region and is zero padding
        # in every sample examined. XOR compensation keeps the original STW name
        # valid without changing the decrypted payload.
        if data[-2:] != b"\x00\x00":
            raise ValueError("Final word is not padding; refusing checksum compensation")
        compensation = filename_checksum(data) ^ original_checksum
        struct.pack_into("<H", data, len(data) - 2, compensation)
    args.output.write_bytes(data)
    checksum = filename_checksum(data)
    print(f"header index: {index}")
    print(f"GMP candidate at 0x{GMP_OFFSET:X}: {previous} -> {args.gmp}")
    print(f"filename checksum: {checksum:04x}")
    print(f"suggested name: STW000000{checksum:04x}01")
    print(f"wrote: {args.output}")


if __name__ == "__main__":
    main()
