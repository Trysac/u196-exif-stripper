# exif-stripper

Strip EXIF, GPS, XMP, IPTC and comments from JPEG, PNG and WebP images byte-exactly. This utility avoids re-encoding pixel data, preserving image quality and avoiding dependency on heavy raster decoders.

## Installation

```bash
pip install exif-stripper
```

## Usage

```python
import exif_stripper

with open("photo.jpg", "rb") as f:
    data = f.read()

result = exif_stripper.strip(data)
print(f"Stripped {len(result.removed)} blocks; format={result.format}")
with open("photo_clean.jpg", "wb") as f:
    f.write(result.data)
```

## Public API Summary

- `exif_stripper.strip(data: bytes, *, keep_icc: bool = True, max_bytes: int = 100_000_000) -> StripResult`: Removes metadata and returns the stripped binary.
- `exif_stripper.inspect(data: bytes, *, max_bytes: int = 100_000_000) -> list[MetadataBlock]`: Enumerate metadata segments without modifying the file.
- `ExifStripError(code: str, message: str)`: Raised for `input_too_large`, `unsupported_format`, or `corrupt` data errors.

## Why not alternatives?

Unlike `exiftool` or `Pillow`, this library has zero runtime dependencies, requires no external binaries, performs no decoding, and guarantees byte-exact image entropy preservation while providing a report of exactly what was removed.

See [docs/SECURITY.md](docs/SECURITY.md) for vulnerability reporting.