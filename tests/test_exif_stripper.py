"""Unit tests for exif_stripper."""

from __future__ import annotations

import struct
import zlib

import pytest

from exif_stripper import (
    ExifStripError,
    __version__,
    inspect,
    strip,
)
from exif_stripper.__main__ import main
from exif_stripper.tiff import parse_tiff


def build_tiff_payload(
    endian: str, orientation: int | None = None, with_gps: bool = False
) -> bytes:
    """Helper to construct a minimal TIFF EXIF header with Orientation and GPS tags."""
    endian_char = "<" if endian == "II" else ">"
    sig = endian.encode("ascii")
    magic = struct.pack(f"{endian_char}H", 42)
    first_ifd_offset = struct.pack(f"{endian_char}I", 8)

    entries: list[bytes] = []
    if orientation is not None:
        # Tag 0x0112, SHORT (3), count 1, value
        val_bytes = struct.pack(f"{endian_char}H", orientation) + b"\x00\x00"
        entries.append(struct.pack(f"{endian_char}HHI", 0x0112, 3, 1) + val_bytes)
    if with_gps:
        # Tag 0x8825 (GPSInfo), LONG (4), count 1, offset 0
        entries.append(struct.pack(f"{endian_char}HHI", 0x8825, 4, 1) + b"\x00\x00\x00\x00")

    num_entries = struct.pack(f"{endian_char}H", len(entries))
    next_ifd = struct.pack(f"{endian_char}I", 0)
    return sig + magic + first_ifd_offset + num_entries + b"".join(entries) + next_ifd


def build_jpeg_criterion_1() -> bytes:
    """Build JPEG as specified in acceptance criterion 1:
    SOI + APP0 'JFIF\0' + APP1 'Exif\0\0' (TIFF with GPSInfo 0x8825) + COM + SOS segment & entropy + EOI.
    """
    soi = b"\xff\xd8"
    app0_payload = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    app0 = b"\xff\xe0" + struct.pack(">H", len(app0_payload) + 2) + app0_payload

    tiff_data = build_tiff_payload("II", orientation=1, with_gps=True)
    app1_payload = b"Exif\x00\x00" + tiff_data
    app1 = b"\xff\xe1" + struct.pack(">H", len(app1_payload) + 2) + app1_payload

    com_payload = b"a comment"
    com = b"\xff\xfe" + struct.pack(">H", len(com_payload) + 2) + com_payload

    sos_payload = b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    sos_header = b"\xff\xda" + struct.pack(">H", len(sos_payload) + 2) + sos_payload
    entropy = b"\x12\x34\x56\xff\x00\x78\x9a"
    eoi = b"\xff\xd9"

    return soi + app0 + app1 + com + sos_header + entropy + eoi


def build_png_criterion_4() -> bytes:
    """PNG with IHDR, tEXt, eXIf, iTXt, tIME, IDAT, and IEND."""
    sig = b"\x89PNG\r\n\x1a\n"

    def make_chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
        length = struct.pack(">I", len(chunk_data))
        crc = struct.pack(">I", zlib.crc32(chunk_type + chunk_data))
        return length + chunk_type + chunk_data + crc

    ihdr_data = struct.pack(">IIBBBBB", 10, 10, 8, 2, 0, 0, 0)
    ihdr = make_chunk(b"IHDR", ihdr_data)
    text1 = make_chunk(b"tEXt", b"Author\x00John")
    exif_data = build_tiff_payload("MM", orientation=3, with_gps=False)
    exif = make_chunk(b"eXIf", exif_data)
    itxt = make_chunk(b"iTXt", b"Description\x00\x00\x00\x00\x00Text")
    time_data = struct.pack(">HBBBBB", 2024, 5, 1, 12, 0, 0)
    time = make_chunk(b"tIME", time_data)
    idat = make_chunk(b"IDAT", zlib.compress(b"pixeldata"))
    iend = make_chunk(b"IEND", b"")

    return sig + ihdr + text1 + exif + itxt + time + idat + iend


def build_webp_criterion_5() -> bytes:
    """WebP with VP8X flags 0x0C and EXIF and 'XMP ' chunks."""
    # VP8X chunk length = 10
    # Flags byte at offset 0 of payload = 0x0C (EXIF 0x08 | XMP 0x04)
    vp8x_payload = b"\x0c\x00\x00\x00\x09\x00\x00\x09\x00\x00"
    vp8x = b"VP8X" + struct.pack("<I", len(vp8x_payload)) + vp8x_payload

    # EXIF chunk
    exif_tiff = build_tiff_payload("II", orientation=1)
    exif_payload = b"Exif\x00\x00" + exif_tiff
    pad_exif = b"\x00" if len(exif_payload) % 2 == 1 else b""
    exif = b"EXIF" + struct.pack("<I", len(exif_payload)) + exif_payload + pad_exif

    # XMP chunk (odd-sized to verify padding preservation)
    xmp_payload = b"<x:xmpmeta/>1"  # length 14
    pad_xmp = b"\x00" if len(xmp_payload) % 2 == 1 else b""
    xmp = b"XMP " + struct.pack("<I", len(xmp_payload)) + xmp_payload + pad_xmp

    # Image chunk (VP8)
    vp8_payload = b"\x00" * 10
    vp8 = b"VP8 " + struct.pack("<I", len(vp8_payload)) + vp8_payload

    body = vp8x + exif + xmp + vp8
    riff_size = 4 + len(body)
    return b"RIFF" + struct.pack("<I", riff_size) + b"WEBP" + body


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_criterion_1_jpeg() -> None:
    # Criterion 1: For a JPEG built as SOI + APP0 'JFIF\0' + APP1 'Exif\0\0' (TIFF with a GPSInfo 0x8825 entry)
    # + COM + the SOS segment and entropy data + EOI, strip(data).data == SOI + APP0 + SOS..EOI bytes,
    # removed kinds == ('exif', 'comment') and inspect(data) reports has_gps True for the exif block.
    raw = build_jpeg_criterion_1()
    res = strip(raw)

    # Check removed kinds
    assert tuple(r.kind for r in res.removed) == ("exif", "comment")
    assert res.format == "jpeg"
    assert res.orientation == 1

    # Inspect reports has_gps True
    ins = inspect(raw)
    exif_block = next(b for b in ins if b.kind == "exif")
    assert exif_block.has_gps is True

    # Check stripped data matches SOI + APP0 + SOS..EOI bytes
    soi = b"\xff\xd8"
    app0_payload = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    app0 = b"\xff\xe0" + struct.pack(">H", len(app0_payload) + 2) + app0_payload
    sos_payload = b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    sos_header = b"\xff\xda" + struct.pack(">H", len(sos_payload) + 2) + sos_payload
    entropy = b"\x12\x34\x56\xff\x00\x78\x9a"
    eoi = b"\xff\xd9"
    expected_data = soi + app0 + sos_header + entropy + eoi
    assert res.data == expected_data


def test_criterion_2_jpeg_segments() -> None:
    # Criterion 2: An APP2 'ICC_PROFILE\0' segment is kept with keep_icc=True and removed as 'icc' with keep_icc=False;
    # an APP14 'Adobe' segment is always kept; APP1 'http://ns.adobe.com/xap/1.0/\0' is removed as 'xmp'
    # and APP13 as 'iptc'; bytes b'XYZ' after EOI are removed as 'trailer'.
    soi = b"\xff\xd8"
    app2_payload = b"ICC_PROFILE\x00icc_data"
    app2 = b"\xff\xe2" + struct.pack(">H", len(app2_payload) + 2) + app2_payload

    app14_payload = b"Adobe\x00data"
    app14 = b"\xff\xee" + struct.pack(">H", len(app14_payload) + 2) + app14_payload

    xmp_payload = b"http://ns.adobe.com/xap/1.0/\x00<xmp/>"
    app1_xmp = b"\xff\xe1" + struct.pack(">H", len(xmp_payload) + 2) + xmp_payload

    iptc_payload = b"Photoshop 3.0\x00"
    app13 = b"\xff\xed" + struct.pack(">H", len(iptc_payload) + 2) + iptc_payload

    sos = b"\xff\xda\x00\x02\xff\xd9"
    trailer = b"XYZ"

    full_jpeg = soi + app2 + app14 + app1_xmp + app13 + sos + trailer

    # Test with keep_icc = True
    res_keep = strip(full_jpeg, keep_icc=True)
    kinds_keep = tuple(r.kind for r in res_keep.removed)
    assert kinds_keep == ("xmp", "iptc", "trailer")
    assert app2 in res_keep.data
    assert app14 in res_keep.data
    assert not res_keep.data.endswith(b"XYZ")

    # Test with keep_icc = False
    res_drop = strip(full_jpeg, keep_icc=False)
    kinds_drop = tuple(r.kind for r in res_drop.removed)
    assert kinds_drop == ("icc", "xmp", "iptc", "trailer")
    assert app2 not in res_drop.data
    assert app14 in res_drop.data

    # Test inspection
    ins = inspect(full_jpeg)
    ins_kinds = [b.kind for b in ins]
    assert ins_kinds == ["icc", "xmp", "iptc", "trailer"]


def test_criterion_3_tiff_orientation() -> None:
    # Criterion 3: An EXIF block whose IFD0 holds Orientation (tag 0x0112) = 6 gives orientation == 6
    # for both 'II' and 'MM' byte orders; a malformed TIFF block is still removed and gives orientation None.
    for endian in ["II", "MM"]:
        tiff_data = build_tiff_payload(endian, orientation=6)
        app1 = b"\xff\xe1" + struct.pack(">H", len(tiff_data) + 8) + b"Exif\x00\x00" + tiff_data
        jpeg = b"\xff\xd8" + app1 + b"\xff\xda\x00\x02\xff\xd9"
        res = strip(jpeg)
        assert res.orientation == 6

    # Malformed TIFF block
    malformed_app1 = b"\xff\xe1\x00\x0aExif\x00\x00XX"
    jpeg_malformed = b"\xff\xd8" + malformed_app1 + b"\xff\xda\x00\x02\xff\xd9"
    res_malformed = strip(jpeg_malformed)
    assert res_malformed.orientation is None
    assert len(res_malformed.removed) == 1
    assert res_malformed.removed[0].kind == "exif"


def test_criterion_4_png() -> None:
    # Criterion 4: For a PNG with IHDR, tEXt, eXIf, iTXt, tIME, IDAT and IEND, the output keeps IHDR,
    # IDAT and IEND byte-exact in order, removes the others (kinds 'text', 'exif', 'text', 'time'),
    # and every output chunk CRC equals zlib.crc32(type + data); a wrong CRC raises ExifStripError with code 'corrupt'.
    raw_png = build_png_criterion_4()
    res = strip(raw_png)

    assert tuple(r.kind for r in res.removed) == ("text", "exif", "text", "time")
    assert res.orientation == 3
    assert res.format == "png"

    # Verify output has only IHDR, IDAT, IEND in order
    data = res.data
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    idx = 8
    chunk_types = []
    while idx < len(data):
        length = struct.unpack(">I", data[idx : idx + 4])[0]
        c_type = data[idx + 4 : idx + 8]
        c_data = data[idx + 8 : idx + 8 + length]
        (c_crc,) = struct.unpack(">I", data[idx + 8 + length : idx + 12 + length])
        assert c_crc == zlib.crc32(c_type + c_data)
        chunk_types.append(c_type)
        idx += 12 + length
    assert chunk_types == [b"IHDR", b"IDAT", b"IEND"]

    # Bad CRC
    bad_png = bytearray(raw_png)
    bad_png[len(raw_png) - 2] ^= 0xFF
    with pytest.raises(ExifStripError) as exc_info:
        strip(bytes(bad_png))
    assert exc_info.value.code == "corrupt"


def test_criterion_5_webp() -> None:
    # Criterion 5: For a WebP with VP8X flags 0x0C and EXIF and 'XMP ' chunks, the output has both chunks removed,
    # the VP8X flags byte equals 0x00, and the RIFF size field equals len(output) - 8; odd-sized chunks keep their pad byte.
    raw_webp = build_webp_criterion_5()
    res = strip(raw_webp)

    assert res.format == "webp"
    assert tuple(r.kind for r in res.removed) == ("exif", "xmp")

    # Verify RIFF size
    out = res.data
    (riff_size,) = struct.unpack("<I", out[4:8])
    assert riff_size == len(out) - 8

    # Verify VP8X chunk and flags
    assert out[12:16] == b"VP8X"
    vp8x_len = struct.unpack("<I", out[16:20])[0]
    vp8x_payload = out[20 : 20 + vp8x_len]
    assert vp8x_payload[0] == 0x00  # flags cleared

    # Verify EXIF and XMP are absent, VP8 is present
    assert b"EXIF" not in out
    assert b"XMP " not in out
    assert b"VP8 " in out


def test_criterion_6_idempotency() -> None:
    # Criterion 6: For the JPEG fixture of criterion 1, strip(strip(x).data).data == strip(x).data
    # with removed == () on the second pass, and an input without metadata returns data == input (same bytes).
    raw = build_jpeg_criterion_1()
    first_pass = strip(raw)
    second_pass = strip(first_pass.data)

    assert second_pass.data == first_pass.data
    assert second_pass.removed == ()

    # Clean PNG input
    clean_png = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 0)
        + b"IHDR"
        + struct.pack(">I", zlib.crc32(b"IHDR"))
        + struct.pack(">I", 0)
        + b"IEND"
        + struct.pack(">I", zlib.crc32(b"IEND"))
    )
    clean_res = strip(clean_png)
    assert clean_res.data == clean_png
    assert clean_res.removed == ()


def test_criterion_7_errors_and_limits() -> None:
    # Criterion 7: b'GIF89a' input raises ExifStripError with code 'unsupported_format';
    # a JPEG segment length running past the end raises code 'corrupt';
    # an IFD whose next-IFD offset points to itself terminates;
    # a 100_000_001-byte input raises code 'input_too_large'.
    with pytest.raises(ExifStripError) as exc_gif:
        strip(b"GIF89a")
    assert exc_gif.value.code == "unsupported_format"

    # JPEG segment running past end
    truncated_jpeg = b"\xff\xd8\xff\xe1\xff\xff\x00"
    with pytest.raises(ExifStripError) as exc_trunc:
        strip(truncated_jpeg)
    assert exc_trunc.value.code == "corrupt"

    # IFD offset points to itself
    loop_tiff = (
        b"II"
        + struct.pack("<H", 42)
        + struct.pack("<I", 8)
        + struct.pack("<H", 0)
        + struct.pack("<I", 8)
    )
    orient, gps = parse_tiff(loop_tiff)
    assert orient is None
    assert gps is False

    # 100_000_001 byte input limit
    huge_dummy = b"A" * 100_000_001
    with pytest.raises(ExifStripError) as exc_large:
        strip(huge_dummy)
    assert exc_large.value.code == "input_too_large"

    with pytest.raises(ExifStripError) as exc_large_ins:
        inspect(huge_dummy)
    assert exc_large_ins.value.code == "input_too_large"


def test_criterion_8_cli(tmp_path: pytest.TempPathFactory) -> None:
    # Criterion 8: CLI: main(['in.jpg', '-o', 'out.jpg']) writes the stripped file and returns 0,
    # main(['--check', 'in.jpg']) returns 1 when metadata is present and 0 when clean,
    # and without --in-place the input file is never modified.
    in_file = tmp_path / "in.jpg"
    out_file = tmp_path / "out.jpg"
    raw = build_jpeg_criterion_1()
    in_file.write_bytes(raw)

    # Check initial state with --check: returns 1
    ret = main([str(in_file), "--check"])
    assert ret == 1

    # Output to out_file
    ret = main([str(in_file), "-o", str(out_file)])
    assert ret == 0
    assert out_file.exists()
    # Input file was NOT modified
    assert in_file.read_bytes() == raw

    # Output file is clean: returns 0 with --check
    ret = main([str(out_file), "--check"])
    assert ret == 0

    # Test --in-place
    ret = main([str(in_file), "--in-place"])
    assert ret == 0
    assert in_file.read_bytes() != raw
    assert main([str(in_file), "--check"]) == 0


def test_cli_edge_cases(tmp_path: pytest.TempPathFactory) -> None:
    # Both --in-place and -o
    ret = main(["dummy.jpg", "--in-place", "-o", "other.jpg"])
    assert ret == 2

    # File not found
    ret = main(["non_existent_file.jpg"])
    assert ret == 2

    # Strip without -o or --in-place prints summary
    sample = tmp_path / "sample.png"
    sample.write_bytes(build_png_criterion_4())
    ret = main([str(sample)])
    assert ret == 0

    # Corrupt file
    bad_file = tmp_path / "bad.jpg"
    bad_file.write_bytes(b"\xff\xd8\xff\xe1\xff\xff")
    ret = main([str(bad_file), "--check"])
    assert ret == 2


def test_additional_coverage() -> None:
    # JPEG marker edge cases: fill bytes, standalone markers, MPF APP2, APP3
    soi = b"\xff\xd8"
    app2_non_icc = b"\xff\xe2\x00\x08MPF\x00\x01\x02"
    app3 = b"\xff\xe3\x00\x04XX"
    sos = b"\xff\xff\xda\x00\x02\xff\xd9"
    fill_jpeg = soi + app2_non_icc + app3 + sos
    res = strip(fill_jpeg)
    assert len(res.removed) == 2
    assert res.removed[0].kind == "app"
    assert res.removed[1].kind == "app"

    # JPEG missing EOI after SOS
    bad_sos = b"\xff\xd8\xff\xda\x00\x02\x12\x34"
    with pytest.raises(ExifStripError) as exc_sos:
        strip(bad_sos)
    assert exc_sos.value.code == "corrupt"

    # PNG with iCCP
    sig = b"\x89PNG\r\n\x1a\n"
    iccp_data = b"profile\x00\x00" + zlib.compress(b"icc_raw")
    iccp_chunk = (
        struct.pack(">I", len(iccp_data))
        + b"iCCP"
        + iccp_data
        + struct.pack(">I", zlib.crc32(b"iCCP" + iccp_data))
    )
    iend_chunk = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    png_iccp = sig + iccp_chunk + iend_chunk

    ins_iccp = inspect(png_iccp)
    assert ins_iccp[0].kind == "icc"

    # Keep ICC
    res_keep_icc = strip(png_iccp, keep_icc=True)
    assert len(res_keep_icc.removed) == 0

    # Drop ICC
    res_drop_icc = strip(png_iccp, keep_icc=False)
    assert len(res_drop_icc.removed) == 1
    assert res_drop_icc.removed[0].kind == "icc"

    # WebP with ICCP chunk
    iccp_body = b"ICCP" + struct.pack("<I", len(iccp_data)) + iccp_data
    if len(iccp_data) % 2 == 1:
        iccp_body += b"\x00"
    webp_iccp = b"RIFF" + struct.pack("<I", 4 + len(iccp_body)) + b"WEBP" + iccp_body
    ins_webp = inspect(webp_iccp)
    assert ins_webp[0].kind == "icc"

    res_webp_drop = strip(webp_iccp, keep_icc=False)
    assert len(res_webp_drop.removed) == 1
    assert res_webp_drop.removed[0].kind == "icc"

    res_webp_keep = strip(webp_iccp, keep_icc=True)
    assert len(res_webp_keep.removed) == 0

    # WebP corrupt riff
    with pytest.raises(ExifStripError):
        strip(b"RIFF1234WEBP\x00")
