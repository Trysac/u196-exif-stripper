# Project record

## Objective

Strip EXIF, GPS, XMP, IPTC and comments from JPEG, PNG and WebP by rewriting container segments byte-exactly, without decoding or re-encoding pixels.

## Scope

- JPEG: Parsing and segment stripping from SOI to EOI.
- PNG: Chunk-based metadata removal with CRC validation.
- WebP: RIFF chunk stripping and VP8X flag updates.
- TIFF: IFD parsing for Orientation and GPS detection.

## Out of Scope

- HEIC, AVIF, or RAW file formats.
- Video metadata processing.
- Pixel rotation or image processing (e.g., resizing, re-encoding).
- XMP sidecar file generation.

## Effort metrics

| Metric | Value |
|---|---|
| Tokens (input / output) | 1402525 / 19709 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.1556 |

## Factory run u196 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | gemini-3.8-flash | yes | 4520 | 17398 | 0 | 0 | 0.0343 |
| fix-1 | gemini-3.8-flash | no | 26361 | 567 | 0 | 62768 | 0.0266 |
| audit | gemini-3.1-flash-lite | no | 135585 | 530 | 0 | 1045336 | 0.0608 |
| docs | gemini-3.1-flash-lite | no | 127955 | 1214 | 0 | 0 | 0.0338 |

Total: $0.1556. Prices: Anthropic list prices.
