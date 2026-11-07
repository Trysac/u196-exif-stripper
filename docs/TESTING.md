# Testing

## Overview

Tests are located in `tests/` and use `pytest` to exercise the library's public API (`strip`, `inspect`, `parse_tiff`).

## Test Structure

- `test_exif_stripper.py`: Validates the full stripping pipeline across JPEG, PNG, and WebP using manually constructed byte buffers that represent minimal valid containers.
- Fixture generation: Tests construct binary payloads byte-by-byte (e.g., `build_jpeg_criterion_1`) to verify the stripping logic without requiring external binary files.

## Coverage

- JPEG markers (APP1/Exif, COM, SOS).
- PNG chunks (e.g., `eXIf`, `tEXt`, `iCCP`).
- WebP RIFF headers and `VP8X` flag updates.
- Edge cases: Truncated headers, missing chunks, wrong CRCs, and inputs exceeding 100MB.
- TIFF IFD loop detection.