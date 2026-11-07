# Byte-exact container parsing without image decoding

Status: accepted (generated, pending human review)

## Context

Traditional image sanitization utilizes imaging libraries (such as Pillow or ImageMagick) to re-encode the image. This introduces generational compression artifacts, degrades image quality, alters pixel data, and consumes significant CPU/memory resources.

## Decision

Implement container-level byte slicing and rewriting based solely on the JPEG, PNG, and WebP specifications using Python standard library struct and zlib. Non-pixel metadata blocks (EXIF, XMP, IPTC, comments) are selectively removed while pixel streams and color management blocks (ICC) are preserved byte-for-byte.

## Consequences

Zero loss in pixel quality, extreme execution speed, minimal memory overhead, and no dependencies on native C graphics libraries. Pixel rotation based on EXIF orientation is intentionally deferred to callers.
