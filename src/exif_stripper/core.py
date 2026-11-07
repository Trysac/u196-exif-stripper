"""Core stripping, parsing, and inspection functions."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Literal

from .tiff import MetadataBlock, parse_tiff

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
FormatLiteral = Literal["jpeg", "png", "webp"]
ErrorCodeLiteral = Literal["input_too_large", "unsupported_format", "corrupt"]

DEFAULT_MAX_BYTES: int = 100_000_000


class ExifStripError(Exception):
    """Base exception raised for stripping or inspection errors."""

    def __init__(self, code: ErrorCodeLiteral, message: str) -> None:
        truncated = message[:200]
        super().__init__(truncated)
        self.code: ErrorCodeLiteral = code
        self.message: str = truncated


@dataclass(frozen=True)
class Removed:
    """Record of a metadata segment or chunk removed from the image."""

    kind: KindLiteral
    offset: int
    size: int


@dataclass(frozen=True)
class StripResult:
    """Result of metadata removal."""

    data: bytes
    format: FormatLiteral
    removed: tuple[Removed, ...]
    orientation: int | None


def _detect_format(data: bytes) -> FormatLiteral:
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise ExifStripError("unsupported_format", "Image format signature not recognized")


def inspect(data: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES) -> list[MetadataBlock]:
    """Inspect image bytes and enumerate metadata blocks without altering pixels."""
    if len(data) > max_bytes:
        raise ExifStripError("input_too_large", f"Input size {len(data)} exceeds {max_bytes} limit")

    fmt = _detect_format(data)
    if fmt == "jpeg":
        return _inspect_jpeg(data)
    if fmt == "png":
        return _inspect_png(data)
    return _inspect_webp(data)


def strip(data: bytes, *, keep_icc: bool = True, max_bytes: int = DEFAULT_MAX_BYTES) -> StripResult:
    """Strip metadata from a JPEG, PNG, or WebP container."""
    if len(data) > max_bytes:
        raise ExifStripError("input_too_large", f"Input size {len(data)} exceeds {max_bytes} limit")

    fmt = _detect_format(data)
    if fmt == "jpeg":
        return _strip_jpeg(data, keep_icc=keep_icc)
    if fmt == "png":
        return _strip_png(data, keep_icc=keep_icc)
    return _strip_webp(data, keep_icc=keep_icc)


# --- JPEG Processing ---


def _inspect_jpeg(data: bytes) -> list[MetadataBlock]:
    blocks: list[MetadataBlock] = []
    idx = 2  # skip initial SOI (\xff\xd8)
    n = len(data)

    while idx < n:
        if data[idx] != 0xFF:
            raise ExifStripError("corrupt", f"Expected marker prefix 0xFF at {idx}")
        # Skip fill bytes (0xFF)
        while idx < n and data[idx] == 0xFF:
            idx += 1
        if idx >= n:
            raise ExifStripError("corrupt", "Truncated JPEG before marker identifier")

        marker = data[idx]
        marker_offset = idx - 1
        idx += 1

        # Standalone markers
        if marker in (0xD8, 0xD9) or (0xD0 <= marker <= 0xD7) or marker == 0x01:
            if marker == 0xD9:  # EOI
                if idx < n:
                    blocks.append(
                        MetadataBlock(kind="trailer", offset=idx, size=n - idx, has_gps=False)
                    )
                break
            continue

        if idx + 2 > n:
            raise ExifStripError("corrupt", f"Segment length truncated at {idx}")
        (seg_len,) = struct.unpack(">H", data[idx : idx + 2])
        if seg_len < 2 or idx + seg_len > n:
            raise ExifStripError("corrupt", f"Segment length {seg_len} exceeds data boundaries")

        payload = data[idx + 2 : idx + seg_len]
        total_seg_len = (idx + seg_len) - marker_offset

        if marker == 0xDA:  # SOS (Start of Scan)
            idx += seg_len
            # Scan for EOI
            found_eoi = False
            while idx < n:
                if data[idx] == 0xFF:
                    # Check following byte
                    peek = idx + 1
                    while peek < n and data[peek] == 0xFF:
                        peek += 1
                    if peek < n:
                        code = data[peek]
                        if code == 0xD9:  # EOI
                            found_eoi = True
                            idx = peek + 1
                            if idx < n:
                                blocks.append(
                                    MetadataBlock(
                                        kind="trailer", offset=idx, size=n - idx, has_gps=False
                                    )
                                )
                            break
                        elif code == 0x00 or (0xD0 <= code <= 0xD7):
                            idx = peek + 1
                            continue
                        else:
                            idx = peek + 1
                            continue
                idx += 1
            if not found_eoi:
                raise ExifStripError("corrupt", "Missing EOI marker after SOS")
            break

        kind, has_gps = _classify_jpeg_marker(marker, payload)
        if kind is not None:
            blocks.append(
                MetadataBlock(kind=kind, offset=marker_offset, size=total_seg_len, has_gps=has_gps)
            )

        idx += seg_len

    return blocks


def _classify_jpeg_marker(marker: int, payload: bytes) -> tuple[KindLiteral | None, bool]:
    # APP0: JFIF / JFXX -> kept
    # APP14: Adobe -> kept
    # APP1: Exif or XMP
    # APP2: ICC_PROFILE (kept or icc) or app
    # APP13: IPTC / Photoshop
    # APP3-APP12, APP15: app
    # COM: comment
    if marker == 0xFE:
        return ("comment", False)
    if marker == 0xE0:
        return (None, False)  # APP0 is kept
    if marker == 0xEE:
        return (None, False)  # APP14 is kept
    if marker == 0xE1:
        if payload.startswith(b"Exif\x00\x00"):
            _, has_gps = parse_tiff(payload[6:])
            return ("exif", has_gps)
        if payload.startswith(b"http://ns.adobe.com/xap/1.0/\x00"):
            return ("xmp", False)
        return ("app", False)
    if marker == 0xE2:
        if payload.startswith(b"ICC_PROFILE\x00"):
            return ("icc", False)
        return ("app", False)
    if marker == 0xED:
        return ("iptc", False)
    if (0xE3 <= marker <= 0xEC) or marker == 0xEF:
        return ("app", False)
    return (None, False)


def _strip_jpeg(data: bytes, *, keep_icc: bool) -> StripResult:
    n = len(data)
    if n < 2 or data[:2] != b"\xff\xd8":
        raise ExifStripError("unsupported_format", "Not a JPEG")

    out = bytearray(b"\xff\xd8")
    removed: list[Removed] = []
    found_orientation: int | None = None
    idx = 2

    while idx < n:
        if data[idx] != 0xFF:
            raise ExifStripError("corrupt", f"Expected marker at {idx}")
        while idx < n and data[idx] == 0xFF:
            idx += 1
        if idx >= n:
            raise ExifStripError("corrupt", "Truncated JPEG before marker identifier")

        marker = data[idx]
        marker_offset = idx - 1
        idx += 1

        if marker in (0xD8, 0xD9) or (0xD0 <= marker <= 0xD7) or marker == 0x01:
            out.extend(b"\xff")
            out.append(marker)
            if marker == 0xD9:  # EOI
                if idx < n:
                    removed.append(Removed(kind="trailer", offset=idx, size=n - idx))
                break
            continue

        if idx + 2 > n:
            raise ExifStripError("corrupt", f"Segment length truncated at {idx}")
        (seg_len,) = struct.unpack(">H", data[idx : idx + 2])
        if seg_len < 2 or idx + seg_len > n:
            raise ExifStripError("corrupt", f"Segment length {seg_len} exceeds data boundaries")

        payload = data[idx + 2 : idx + seg_len]
        total_seg_len = (idx + seg_len) - marker_offset
        seg_bytes = data[marker_offset : idx + seg_len]

        if marker == 0xDA:  # SOS
            out.extend(seg_bytes)
            idx += seg_len
            sos_start = idx
            found_eoi = False
            while idx < n:
                if data[idx] == 0xFF:
                    peek = idx + 1
                    while peek < n and data[peek] == 0xFF:
                        peek += 1
                    if peek < n:
                        code = data[peek]
                        if code == 0xD9:  # EOI
                            found_eoi = True
                            out.extend(data[sos_start : peek + 1])
                            idx = peek + 1
                            if idx < n:
                                removed.append(Removed(kind="trailer", offset=idx, size=n - idx))
                            break
                        elif code == 0x00 or (0xD0 <= code <= 0xD7):
                            idx = peek + 1
                            continue
                        else:
                            idx = peek + 1
                            continue
                idx += 1
            if not found_eoi:
                raise ExifStripError("corrupt", "Missing EOI marker after SOS")
            break

        kind, _ = _classify_jpeg_marker(marker, payload)
        if kind == "exif":
            if payload.startswith(b"Exif\x00\x00"):
                orient, _ = parse_tiff(payload[6:])
                if found_orientation is None and orient is not None:
                    found_orientation = orient
            removed.append(Removed(kind="exif", offset=marker_offset, size=total_seg_len))
        elif kind == "icc":
            if keep_icc:
                out.extend(seg_bytes)
            else:
                removed.append(Removed(kind="icc", offset=marker_offset, size=total_seg_len))
        elif kind in ("xmp", "iptc", "comment", "app"):
            removed.append(Removed(kind=kind, offset=marker_offset, size=total_seg_len))
        else:
            # Keep segment
            out.extend(seg_bytes)

        idx += seg_len

    return StripResult(
        data=bytes(out),
        format="jpeg",
        removed=tuple(removed),
        orientation=found_orientation,
    )


# --- PNG Processing ---

PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _inspect_png(data: bytes) -> list[MetadataBlock]:
    blocks: list[MetadataBlock] = []
    n = len(data)
    idx = len(PNG_HEADER)

    while idx < n:
        if idx + 8 > n:
            raise ExifStripError("corrupt", "Truncated PNG chunk header")
        length = struct.unpack(">I", data[idx : idx + 4])[0]
        chunk_type = data[idx + 4 : idx + 8]
        total_chunk_len = 8 + length + 4
        if idx + total_chunk_len > n:
            raise ExifStripError(
                "corrupt",
                f"PNG chunk {chunk_type.decode('latin1', errors='replace')} length overflows",
            )

        expected_crc = struct.unpack(">I", data[idx + 8 + length : idx + total_chunk_len])[0]
        actual_crc = zlib.crc32(data[idx + 4 : idx + 8 + length])
        if expected_crc != actual_crc:
            raise ExifStripError(
                "corrupt",
                f"PNG CRC mismatch in chunk {chunk_type.decode('latin1', errors='replace')}",
            )

        chunk_data = data[idx + 8 : idx + 8 + length]

        if chunk_type == b"eXIf":
            _, has_gps = parse_tiff(chunk_data)
            blocks.append(
                MetadataBlock(kind="exif", offset=idx, size=total_chunk_len, has_gps=has_gps)
            )
        elif chunk_type in (b"tEXt", b"zTXt", b"iTXt"):
            blocks.append(
                MetadataBlock(kind="text", offset=idx, size=total_chunk_len, has_gps=False)
            )
        elif chunk_type == b"tIME":
            blocks.append(
                MetadataBlock(kind="time", offset=idx, size=total_chunk_len, has_gps=False)
            )
        elif chunk_type == b"iCCP":
            blocks.append(
                MetadataBlock(kind="icc", offset=idx, size=total_chunk_len, has_gps=False)
            )

        idx += total_chunk_len
        if chunk_type == b"IEND":
            if idx < n:
                blocks.append(
                    MetadataBlock(kind="trailer", offset=idx, size=n - idx, has_gps=False)
                )
            break

    return blocks


def _strip_png(data: bytes, *, keep_icc: bool) -> StripResult:
    n = len(data)
    idx = len(PNG_HEADER)
    out = bytearray(PNG_HEADER)
    removed: list[Removed] = []
    found_orientation: int | None = None

    while idx < n:
        if idx + 8 > n:
            raise ExifStripError("corrupt", "Truncated PNG chunk header")
        length = struct.unpack(">I", data[idx : idx + 4])[0]
        chunk_type = data[idx + 4 : idx + 8]
        total_chunk_len = 8 + length + 4
        if idx + total_chunk_len > n:
            raise ExifStripError("corrupt", "PNG chunk length overflows")

        expected_crc = struct.unpack(">I", data[idx + 8 + length : idx + total_chunk_len])[0]
        actual_crc = zlib.crc32(data[idx + 4 : idx + 8 + length])
        if expected_crc != actual_crc:
            raise ExifStripError("corrupt", "PNG CRC mismatch")

        chunk_bytes = data[idx : idx + total_chunk_len]
        chunk_data = data[idx + 8 : idx + 8 + length]

        if chunk_type == b"eXIf":
            orient, _ = parse_tiff(chunk_data)
            if found_orientation is None and orient is not None:
                found_orientation = orient
            removed.append(Removed(kind="exif", offset=idx, size=total_chunk_len))
        elif chunk_type in (b"tEXt", b"zTXt", b"iTXt"):
            removed.append(Removed(kind="text", offset=idx, size=total_chunk_len))
        elif chunk_type == b"tIME":
            removed.append(Removed(kind="time", offset=idx, size=total_chunk_len))
        elif chunk_type == b"iCCP":
            if keep_icc:
                out.extend(chunk_bytes)
            else:
                removed.append(Removed(kind="icc", offset=idx, size=total_chunk_len))
        else:
            out.extend(chunk_bytes)

        idx += total_chunk_len
        if chunk_type == b"IEND":
            if idx < n:
                removed.append(Removed(kind="trailer", offset=idx, size=n - idx))
            break

    return StripResult(
        data=bytes(out),
        format="png",
        removed=tuple(removed),
        orientation=found_orientation,
    )


# --- WebP Processing ---


def _inspect_webp(data: bytes) -> list[MetadataBlock]:
    blocks: list[MetadataBlock] = []
    n = len(data)
    if n < 12:
        raise ExifStripError("corrupt", "WebP data too short")

    idx = 12
    while idx < n:
        if idx + 8 > n:
            raise ExifStripError("corrupt", "Truncated WebP chunk")
        chunk_id = data[idx : idx + 4]
        chunk_len = struct.unpack("<I", data[idx + 4 : idx + 8])[0]
        payload_start = idx + 8
        payload_end = payload_start + chunk_len
        if payload_end > n:
            raise ExifStripError("corrupt", "WebP chunk overflows container")
        pad = chunk_len % 2
        chunk_full_size = 8 + chunk_len + pad

        chunk_payload = data[payload_start:payload_end]
        if chunk_id == b"EXIF":
            # May start with 'Exif\0\0' or directly TIFF
            tiff_data = (
                chunk_payload[6:] if chunk_payload.startswith(b"Exif\x00\x00") else chunk_payload
            )
            _, has_gps = parse_tiff(tiff_data)
            blocks.append(
                MetadataBlock(kind="exif", offset=idx, size=chunk_full_size, has_gps=has_gps)
            )
        elif chunk_id == b"XMP ":
            blocks.append(
                MetadataBlock(kind="xmp", offset=idx, size=chunk_full_size, has_gps=False)
            )
        elif chunk_id == b"ICCP":
            blocks.append(
                MetadataBlock(kind="icc", offset=idx, size=chunk_full_size, has_gps=False)
            )

        idx += chunk_full_size

    return blocks


def _strip_webp(data: bytes, *, keep_icc: bool) -> StripResult:
    n = len(data)
    if n < 12:
        raise ExifStripError("corrupt", "WebP data too short")

    removed: list[Removed] = []
    found_orientation: int | None = None
    idx = 12

    # First pass: inspect chunks, detect VP8X, check if EXIF/XMP/ICCP need removal
    chunks: list[
        tuple[bytes, bytes, int, int]
    ] = []  # (id, raw_chunk_bytes, original_offset, total_size)
    vp8x_index: int | None = None

    while idx < n:
        if idx + 8 > n:
            raise ExifStripError("corrupt", "Truncated WebP chunk")
        chunk_id = data[idx : idx + 4]
        chunk_len = struct.unpack("<I", data[idx + 4 : idx + 8])[0]
        payload_start = idx + 8
        payload_end = payload_start + chunk_len
        if payload_end > n:
            raise ExifStripError("corrupt", "WebP chunk overflows container")
        pad = chunk_len % 2
        full_chunk_end = payload_end + pad
        if full_chunk_end > n:
            # If pad is missing at EOF, allow but cap to n
            full_chunk_end = n
        total_chunk_len = full_chunk_end - idx
        chunk_bytes = data[idx:full_chunk_end]
        payload = data[payload_start:payload_end]

        if chunk_id == b"VP8X":
            vp8x_index = len(chunks)
            chunks.append((chunk_id, chunk_bytes, idx, total_chunk_len))
        elif chunk_id == b"EXIF":
            tiff_data = payload[6:] if payload.startswith(b"Exif\x00\x00") else payload
            orient, _ = parse_tiff(tiff_data)
            if found_orientation is None and orient is not None:
                found_orientation = orient
            removed.append(Removed(kind="exif", offset=idx, size=total_chunk_len))
        elif chunk_id == b"XMP ":
            removed.append(Removed(kind="xmp", offset=idx, size=total_chunk_len))
        elif chunk_id == b"ICCP":
            if keep_icc:
                chunks.append((chunk_id, chunk_bytes, idx, total_chunk_len))
            else:
                removed.append(Removed(kind="icc", offset=idx, size=total_chunk_len))
        else:
            chunks.append((chunk_id, chunk_bytes, idx, total_chunk_len))

        idx = full_chunk_end

    # If VP8X exists, update flags
    if vp8x_index is not None:
        _, vp8x_bytes, v_offset, v_len = chunks[vp8x_index]
        if len(vp8x_bytes) >= 16:
            vp8x_ba = bytearray(vp8x_bytes)
            flags = vp8x_ba[8]
            # Clear EXIF (0x08), XMP (0x04)
            flags &= ~0x08
            flags &= ~0x04
            if not keep_icc:
                flags &= ~0x20  # ICC bit
            vp8x_ba[8] = flags
            chunks[vp8x_index] = (b"VP8X", bytes(vp8x_ba), v_offset, v_len)

    # Assemble payload
    body = bytearray()
    for _, c_bytes, _, _ in chunks:
        body.extend(c_bytes)

    new_riff_size = 4 + len(body)  # 'WEBP' (4 bytes) + chunks
    header = b"RIFF" + struct.pack("<I", new_riff_size) + b"WEBP"
    output_bytes = header + bytes(body)

    return StripResult(
        data=output_bytes,
        format="webp",
        removed=tuple(removed),
        orientation=found_orientation,
    )
