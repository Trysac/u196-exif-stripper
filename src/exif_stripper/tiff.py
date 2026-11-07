"""TIFF IFD parser for orientation tag (0x0112) and GPSInfo tag (0x8825)."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

KindLiteral = Literal[
    "exif",
    "xmp",
    "iptc",
    "icc",
    "comment",
    "text",
    "time",
    "app",
    "trailer",
]


@dataclass(frozen=True)
class MetadataBlock:
    """Information about a detected metadata block in an image container."""

    kind: KindLiteral
    offset: int
    size: int
    has_gps: bool


MAX_IFD_ENTRIES = 1000
MAX_RECURSION_DEPTH = 10


def parse_tiff(data: bytes) -> tuple[int | None, bool]:
    """Parse a TIFF header and IFDs to extract Orientation tag and GPSInfo existence.

    Returns:
        tuple of (orientation: int | None, has_gps: bool)
        On any malformed structure, returns (None, False) without raising.
    """
    if len(data) < 8:
        return None, False

    endian_sig = data[:2]
    if endian_sig == b"II":
        endian = "<"
    elif endian_sig == b"MM":
        endian = ">"
    else:
        return None, False

    try:
        (magic,) = struct.unpack(f"{endian}H", data[2:4])
        if magic != 42:
            return None, False
        (first_ifd_offset,) = struct.unpack(f"{endian}I", data[4:8])
    except struct.error:
        return None, False

    visited_offsets: set[int] = set()
    orientation: int | None = None
    has_gps = False

    curr_offset = first_ifd_offset
    depth = 0

    while curr_offset != 0 and depth < MAX_RECURSION_DEPTH:
        if curr_offset in visited_offsets:
            break
        visited_offsets.add(curr_offset)
        depth += 1

        if curr_offset + 2 > len(data):
            break

        try:
            (num_entries,) = struct.unpack(f"{endian}H", data[curr_offset : curr_offset + 2])
        except struct.error:
            break

        if num_entries > MAX_IFD_ENTRIES:
            break

        entry_offset = curr_offset + 2
        if entry_offset + num_entries * 12 > len(data):
            break

        for _ in range(num_entries):
            try:
                tag, tag_type, _count, val_or_offset = struct.unpack(
                    f"{endian}HHI4s",
                    data[entry_offset : entry_offset + 12],
                )
            except struct.error:
                break

            # Tag 0x0112: Orientation (SHORT)
            if tag == 0x0112 and orientation is None:
                try:
                    if tag_type == 3:  # SHORT
                        (val,) = struct.unpack(f"{endian}H", val_or_offset[:2])
                        orientation = val
                    elif tag_type == 4:  # LONG
                        (val,) = struct.unpack(f"{endian}I", val_or_offset)
                        orientation = val
                except struct.error:
                    pass

            # Tag 0x8825: GPSInfo IFD pointer (LONG or SHORT)
            if tag == 0x8825:
                has_gps = True

            entry_offset += 12

        next_ifd_ptr_offset = entry_offset
        if next_ifd_ptr_offset + 4 > len(data):
            break

        try:
            (curr_offset,) = struct.unpack(
                f"{endian}I", data[next_ifd_ptr_offset : next_ifd_ptr_offset + 4]
            )
        except struct.error:
            break

    return orientation, has_gps
