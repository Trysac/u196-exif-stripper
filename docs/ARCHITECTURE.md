# Architecture

## Overview

`trysac-exif-stripper` strips metadata segments directly from the binary container format of images (JPEG, PNG, and WebP) without running raster image decoders (such as libjpeg or Pillow). This guarantees lossless preservation of compressed pixel entropy and avoids vulnerabilities present in image codecs.

## Parsing and Stripping Pipeline

1. **Format Identification**: Detected via initial signature bytes (`\xff\xd8\xff` for JPEG, `\x89PNG\r\n\x1a\n` for PNG, and `RIFF...WEBP` for WebP).
2. **JPEG Processing**:
   - Walks standard markers from `SOI` (0xFFD8) to `EOI` (0xFFD9).
   - Skips marker fill bytes (`0xFF...`).
   - Handles standalone markers without payload lengths (e.g. `RST0-RST7`, `TEM`).
   - Identifies `APP1` Exif (starts with `Exif\0\0`), `APP1` XMP (`http://ns.adobe.com/xap/1.0/\0`), `APP2` ICC (`ICC_PROFILE\0`), `APP13` IPTC, and `COM` comments.
   - Preserves `APP0` (JFIF) and `APP14` (Adobe color transform) as image rendering parameters.
   - Preserves scan entropy from `SOS` to `EOI`, handling escape sequences (`FF 00`).
   - Removes trailing garbage bytes after `EOI`.
3. **PNG Processing**:
   - Verifies CRC32 for each chunk.
   - Removes `eXIf`, `tEXt`, `zTXt`, `iTXt`, `tIME`, and optionally `iCCP`.
   - Leaves all other chunks (`IHDR`, `IDAT`, `PLTE`, `IEND`) byte-exact in order.
   - Truncates bytes following `IEND`.
4. **WebP Processing**:
   - Walks RIFF chunks.
   - Removes `EXIF` and `XMP ` chunks (and `ICCP` if requested).
   - Clears corresponding flags in the `VP8X` extended header (clearing bits `0x08`, `0x04`, `0x20`).
   - Recomputes and writes the 4-byte RIFF container size.
5. **TIFF Parser**:
   - Decodes Big-Endian (`MM`) and Little-Endian (`II`) TIFF headers.
   - Limits IFD loop count and recursion depth to avoid infinite loops or memory exhaustion on hostile inputs.
   - Safely extracts `Orientation` (tag `0x0112`) and tests for `GPSInfo` (tag `0x8825`).
